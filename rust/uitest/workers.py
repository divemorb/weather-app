"""Parallel UI runs: one worker process per job (T3).

The scenarios run in worker processes instead of one after another: one job
per scenario, except ``sky``, which is split into one job per scene (the
``scene-*`` cases and ``sky-layer`` go to the first sky job) so that the
longest scenario is not the long pole. Each worker is a subprocess of
``run.py`` itself (``--worker``), with its own app, its own fake upstream
and its own Chromium per language, exactly as ``run_scenario`` does per
scenario today.

Worker k owns the app ports ``20000 + 100*k .. 20000 + 100*k + 99`` (a fixed
range per worker: two workers never pick the same port; on a busy port the
next one in the range is tried). The worker reads one job per line from
stdin (JSON, with an ``idx`` naming the job) and prints one line per job,
``UITEST-RESULT <json>`` (``{"idx": ..., "problems": {name: [problems...]}}``)
to stdout; everything else (tracebacks) goes to stderr.
"""
from __future__ import annotations

import json
import os
import pathlib
import queue
import subprocess
import sys
import threading
import time

PORT_BASE = 20000  # worker k may use the app ports 20000 + 100*k .. +100*k + 99
PORT_SPAN = 100
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
               "--worker", "--worker-index", str(index)]
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


def run_jobs(args, jobs: list[dict], job_checks: list[list[str]]) -> dict[str, list[str]]:
    """Run the jobs in worker processes (all workers kept busy) and return the
    merged problems, as a ``Results.problems`` dict. A worker that dies
    reports its in-flight job's checks as failed (as ``run_scenario`` does on
    a harness error), never as missing."""
    n = max(1, min(args.workers, MAX_WORKERS, len(jobs)))
    workers = [Worker(k, args) for k in range(n)]
    problems: dict[str, list[str]] = {}
    busy = [None] * n  # the job idx in flight on worker i
    next_idx = 0

    def dispatch(i: int) -> bool:
        nonlocal next_idx, remaining
        if next_idx >= len(jobs):
            return False
        idx = next_idx
        next_idx += 1
        if not workers[i].send({**jobs[idx], "idx": idx}):
            fail_job(idx)
            remaining -= 1
            workers[i].close()
            return False
        busy[i] = idx
        return True

    def absorb(line: str, idx: int):
        if line.startswith(RESULT_PREFIX):
            # extend, don't overwrite: a few checks (the sky's console and
            # requests) are added by every job and must be the union of what
            # every page of the scenario showed (as in the serial run)
            for name, ps in json.loads(line[len(RESULT_PREFIX):])["problems"].items():
                problems.setdefault(name, []).extend(ps)
        else:
            for name in job_checks[idx]:
                problems.setdefault(name, []).append(f"worker died: {line[:200]!r}")

    def fail_job(idx: int):
        for name in job_checks[idx]:
            problems.setdefault(name, []).append("the worker process died before this check ran")

    remaining = len(jobs)
    try:
        for i in range(n):
            dispatch(i)
        while remaining:
            progress = False
            for i in range(n):
                if busy[i] is None:
                    continue
                if workers[i].has_result():
                    absorb(workers[i].next_result(), busy[i])
                    busy[i] = None
                    remaining -= 1
                    dispatch(i)
                    progress = True
                    break
                if workers[i].dead():  # no result: the worker died mid-job
                    fail_job(busy[i])
                    busy[i] = None
                    remaining -= 1
                    workers[i].close()
                    progress = True
                    break
            if not progress:
                if all(b is None for b in busy):
                    # nothing in flight, yet jobs left: every worker died (or a
                    # send failed); hand them to a live worker, else fail them
                    live = [i for i in range(n) if not workers[i].dead()]
                    if not (live and dispatch(live[0])):
                        for idx in range(next_idx, len(jobs)):
                            fail_job(idx)
                        remaining = 0
                    continue
                time.sleep(0.02)
        deadline = time.monotonic() + 10
        for i in range(n):
            if busy[i] is not None and time.monotonic() < deadline:
                if workers[i].has_result():
                    absorb(workers[i].next_result(), busy[i])
                    busy[i] = None
            workers[i].close()
    except Exception:
        for worker in workers:
            worker.proc.kill()
        raise
    return problems
