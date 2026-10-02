/* details.js — the Details card (step W7): the technical parts.
 *
 * One <details data-test="details"> (closed on load) after the forecast;
 * details.js fills its body from four endpoints, fetched by app.js on
 * every refresh:
 *   - the signals (radar, models, ensemble) and the weights in use,
 *     from /api/rain-probability (without data: a dash),
 *   - the refresh countdowns (radar, models, next page reload) from
 *     /api/schedule, ticking once a second,
 *   - the data sources with their age and errors, from /api/sources,
 *   - the model accuracy table, from /api/model-accuracy (rows with
 *     enough data first, best hit rate first; below the sample minimum
 *     greyed; the table explains itself in the note under it).
 *
 * The page reload moves here too: 10 s after the next scheduled backend
 * refresh, at the latest every 60 s (the old scheduleNextLoad); the
 * callback is set by app.js.
 */
import {
  DASH, fmtAge, fmtCountdown, fmtMm, fmtPercent, modelLabel, rainObserved, sortAccuracy,
} from "./format.js";
import { t } from "./i18n.js";

const $ = (id) => document.getElementById(id);

const els = {
  title: $("details-title"),
  body: $("details-body"),
};

const REFRESH_MS = 60_000; // reload at least this often
const RELOAD_AFTER_REFRESH_MS = 10_000; // after a scheduled backend refresh
const SOURCE_ORDER = ["radar", "current", "forecast", "ensemble"];

let lang = "en";
let locale = "en-US";
let onReload = () => {};
let schedule = null; // { offsetMs, jobs } from /api/schedule
let loadTimer = null;
let nextLoadAt = 0; // Date.now() ms of the next page reload
let valueEls = null; // the three countdown value spans

/* ---- the schedule and the reload (the old countdown.js behaviour) ---- */

function applySchedule(s) {
  if (!s || !s.jobs) {
    schedule = null;
    return;
  }
  // server clock minus browser clock, so the countdown matches the server
  const offsetMs = Date.parse(s.server_time_utc) - Date.now();
  schedule = { offsetMs: isNaN(offsetMs) ? 0 : offsetMs, jobs: s.jobs };
}

function serverNow() {
  return Date.now() + (schedule ? schedule.offsetMs : 0);
}

/* Next page reload: every REFRESH_MS, or sooner right after a backend
 * refresh (the refresh normally finishes within a few seconds). */
function scheduleNextLoad() {
  clearTimeout(loadTimer);
  let delay = REFRESH_MS;
  if (schedule) {
    for (const job of Object.values(schedule.jobs)) {
      if (!job || !job.next_run_utc) continue;
      const until = Date.parse(job.next_run_utc) - serverNow() + RELOAD_AFTER_REFRESH_MS;
      if (until > 0 && until < delay) delay = until;
    }
  }
  nextLoadAt = Date.now() + delay;
  loadTimer = setTimeout(() => {
    onReload();
  }, delay);
}

/* The three countdown values, once a second. */
function tick() {
  if (!valueEls) return;
  for (const job of ["radar", "models"]) {
    const el = valueEls[job];
    const def = schedule && schedule.jobs ? schedule.jobs[job] : null;
    if (!el) continue;
    if (!def || !def.next_run_utc) {
      el.textContent = DASH;
      continue;
    }
    el.textContent = fmtCountdown(Date.parse(def.next_run_utc) - serverNow());
  }
  const page = valueEls.page;
  if (page) page.textContent = fmtCountdown(nextLoadAt - Date.now());
}

/* ---- wiring (called once from app.js) ---- */

export function initDetails(l, loc, opts) {
  lang = l || "en";
  locale = loc || "en-US";
  onReload = (opts && opts.onReload) || (() => {});
  els.title.textContent = t(lang, "details.title");
  setInterval(tick, 1000);
}

/* The body, rebuilt on every refresh. */
export function renderDetails(data) {
  const rain = data && data.rain;
  const sources = data && data.sources;
  const accuracy = data && data.accuracy;

  els.body.textContent = "";
  els.body.appendChild(signalsSection(rain));
  const refresh = refreshSection();
  valueEls = refresh.values;
  els.body.appendChild(refresh.wrap);
  els.body.appendChild(sourcesSection(sources));
  els.body.appendChild(accuracySection(accuracy));

  applySchedule(data && data.schedule);
  scheduleNextLoad();
  tick();
}

/* ---- small builders ---- */

function section(title) {
  const div = document.createElement("div");
  div.className = "details-section";
  const h = document.createElement("h3");
  h.textContent = title;
  div.appendChild(h);
  return div;
}

function line(hook) {
  const p = document.createElement("p");
  p.className = "detail-line";
  p.setAttribute("data-test", hook);
  return p;
}

/* One line of "part · part · part". */
function fillLine(p, parts) {
  for (let i = 0; i < parts.length; i++) {
    if (i) {
      const sep = document.createElement("span");
      sep.className = "sep";
      sep.textContent = "·";
      p.appendChild(sep);
    }
    p.appendChild(document.createTextNode(parts[i]));
  }
}

/* Signals and weights: the weights in use (a dash without data) and the
 * current signals — radar raining or not, how many models see rain, the
 * ensemble's own probability. */
function signalsSection(rain) {
  const sec = section(t(lang, "details.signals-weights"));
  const weightsLine = line("details-weights");
  const signalsLine = line("details-signals");
  const weights = rain && rain.weights_used;
  const hasData = !!(weights && Object.keys(weights).length > 0);
  if (!hasData) {
    weightsLine.textContent = DASH;
    signalsLine.textContent = DASH;
  } else {
    fillLine(weightsLine, [
      `${t(lang, "weight.radar")} ${fmtPercent(weights.radar * 100, locale)}`,
      `${t(lang, "weight.models")} ${fmtPercent(weights.models * 100, locale)}`,
      `${t(lang, "weight.ensemble")} ${fmtPercent(weights.ensemble * 100, locale)}`,
    ]);
    const radar = rain.radar_raining == null
      ? DASH
      : rain.radar_raining ? t(lang, "signals.radar-yes") : t(lang, "signals.radar-no");
    fillLine(signalsLine, [
      radar,
      `${t(lang, "weight.models")}: ${t(lang, "signals.models", { n: rain.models_rain_count, total: rain.models_total })}`,
      `${t(lang, "weight.ensemble")}: ${fmtPercent(rain.ensemble_pct, locale)}`,
    ]);
  }
  sec.append(weightsLine, signalsLine);
  return sec;
}

/* The three countdown tiles (radar, models, page reload); the values are
 * updated by tick(), the reload itself by scheduleNextLoad(). */
function refreshSection() {
  const sec = section(t(lang, "details.refresh"));
  const grid = document.createElement("div");
  grid.className = "refresh-grid";
  const values = {};
  for (const [job, label] of [
    ["radar", t(lang, "weight.radar")],
    ["models", t(lang, "weight.models")],
    ["page", t(lang, "countdown.page")],
  ]) {
    const tile = document.createElement("div");
    tile.className = "refresh-tile";
    const value = document.createElement("span");
    value.className = "refresh-value";
    value.setAttribute("data-test", `countdown-${job}`);
    value.textContent = DASH;
    const lab = document.createElement("span");
    lab.className = "refresh-label";
    lab.textContent = label;
    tile.append(value, lab);
    grid.appendChild(tile);
    values[job] = value;
  }
  sec.appendChild(grid);
  return { wrap: sec, values };
}

/* Which page part a source feeds: two rows share an upstream, so each
 * row also names the feed (Radar, Now, Models, Ensemble). */
const FEED_KEYS = {
  radar: "weight.radar",
  current: "now.title",
  forecast: "weight.models",
  ensemble: "weight.ensemble",
};

/* The four sources in API order: the feed it drives, the upstream's name
 * muted next to it, the age (and the "stale" marker), the last error
 * under the row when it is set. */
function sourcesSection(sources) {
  const sec = section(t(lang, "details.sources"));
  const list = document.createElement("div");
  list.className = "source-list";
  for (const key of SOURCE_ORDER) {
    const s = (sources && sources[key]) || null;
    const row = document.createElement("div");
    row.className = "source-row";
    row.setAttribute("data-test", "source-row");
    row.setAttribute("data-source", key);
    const what = document.createElement("span");
    what.className = "source-what";
    const name = document.createElement("span");
    name.className = "source-name";
    name.textContent = t(lang, FEED_KEYS[key]);
    const upstream = document.createElement("span");
    upstream.className = "source-upstream";
    upstream.textContent = (s && s.upstream) || key;
    what.append(name, " ", upstream);
    const age = document.createElement("span");
    age.className = "source-age";
    const parts = [];
    if (s) {
      parts.push(fmtAge(s.age_seconds, lang));
      if (s.stale) parts.push(t(lang, "sources.stale"));
    } else {
      parts.push(t(lang, "age.na"));
    }
    age.textContent = parts.join(" · ");
    row.append(what, age);
    if (s && s.last_error) {
      const err = document.createElement("p");
      err.className = "source-error";
      err.setAttribute("data-test", "source-error");
      err.textContent = s.last_error;
      row.appendChild(err);
    }
    list.appendChild(row);
  }
  sec.appendChild(list);
  return sec;
}

/* The accuracy: without any compared model the status line; otherwise
 * the table (the no-rain note above it when no rain has been measured
 * yet) and the note that explains the columns. */
function accuracySection(accuracy) {
  const sec = section(t(lang, "details.accuracy"));
  const models = accuracy && accuracy.models && typeof accuracy.models === "object"
    ? accuracy.models
    : {};
  if (Object.keys(models).length === 0) {
    const status = document.createElement("p");
    status.className = "accuracy-status";
    status.setAttribute("data-test", "accuracy-status");
    status.textContent = t(lang, "accuracy.none");
    sec.appendChild(status);
    return sec;
  }
  if (!rainObserved(models)) {
    const noRain = document.createElement("p");
    noRain.className = "accuracy-no-rain";
    noRain.setAttribute("data-test", "accuracy-no-rain");
    noRain.textContent = t(lang, "accuracy.no-rain");
    sec.appendChild(noRain);
  }
  sec.appendChild(buildTable(models));
  const note = document.createElement("p");
  note.className = "accuracy-note";
  note.setAttribute("data-test", "accuracy-note");
  note.textContent = t(lang, "accuracy.note");
  sec.appendChild(note);
  return sec;
}

/* The table in a scrollable container (a phone must not widen): header
 * row with the plain column names, one row per model, the rows without
 * enough data last and greyed (but still readable). */
function buildTable(models) {
  const scroll = document.createElement("div");
  scroll.className = "table-scroll";
  const table = document.createElement("table");
  table.className = "accuracy-table";
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  headRow.setAttribute("data-test", "accuracy-head");
  for (const key of ["model", "hours", "hits", "misses", "false-alarms", "hit-rate", "mae"]) {
    const th = document.createElement("th");
    th.textContent = t(lang, `accuracy.head.${key}`);
    headRow.appendChild(th);
  }
  head.appendChild(headRow);
  table.appendChild(head);
  const body = document.createElement("tbody");
  for (const name of sortAccuracy(models)) {
    const m = models[name];
    const row = document.createElement("tr");
    row.setAttribute("data-test", "accuracy-row");
    row.setAttribute("data-model", name);
    if (!m.enough_data) row.className = "low";
    const cells = [
      modelLabel(name),
      m.n_samples,
      m.hits,
      m.misses,
      m.false_alarms,
      fmtPercent(typeof m.event_accuracy === "number" ? m.event_accuracy * 100 : null, locale),
      fmtMm(m.mae_mm, locale, 2),
    ];
    for (const c of cells) {
      const td = document.createElement("td");
      td.textContent = c == null ? DASH : String(c);
      row.appendChild(td);
    }
    body.appendChild(row);
  }
  table.appendChild(body);
  scroll.appendChild(table);
  return scroll;
}
