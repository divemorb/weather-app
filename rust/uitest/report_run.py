"""The run of the report scenario: the flip and the picker, saving, the sky
following a fresh report, and Details scoring the reports (report_run).

``run`` runs one named part per phase of the scenario, in the same order the
page's actions have always run; each part is ``run_<phase>`` or ``<phase>``."""
from __future__ import annotations

import json

from expect import MODEL_LABELS, REPORT_FIT, REPORT_SKY_CASES, REPORT_TEXT, SCENE_LABEL
from page import Run, UIPage, has, norm
from report_save import run_save
from report_ui import (FIT, LANG_I, OPEN_CLEAR, _api, _iso, back_contrast,
                       clear_fresh, closed_problems, current, open_back, open_label_problems,
                       picker_problems, sel, settle_turn, shows_problems, state, visible, wait)

def run(run: Run):
    """The report scenario, in order: the desktop (the big view), saving, the sky after a
    fresh report, and Details scoring the reports."""
    clear_fresh(run.base)
    pg = desktop_checks(run)
    close_checks(run, pg)
    contrast_checks(run)
    fit_checks(run)
    locked_motion_checks(run)
    if "report-save" in run.names:
        run_save(run)
    if "sky-report-none" in run.names:
        run_sky(run)
    if "details-reports" in run.names:
        details_checks(run)
    clear_fresh(run.base)


def desktop_checks(run: Run) -> UIPage:
    """The big view: closed, open, the flip, the picker, the buttons.
    The back is left open on the page (the close check closes it there)."""
    pg = run.page()
    s = state(pg)
    run.add("report-closed", closed_problems(s))
    opens = [e for e in pg.ui("report-open") if e["visible"]]
    run.add("report-open", ([] if s.get("openLive") == 1 and len(opens) == 1 else
                            [f"{len(opens)} visible [data-test=report-open] ({s.get('openCount')} in the host), expected 1"])
        + open_label_problems(pg, opens, run.lang))
    before = s.get("rect")
    problems = open_back(pg)
    s = state(pg)
    if not problems:
        if not s["focusInBack"]:
            problems.append(f"the focus is on {s['focus']!r}, not inside the back")
        if before and any(abs(a - b) > 1 for a, b in zip(before[2:], s["rect"][2:])):
            problems.append(f"the tile changed its size: {before[2:]} -> {s['rect'][2:]}")
    run.add("report-flip", problems)
    if "report-picker" in run.names:
        run.add("report-picker", picker_problems(pg, run.lang) if not problems else ["the back did not open"])
    if "report-shows" in run.names:
        run.add("report-shows", shows_problems(pg, run.lang, s.get("scene")) if not problems else ["the back did not open"])
    if "report-buttons" in run.names:
        run.add("report-buttons", pg.js("__ui.controls()"))
    run.shot(pg, "report-back")
    return pg


def close_checks(run: Run, pg: UIPage):
    """Closing the back (the button, then Escape): the front again, the
    focus back on the open button, nothing saved."""
    if "report-close" in run.names:
        problems = pg.click(selector=sel("report-close"))
        problems += (wait(pg, lambda s: not s.get("backLive") and s.get("frontLive"), 1.5, "the front")
                     or settle_turn(pg))
        s = state(pg)
        if not problems and s["focus"] != "report-open":
            problems.append(f"the focus is on {s['focus']!r}, expected report-open")
        if current(run.base):
            problems.append("closing saved a report")
        run.add("report-close", problems)
    if "report-escape" in run.names:
        problems = open_back(pg)
        if not problems:
            pg.p.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape",
                                                 "windowsVirtualKeyCode": 27})
            pg.p.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "code": "Escape",
                                                 "windowsVirtualKeyCode": 27})
            problems = wait(pg, lambda s: not s.get("backLive") and s.get("frontLive"), 1.5, "Escape to close")
        run.add("report-escape", problems + (["Escape saved a report"] if current(run.base) else []))
    run.done(pg)


def contrast_checks(run: Run):
    """The back's contrast, light and dark."""
    for theme in ("light", "dark"):
        if f"report-contrast-{theme}" in run.names:
            pg = run.page(scheme=theme)
            run.add(f"report-contrast-{theme}", back_contrast(pg))
            run.done(pg)


def fit_checks(run: Run):
    """The back fits the host everywhere, the host keeps its size, the
    big view doesn't scroll; the open button clears the fresh badge."""
    clear = []
    for variant, (w, h, query) in REPORT_FIT.items():
        if f"report-fit-{variant}" not in run.names:
            continue
        pg = run.page(width=w, height=h, query=query)
        pg.js("document.querySelector('[data-report-host]').scrollIntoView({block: 'center'})")
        before = state(pg)
        if not query:
            clear += pg.js(OPEN_CLEAR)
        problems = open_back(pg)
        if not problems:
            after = state(pg)
            problems = pg.js(FIT)
            if any(abs(a - b) > 1 for a, b in zip(before["rect"][2:], after["rect"][2:])):
                problems.append(f"the tile changed its size: {before['rect'][2:]} -> {after['rect'][2:]}")
            if query == "" and w >= 1000 and after["sh"] > after["ih"] + 1:
                problems.append(f"the big view scrolls with the back open ({after['sh']} > {after['ih']} px)")
        run.add(f"report-fit-{variant}", problems)
        run.shot(pg, f"report-fit-{variant}", full=False)
        run.done(pg)
    if "report-open-clear" in run.names:
        run.add("report-open-clear", clear)


def locked_motion_checks(run: Run):
    """The locked wall display shows the open button; the turn animates
    (report-motion), but not with prefers-reduced-motion (report-still)."""
    if "report-locked" in run.names:
        pg = run.page(width=1280, height=800, query="?kiosk")
        n = len(visible(pg, "report-open"))
        run.add("report-locked", [f"{n} visible [data-test=report-open] on the locked wall display"] if n else [])
        run.done(pg)
    if "report-motion" in run.names:
        for check, reduced in (("report-motion", False), ("report-still", True)):
            pg = run.page(reduced=reduced)
            running = pg.js("""(() => { const h = document.querySelector('[data-report-host]');
                h.querySelector('[data-test="report-open"]').click();
                return document.getAnimations().filter((a) => a.playState === 'running'
                  && a.effect && a.effect.target && (h === a.effect.target || h.contains(a.effect.target)))
                  .map((a) => a.animationName || a.transitionProperty || 'animation'); })()""")
            if reduced:
                run.add(check, [f"the turn animates with prefers-reduced-motion: {running}"] if running else [])
            else:
                run.add(check, [] if running else ["no animation or transition runs in the tile when it turns"])
            run.done(pg)


def details_checks(run: Run):
    """D: Details scores the saved reports, on the big and the 360 px view."""
    pg = run.page(query="?detailed")
    pg.js("__ui.openDetails()")
    pg.settle()
    run.add("details-reports", details_problems(pg, run.lang, run.base))
    run.shot(pg, "report-details")
    run.done(pg)
    pg = run.page(width=360, height=740, query="?detailed")
    pg.js("__ui.openDetails()")
    pg.settle()
    info = pg.js("__ui.page()")
    run.add("details-reports-fit", ([] if info["sw"] <= 361 else [f"page is {info['sw']} px wide at 360 px"])
            + [f"at 360 px: {p}" for p in pg.js('__ui.sticksOut("details")')])
    run.done(pg)


def sky_case(run: Run, case: str, fields: dict, clock: str | None, scene: str) -> None:
    """C: one case (sky-report-<case>): with a fresh report faked from
    another device, the sky shows its scene and the sky-reason names it."""
    lang = run.lang
    at = clock or run.sc["now"]
    rep = {"id": 90, "intensity": None, "confirms": False, **fields, "observed_at": _iso(at, -5)}
    pg = UIPage(run.browser, run.base, at, lang,
                fakes={"/api/reports/current": [(200, json.dumps({"report": rep}))] * 8})
    problems = []
    got = pg.js("document.documentElement.getAttribute('data-scene')")
    if got != scene:
        problems.append(f"data-scene {got!r} with a fresh {fields} report, expected {scene!r}")
    key = "sky-confirmed" if rep["confirms"] else "sky"
    want = REPORT_TEXT[key][lang].format(scene=SCENE_LABEL[scene][LANG_I[lang]],
                                         time=pg.times([rep["observed_at"]])[0])
    reason = visible(pg, "sky-reason")
    if len(reason) != 1 or norm(reason[0]["text"]) != want:
        problems.append(f"sky-reason {[r['text'] for r in reason]}, expected {want!r}")
    run.add(f"sky-report-{case}", problems)
    run.done(pg)


def sky_none(run: Run) -> None:
    """C: without a fresh report the sky-reason is the sky's own (no report
    named in it, sky-report-none)."""
    lang = run.lang
    pg = UIPage(run.browser, run.base, run.sc["now"], lang,
                fakes={"/api/reports/current": [(200, '{"report": null}')] * 8})
    reason = visible(pg, "sky-reason")
    text = reason[0]["text"] if reason else ""
    mine = "by you" if lang == "en" else "von dir"
    run.add("sky-report-none", [f"sky-reason names a report without one: {text!r}"] if mine in text else
            ([] if reason else ["no sky-reason shown"]))
    run.done(pg)


def run_sky(run: Run):
    """The sky follows a fresh report, with faked answers; and the
    sky without one (sky-report-none)."""
    for case, (fields, clock, scene) in REPORT_SKY_CASES.items():
        if f"sky-report-{case}" not in run.names:
            continue
        sky_case(run, case, fields, clock, scene)
    sky_none(run)


def details_problems(pg, lang, base) -> list[str]:
    """The Details' report-scoring section: the title, the summary, the note, and the
    per-model rows in best hit-rate order, matching the API's user_reports."""
    i = LANG_I[lang]
    status, body = _api(base, "GET", "/api/model-accuracy")
    ur = (body or {}).get("user_reports") if status == 200 else None
    if not isinstance(ur, dict):
        return [f"/api/model-accuracy has no user_reports (status {status})"]
    out = []
    sec = visible(pg, "accuracy-reports")
    if len(sec) != 1:
        return [f"{len(sec)} visible [data-test=accuracy-reports], expected 1"]
    if not has(sec[0]["text"], REPORT_TEXT["acc-title"][lang]):
        out.append(f"accuracy-reports lacks its title {REPORT_TEXT['acc-title'][lang]!r}")
    inside = pg.js("(() => { const d = document.querySelector('[data-test=\"details\"]'); "
                   "const s = document.querySelector('[data-test=\"accuracy-reports\"]'); return !!d && !!s && d.contains(s); })()")
    if not inside:
        out.append("accuracy-reports is not inside the Details card")
    if not ur["models"]:
        none = visible(pg, "accuracy-reports-none")
        if len(none) != 1 or norm(none[0]["text"]) != REPORT_TEXT["acc-none"][lang]:
            out.append(f"accuracy-reports-none: {[n['text'] for n in none]}, expected {REPORT_TEXT['acc-none'][lang]!r}")
        return out
    summary = visible(pg, "accuracy-reports-summary")
    want = REPORT_TEXT["acc-summary"][lang].format(hours=ur["hours"], confirmed=ur["confirmed_hours"])
    if len(summary) != 1 or norm(summary[0]["text"]) != want:
        out.append(f"accuracy-reports-summary: {[s['text'] for s in summary]}, expected {want!r}")
    note = visible(pg, "accuracy-reports-note")
    if len(note) != 1 or norm(note[0]["text"]) != norm(REPORT_TEXT["acc-note"][lang]):
        out.append(f"accuracy-reports-note: {[n['text'][:60] for n in note]}, expected the fixed note")
    order = sorted(ur["models"], key=lambda m: -ur["models"][m]["event_accuracy"])  # stable: ties keep the API order
    rows = visible(pg, "accuracy-reports-row")
    got = [r["attrs"].get("data-model") for r in rows]
    if got != order:
        return out + [f"accuracy-reports-row data-model order {got}, expected {order} (best hit rate first)"]
    locale = "en-US" if lang == "en" else "de-DE"
    for r, model in zip(rows, order):
        m = ur["models"][model]
        pct = pg.js(f"new Intl.NumberFormat({locale!r}, {{style: 'percent', maximumFractionDigits: 0}})"
                    f".format({m['event_accuracy']})")
        cells = pg.js(f"[...document.querySelectorAll('[data-test=\"accuracy-reports-row\"][data-model=\"{model}\"] td')]"
                      ".map((td) => td.textContent.trim())")
        want = [MODEL_LABELS[model], str(m["n_samples"]), str(m["hits"]), str(m["misses"]), str(m["false_alarms"]), pct]
        if [norm(c) for c in cells] != [norm(w) for w in want]:
            out.append(f"row {model}: cells {cells}, expected {want}")
    return out


def none_problems(pg, lang) -> list[str]:
    """Details without any report (the accuracy scenario): the none line, no rows."""
    out = []
    none = visible(pg, "accuracy-reports-none")
    if len(none) != 1 or norm(none[0]["text"]) != REPORT_TEXT["acc-none"][lang]:
        out.append(f"accuracy-reports-none: {[n['text'] for n in none]}, expected {REPORT_TEXT['acc-none'][lang]!r}")
    if visible(pg, "accuracy-reports-row"):
        out.append("accuracy-reports-row shown without reports")
    return out
