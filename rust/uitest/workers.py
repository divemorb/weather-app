"""Parallel UI runs: one worker process per job.
One job per scenario and language (``wizard`` stays one job, its German
validation before the English save), except ``sky`` (one per scene) and
``rain`` (the en-only flow checks in a second job); each worker is a
``run.py --worker`` subprocess with its own app, fake upstream and Chromium
per language. Worker k owns app ports ``20000 + 100*k .. 20000 + 100*k + 99``
(disjoint ranges, a busy port tries the next); jobs arrive on stdin as one
JSON line each (with an ``idx``); per job the worker prints ``UITEST-RESULT
<json>`` to stdout, everything else to stderr.
"""
from __future__ import annotations

import fnmatch
import json
import os
import pathlib
import queue
import subprocess
import sys
import threading
import time

from cdp import Browser
from expect import LOCALES, SCENES
from names import SCENARIO_LANGS, check_names
from scenario import PORT_BASE, PORT_SPAN, Results, run_scenario

MAX_WORKERS = 8
RESULT_PREFIX = "UITEST-RESULT "


def cgroup_cpus() -> float | None:
    """The cgroup CPU quota in whole CPUs, or None when there is no quota."""
    try:
        text = pathlib.Path("/sys/fs/cgroup/cpu.max").read_text().split()
    except OSError:
        text = []
    if text and text[0] != "max":
        return int(text[0]) / int(text[1])
    try:  # cgroup v1
        quota = int(pathlib.Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
        if quota > 0:
            return quota / int(pathlib.Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
    except (OSError, ValueError):
        pass
    return None


def default_workers() -> int:
    """min(6, the CPUs available), the CPUs from the affinity mask and the
    cgroup quota when set; never more than 8, never less than 1."""
    cpus = float(len(os.sched_getaffinity(0)))
    quota = cgroup_cpus()
    if quota is not None:
        cpus = min(cpus, quota)
    return max(1, min(6, int(cpus)))


# The scenarios, longest first (report, live and rain take the longest; the
# sky jobs next; the small scenarios last).
JOB_RANK = {"report": 0, "live": 1, "rain": 2, "sky": 3,
            "errors": 4, "accuracy": 4, "unconfigured": 4, "wizard": 4,
            "fallback": 4, "report-glance": 4}


class Worker:
    """One worker process: it reads jobs from stdin, one per line, and prints
    a RESULT_PREFIX line per job to stdout (in the order the jobs were
    given). Stderr is inherited (for tracebacks); it never mixes into the
    result stream."""

    def __init__(self, index: int, args):
        cmd = [sys.executable, str(pathlib.Path(__file__).resolve().parent / "run.py"),
               "--worker", "--worker-index", str(args.worker_offset + index)]
        if args.binary != "/target/debug/wetter":
            cmd += ["--binary", args.binary]
        if args.only:
            cmd += ["--only", *args.only]
        if args.lang:
            cmd += ["--lang", *args.lang]
        if args.shots:
            cmd += ["--shots", str(args.shots)]
        if args.no_unit:
            cmd += ["--no-unit"]
        if args.static:
            cmd += ["--static", str(args.static)]
        if args.backend_log:  # the worker appends ".<index>" itself
            cmd += ["--backend-log", args.backend_log]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=None, text=True, bufsize=1)
        self.queue: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.proc.stdout:
            self.queue.put(line.rstrip("\n"))

    def send(self, job: dict) -> bool:
        try:
            self.proc.stdin.write(json.dumps(job) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            return False
        return True

    def has_result(self) -> bool:
        return not self.queue.empty()

    def next_result(self) -> str:
        return self.queue.get()

    def dead(self) -> bool:
        return self.proc.poll() is not None

    def close(self):
        try:
            self.proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:  # reap the process (it exits on the end of stdin)
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)


class JobPool:
    """The workers' dispatch loop: one job per worker (``busy[i]`` the job idx
    in flight on worker i), the results merged into ``problems`` as a
    ``Results.problems`` dict. A worker that dies reports its in-flight
    job's checks as failed (as ``run_scenario`` does on a harness error),
    never as missing."""

    def __init__(self, args, jobs: list[dict], job_checks: list[list[str]]):
        self.jobs, self.job_checks = jobs, job_checks
        n = max(1, min(args.workers, MAX_WORKERS, len(jobs)))
        self.workers = [Worker(k, args) for k in range(n)]
        self.problems: dict[str, list[str]] = {}
        self.busy = [None] * n
        self.next_idx = 0
        self.remaining = len(jobs)
        self.started: dict[int, float] = {}  # job idx -> monotonic start
        self.took: dict[int, float] = {}  # job idx -> seconds, for the timing line

    def fail_job(self, idx: int):
        for name in self.job_checks[idx]:
            self.problems.setdefault(name, []).append("the worker process died before this check ran")

    def dispatch(self, i: int) -> bool:
        """Give worker i the next job (or close it when there are none left)."""
        if self.next_idx >= len(self.jobs):
            return False
        idx = self.next_idx
        self.next_idx += 1
        if not self.workers[i].send({**self.jobs[idx], "idx": idx}):
            self.fail_job(idx)
            self.remaining -= 1
            self.workers[i].close()
            return False
        self.busy[i] = idx
        self.started[idx] = time.monotonic()
        return True

    def absorb(self, line: str, idx: int):
        self.took[idx] = time.monotonic() - self.started.get(idx, time.monotonic())
        if line.startswith(RESULT_PREFIX):
            # extend, don't overwrite: a few checks (the sky's console and
            # requests) are added by every job and must be the union of what
            # every page of the scenario showed (as in the serial run)
            for name, ps in json.loads(line[len(RESULT_PREFIX):])["problems"].items():
                self.problems.setdefault(name, []).extend(ps)
        else:
            for name in self.job_checks[idx]:
                self.problems.setdefault(name, []).append(f"worker died: {line[:200]!r}")

    def drain_deadline(self) -> None:
        """The in-flight results that still land before the deadline, then
        the workers closed."""
        deadline = time.monotonic() + 10
        for i, worker in enumerate(self.workers):
            if self.busy[i] is not None and time.monotonic() < deadline:
                if worker.has_result():
                    self.absorb(worker.next_result(), self.busy[i])
                    self.busy[i] = None
            worker.close()

    def job_name(self, idx: int) -> str:
        """The scenario of a job, its language when the job has one, and the
        part when split (its tag, or the sky's scene as its first check)."""
        job = self.jobs[idx]
        only = job.get("only")
        part = job.get("tag") or (only[0] if only else None)
        lang = f"/{job['langs'][0]}" if job.get("langs") else ""
        return job["scenarios"][0] + lang + (f"[{part}]" if part else "")

    def timing_line(self) -> str:
        """The jobs, slowest first: where the suite's wall time goes."""
        order = sorted(self.took, key=self.took.get, reverse=True)
        return "uitest jobs, slowest first: " + ", ".join(
            f"{self.job_name(i)} {self.took[i]:.0f} s" for i in order)

    def poll(self) -> dict[str, list[str]]:
        """Serve the jobs to the workers until every one is absorbed; on a
        harness error the workers are killed and the error re-raised."""
        try:
            for i in range(len(self.workers)):
                self.dispatch(i)
            while self.remaining:
                progress = False
                for i in range(len(self.workers)):
                    if self.busy[i] is None:
                        continue
                    if self.workers[i].has_result():
                        self.absorb(self.workers[i].next_result(), self.busy[i])
                        self.busy[i] = None
                        self.remaining -= 1
                        self.dispatch(i)
                        progress = True
                        break
                    if self.workers[i].dead():  # no result: the worker died mid-job
                        self.fail_job(self.busy[i])
                        self.busy[i] = None
                        self.remaining -= 1
                        self.workers[i].close()
                        progress = True
                        break
                if not progress:
                    if all(b is None for b in self.busy):
                        # nothing in flight, yet jobs left: every worker died (or a
                        # send failed); hand them to a live worker, else fail them
                        live = [i for i in range(len(self.workers)) if not self.workers[i].dead()]
                        if not (live and self.dispatch(live[0])):
                            for idx in range(self.next_idx, len(self.jobs)):
                                self.fail_job(idx)
                            self.remaining = 0
                        continue
                    time.sleep(0.02)
            self.drain_deadline()
            print(self.timing_line(), file=sys.stderr)
        except Exception:
            for worker in self.workers:
                worker.proc.kill()
            raise
        return self.problems


def run_jobs(args, jobs: list[dict], job_checks: list[list[str]]) -> dict[str, list[str]]:
    """Run the jobs in worker processes (all workers kept busy) and return
    the merged problems (see ``JobPool``)."""
    return JobPool(args, jobs, job_checks).poll()


# --- the jobs (one per scenario and language, sky one per scene, rain en
# split off its flow checks) ---------------------------------------------------

# The rain checks that need their own page or a long wait (the timed reload,
# the refresh flows, the reduced motion and the rainy tracks): they run in a
# job of their own (rain_flow_names), never on the same job as the content
# pages they would otherwise follow.
RAIN_FLOW = ["reduced-motion", "refresh-render-error", "refresh-config-retry", "rain-tracks", "reload-fires"]


def rain_flow_names() -> list[str]:
    """The rain/en flow job's checks: RAIN_FLOW plus console and requests
    (the per-page aggregations, kept in every job: the merge takes the union,
    so an error on a flow page still fails them, as in the serial run)."""
    return RAIN_FLOW + ["console", "requests"]


def _sky_scene_of(check: str) -> str | None:
    """The scene of a sky check (``motion-<scene>``, ``still-<scene>``,
    ``glass-<scene>``, ``contrast-<scene>-<theme>``), or None for the common ones."""
    for prefix in ("motion-", "still-", "glass-", "contrast-"):
        if check.startswith(prefix):
            rest = check[len(prefix):]
            if prefix == "contrast-":  # contrast-<scene>-<theme>
                rest = rest.rsplit("-", 1)[0]
            return rest
    return None


def sky_job_names() -> list[list[str]]:
    """The sky's checks, one list per job: first the common ones (the
    ``scene-*`` cases, ``sky-layer`` and ``layout-*``), then the checks of
    each scene, so that no single job is the long pole of the whole run.
    ``console`` and ``requests`` aggregate over the pages of every job, so
    they are kept in all of them (the merge takes the union, as in the serial
    run: an error on a per-scene page still fails them)."""
    names = check_names("sky", "en")
    common = [c for c in names if c in ("sky-layer",) or c.startswith(("scene-", "layout-"))]
    jobs = [common]
    for scene in SCENES:
        jobs.append([c for c in names if _sky_scene_of(c) == scene])
    for job in jobs:  # the per-page aggregations, in every job
        job += ["console", "requests"]
    return jobs


def build_jobs(args, scenarios: list[str], langs: list[str]) -> tuple[list[dict], list[list[str]]]:
    """The jobs to run, longest first, and the check names each job is
    responsible for (a job that dies reports its checks as failed). Every
    scenario that runs both languages gets one job per language (each with its
    own app and database, so a check never reads what the other language's run
    left behind); ``wizard`` stays one job (``SCENARIO_LANGS``: the German
    validation runs before the English save). rain's en-only flow checks (the
    timed reload, the refresh flows, the reduced motion and the tracks) run in
    a second rain/en job (``only`` subset, like the sky's scene jobs)."""
    jobs: list[tuple[int, dict, list[str]]] = []
    for name in scenarios:
        if name != "sky":
            for lang in SCENARIO_LANGS.get(name, ["en", "de"]):
                if lang not in langs:
                    continue
                if name == "wizard":
                    continue
                names = check_names(name, lang)
                if name == "rain" and lang == "en":  # the content pages and the flow pages split
                    flow = rain_flow_names()
                    for only, tag in (([c for c in names if c not in flow], "content"), (flow, "flows")):
                        jobs.append((JOB_RANK[name],
                                     {"scenarios": [name], "langs": [lang], "only": only, "tag": tag},
                                     [f"{name}/{lang}/{c}" for c in only]))
                    continue
                jobs.append((JOB_RANK.get(name, 9),
                             {"scenarios": [name], "langs": [lang], "only": None},
                             [f"{name}/{lang}/{c}" for c in names]))
            if name == "wizard" and any(l in langs for l in SCENARIO_LANGS["wizard"]):
                jobs.append((JOB_RANK["wizard"], {"scenarios": [name], "only": None},
                             [f"{name}/{lang}/{c}" for lang in SCENARIO_LANGS["wizard"] if lang in langs
                              for c in check_names(name, lang)]))
            continue
        for subset in sky_job_names():
            jobs.append((JOB_RANK["sky"], {"scenarios": ["sky"], "only": subset},
                         [f"sky/en/{c}" for c in subset]))
    jobs.sort(key=lambda t: t[0])
    return [j for _, j, _ in jobs], [names for _, _, names in jobs]


def run_job(args, job: dict) -> dict[str, list[str]]:
    """One job in a worker process (its own app, fake upstream and Chromium,
    as ``run_scenario`` does per scenario today): ``{"scenarios": [...],
    "langs": [language] or all the scenario's languages when missing,
    "only": [check names] or None, "tag": the job's part name for the timing
    line (the rain split)}``; returns the problems, keyed by the checks' full
    names."""
    res = Results()
    want_langs = args.lang or list(LOCALES)
    job_langs = [l for l in job.get("langs", []) if l in want_langs]
    for name in job["scenarios"]:  # all of the scenario's languages when the job names none
        if not job_langs:
            job_langs = [lang for lang in SCENARIO_LANGS.get(name, ["en", "de"]) if lang in want_langs]
    browsers = {lang: Browser(lang=LOCALES[lang]) for lang in job_langs}
    try:
        for name in job["scenarios"]:
            run_scenario(name, browsers, args, res, checks=job.get("only"))
    finally:
        for b in browsers.values():
            b.close()
    return res.problems


def worker_main() -> int:
    """``--worker``: read the jobs from stdin (one JSON per line) and print
    one RESULT line per job, in the order the jobs were given. ``parse_args``
    lives in ``run`` (nothing but ``run`` may import it), so import it here,
    only ever reached from ``run.main`` once ``run`` is loaded."""
    from run import parse_args

    args = parse_args()
    args.selected = lambda name: not args.only or any(fnmatch.fnmatch(name, p) for p in args.only)
    args.port_base = PORT_BASE + PORT_SPAN * args.worker_index
    args.log = (open(f"{args.backend_log}.{args.worker_index}", "a") if args.backend_log
                else subprocess.DEVNULL)
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            job = json.loads(line)
            print(RESULT_PREFIX + json.dumps({"idx": job["idx"], "problems": run_job(args, job)}),
                  flush=True)
    finally:
        if args.log is not subprocess.DEVNULL:
            args.log.close()
    return 0
