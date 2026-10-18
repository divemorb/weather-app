"""Saving in the report run: the report-save checks, the sky after the save,
the undo, the intensity choices, confirming, a failing save and a fresh
report from elsewhere (report_save)."""
from __future__ import annotations

import json
import time

from expect import (REPORT_INTENSITY, REPORT_SAVE_S, REPORT_SCENE_KIND, REPORT_TEXT,
                    SCENE_LABEL)
from page import Run, norm
from report_ui import (FIT, LANG_I, _iso, clear_fresh, current, kind_scene, line_problems,
                       open_back, sel, state, visible)


def saved_and_back(pg, base: str, want: dict) -> list[str]:
    """Wait for the save to land (GET /api/reports/current) and the tile to
    turn back; check the saved report's fields against ``want``."""
    end = time.monotonic() + REPORT_SAVE_S
    got = None
    while time.monotonic() < end:
        got = current(base)
        s = state(pg)
        if got and not s.get("backLive") and s.get("frontLive"):
            break
        pg.p.wait_idle(timeout=0.3, idle=0.1)
    out = []
    if not got:
        return [f"nothing saved within {REPORT_SAVE_S} s (GET /api/reports/current is null)"]
    for k, v in want.items():
        if got.get(k) != v:
            out.append(f"saved {k}={got.get(k)!r}, expected {v!r} (report {got})")
    s = state(pg)
    if s.get("backLive") or not s.get("frontLive"):
        out.append(f"the tile did not turn back within {REPORT_SAVE_S} s")
    return out


def save_fog(run: Run, pg) -> dict | None:
    """Save a fog report from 15 min ago: the saved fields, the front's
    report line (report-save), the sky after the save (sky-after-save)."""
    problems = open_back(pg)
    problems = problems or pg.click(selector=sel("report-when", minutes="15"))
    problems = problems or pg.click(selector=sel("report-kind", kind="fog"))
    problems = problems or saved_and_back(pg, run.base, {"kind": "fog", "intensity": None, "confirms": False,
                                                         "observed_at": _iso(run.sc["now"], -15)})
    rep = current(run.base)
    if not problems and rep:
        problems = line_problems(pg, run.lang, rep, run.sc["now"])
    run.add("report-save", problems)
    run.shot(pg, "report-saved")
    if "sky-after-save" in run.names:
        sky_after_save(run, pg, rep)
    return rep


def sky_after_save(run: Run, pg, rep) -> None:
    """After the save, the sky follows the fresh report (data-scene and
    sky-reason)."""
    lang, now = run.lang, run.sc["now"]
    problems = []
    if rep:
        scene = kind_scene(rep, rep["observed_at"])
        got = pg.js("document.documentElement.getAttribute('data-scene')")
        if got != scene:
            problems.append(f"data-scene {got!r} after saving {rep['kind']}, expected {scene!r}")
        want = REPORT_TEXT["sky"][lang].format(scene=SCENE_LABEL[scene][LANG_I[lang]],
                                               time=pg.times([rep["observed_at"]])[0])
        reason = visible(pg, "sky-reason")
        if len(reason) != 1 or norm(reason[0]["text"]) != want:
            problems.append(f"sky-reason {[r['text'] for r in reason]}, expected {want!r}")
    else:
        problems.append("nothing saved (see report-save)")
    run.add("sky-after-save", problems)


def undo_report(run: Run, pg, rep) -> None:
    """Undo the just saved report: nothing on the API, the front's
    report line gone (report-undo)."""
    problems = [] if rep else ["nothing saved (see report-save)"]
    if rep:
        problems = pg.click(selector=sel("report-undo"))
        end = time.monotonic() + REPORT_SAVE_S
        while current(run.base) and time.monotonic() < end:
            pg.p.wait_idle(timeout=0.3, idle=0.1)
        if current(run.base):
            problems.append("the report is still there after undo")
        n = pg.js("[...document.querySelectorAll('[data-report-host] [data-test=\"report-line\"]')]"
                  ".filter((el) => el.checkVisibility()).length")
        if n:
            problems.append("report-line still visible after undo")
    run.add("report-undo", problems)
    run.done(pg)


def save_intensity(run: Run, check: str, button: tuple[str, dict], want: str | None) -> None:
    """The intensity choices (report-intensity) and a save with it, or
    skipping it (report-skip: no intensity on the report)."""
    lang, now = run.lang, run.sc["now"]
    clear_fresh(run.base)
    pg = run.page()
    problems = open_back(pg) or pg.click(selector=sel("report-kind", kind="rain"))
    if not problems:
        choices = visible(pg, "report-intensity")
        got = [(c["attrs"].get("data-intensity"), norm(c["name"])) for c in choices]
        exp = [(k, v[LANG_I[lang]]) for k, v in REPORT_INTENSITY.items()]
        if got != exp:
            problems.append(f"report-intensity (data-intensity, name) {got}, expected {exp}")
        skip = visible(pg, "report-intensity-skip")
        if len(skip) != 1 or norm(skip[0]["name"]) != REPORT_TEXT["skip"][lang]:
            problems.append(f"report-intensity-skip: {[x['name'] for x in skip]}, expected {REPORT_TEXT['skip'][lang]!r}")
        if current(run.base):
            problems.append("rain was saved before its intensity was chosen")
        problems += pg.js(FIT)
    if not problems:
        problems = pg.click(selector=sel(button[0], **button[1]))
        problems = problems or saved_and_back(pg, run.base,
                                              {"kind": "rain", "intensity": want, "confirms": False,
                                               "observed_at": now})
        rep = current(run.base)
        if not problems and rep:
            problems = line_problems(pg, lang, rep, now)
    run.add(check, problems)
    run.done(pg)


def save_confirm(run: Run) -> None:
    """Confirming ("that's right") saves what the page shows (report-confirm)."""
    lang, now = run.lang, run.sc["now"]
    clear_fresh(run.base)
    pg = run.page()
    scene = state(pg).get("scene")
    want = REPORT_SCENE_KIND.get(scene)
    problems = [] if want else [f"the page shows {scene!r}, which no report kind names (the check needs one)"]
    problems = problems or open_back(pg) or pg.click(selector=sel("report-confirm"))
    if not problems:
        problems = saved_and_back(pg, run.base, {"kind": want[0], "intensity": want[1], "confirms": True,
                                                 "observed_at": now})
        rep = current(run.base)
        if not problems and rep:
            problems = line_problems(pg, lang, rep, now)
    run.add("report-confirm", problems)
    run.done(pg)
    clear_fresh(run.base)


def save_error(run: Run) -> None:
    """A failing save (a faked 500): the error message, the back stays,
    nothing on the front (report-error)."""
    lang = run.lang
    pg = run.page(fakes={"/api/reports": [(500, json.dumps({"detail": "boom"}))] * 4})
    problems = open_back(pg) or pg.click(selector=sel("report-kind", kind="snow"))
    if not problems:
        pg.p.wait_idle(timeout=2, idle=0.3)
        err = visible(pg, "report-error")
        if len(err) != 1 or norm(err[0]["text"]) != REPORT_TEXT["failed"][lang]:
            problems.append(f"report-error: {[e['text'] for e in err]}, expected {REPORT_TEXT['failed'][lang]!r}")
        if not state(pg).get("backLive"):
            problems.append("the back closed although nothing was saved")
        if visible(pg, "report-line"):
            problems.append("report-line shown although nothing was saved")
    run.add("report-error", problems)
    pg.close()  # its console has the faked 500 on purpose


def save_fresh(run: Run) -> None:
    """A fresh report from earlier (another device): the front shows it
    on load (report-line-fresh)."""
    rep = {"id": 77, "kind": "snow", "intensity": None, "confirms": False, "observed_at": _iso(run.sc["now"], -10)}
    pg = run.page(fakes={"/api/reports/current": [(200, json.dumps({"report": rep}))] * 8})
    run.add("report-line-fresh", line_problems(pg, run.lang, rep, run.sc["now"]))
    run.done(pg)


def undo_settled(pg, rep: dict) -> list[str]:
    """Wait until the undo's DELETE has been faked (the 500 served) and the
    page is idle again (a re-read, when it happens, has landed and rendered)."""
    end = time.monotonic() + REPORT_SAVE_S
    while pg.p.fakes_left() and time.monotonic() < end:
        pg.p.pump()
        time.sleep(0.05)
    if pg.p.fakes_left():
        return [f"the undo's DELETE /api/reports/{rep['id']} never reached the page"]
    pg.p.wait_idle(timeout=REPORT_SAVE_S, idle=0.1)
    pg.settle()
    return []


def undo_failed(run: Run) -> None:
    """A failed undo (a faked 500 on the DELETE): the page re-reads
    /api/reports/current and the front's line still shows the report that is
    really still there (report-undo-failed)."""
    clear_fresh(run.base)
    pg = run.page()
    rep = save_fog(run, pg)
    if not rep:
        run.add("report-undo-failed", ["nothing saved (see report-save)"])
        run.done(pg)
        return
    pg.p.fake({"DELETE /api/reports/*": [(500, json.dumps({"detail": "boom"}))]})
    problems = pg.click(selector=sel("report-undo")) or undo_settled(pg, rep)
    if not problems and current(run.base) != rep:
        problems.append(f"the report after the failed undo is {current(run.base)!r}, expected {rep!r}")
    problems = problems or line_problems(pg, run.lang, rep, run.sc["now"])
    run.add("report-undo-failed", problems)
    pg.close()  # its console has the faked 500 on purpose


def run_save(run: Run):
    """Saving: fog, the sky after the save, undo, the intensity
    choices, confirming, a failing save, a fresh report from elsewhere."""
    clear_fresh(run.base)
    pg = run.page()
    rep = save_fog(run, pg)
    undo_report(run, pg, rep)
    save_intensity(run, "report-intensity", ("report-intensity", {"intensity": "heavy"}), "heavy")
    save_intensity(run, "report-skip", ("report-intensity-skip", {}), None)
    save_confirm(run)
    save_error(run)
    save_fresh(run)
