/* details.js — the Details card (step W7), the page reload (step W9b).
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
 * Each section renders on its own: one bad endpoint never clears the
 * card or stops the other sections (the new body is only swapped in once
 * it has been built). The page reload lives here too, but not inside the
 * body: app.js calls scheduleFrom() after every refresh, after all the
 * renderers, so the next reload (10 s after the next scheduled backend
 * refresh, at the latest every 60 s) is scheduled whatever failed. The
 * onReload callback (one refresh) is set by app.js.
 */
import {
  DASH, PAGE_RELOAD_AFTER_REFRESH_MS, PAGE_REFRESH_MS, fmtAge, fmtCountdown, fmtMm,
  fmtPercent, modelLabel, nextLoadDelay, rainObserved, sortAccuracy,
} from "./format.js";
import { t } from "./i18n.js";
import { stationsSection } from "./stationmap.js";

const $ = (id) => document.getElementById(id);

const els = {
  title: $("details-title"),
  body: $("details-body"),
};

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
  if (!s || typeof s !== "object" || !s.jobs || typeof s.jobs !== "object") {
    schedule = null;
    return;
  }
  // server clock minus browser clock, so the countdown matches the server
  const offsetMs = Date.parse(s.server_time_utc) - Date.now();
  schedule = { offsetMs: isNaN(offsetMs) ? 0 : offsetMs, jobs: s.jobs };
}

function serverNow() {
  return Date.now() + (schedule && Number.isFinite(schedule.offsetMs) ? schedule.offsetMs : 0);
}

/* Next page reload: every PAGE_REFRESH_MS, or sooner right after a
 * backend refresh (the refresh normally finishes within a few seconds).
 * The delay is the pure nextLoadDelay() (format.js); this only sets the
 * timer, and it always sets it — even on bad data, the page reloads. */
function scheduleNextLoad() {
  let delay;
  try {
    delay = nextLoadDelay(schedule && schedule.jobs, serverNow(), PAGE_REFRESH_MS, PAGE_RELOAD_AFTER_REFRESH_MS);
  } catch (e) {
    console.warn("computing the reload delay failed", e);
    delay = PAGE_REFRESH_MS;
  }
  if (typeof delay !== "number" || !Number.isFinite(delay) || delay <= 0) delay = PAGE_REFRESH_MS;
  clearTimeout(loadTimer);
  nextLoadAt = Date.now() + delay;
  loadTimer = setTimeout(() => {
    onReload();
  }, delay);
}

/* Apply the /api/schedule data and schedule the next page reload.
 * app.js calls this after every refresh, after the renderers, so the
 * reload happens whatever failed in them. It never throws. */
export function scheduleFrom(scheduleData) {
  try {
    applySchedule(scheduleData);
    scheduleNextLoad();
    tick();
  } catch (e) {
    console.warn("scheduling the next reload failed", e);
  }
}

/* The three countdown values, once a second; bad data shows a dash, it
 * never throws (the interval would turn it into an uncaught error). */
function tick() {
  try {
    if (!valueEls) return;
    for (const job of ["radar", "models"]) {
      const el = valueEls[job];
      if (!el || typeof el !== "object") continue;
      const def = schedule && schedule.jobs && typeof schedule.jobs === "object"
        ? schedule.jobs[job]
        : null;
      if (!def || typeof def !== "object" || !def.next_run_utc || isNaN(Date.parse(def.next_run_utc))) {
        el.textContent = DASH;
        continue;
      }
      el.textContent = fmtCountdown(Date.parse(def.next_run_utc) - serverNow());
    }
    const page = valueEls.page;
    if (page && typeof page === "object") page.textContent = fmtCountdown(nextLoadAt - Date.now());
  } catch (e) {
    console.warn("the countdown tick failed", e);
  }
}

/* ---- wiring (called once from app.js) ---- */

export function initDetails(l, loc, opts) {
  lang = l || "en";
  locale = loc || "en-US";
  onReload = (opts && opts.onReload) || (() => {});
  els.title.textContent = t(lang, "details.title");
  setInterval(tick, 1000);
}

/* The body, rebuilt on every refresh. Each section renders on its own
 * (one bad endpoint keeps the card, never the empty half of it): the new
 * body is built in a detached fragment and only swapped in at the end.
 * Scheduling the next reload is not part of the body — app.js calls
 * scheduleFrom() afterwards, so it happens whatever failed here. */
export function renderDetails(data) {
  const rain = data && data.rain;
  const sources = data && data.sources;
  const accuracy = data && data.accuracy;
  const now = data && data.now;
  const location = data && data.location;
  const radiusKm = data && data.radiusKm;

  const frag = document.createDocumentFragment();
  const add = (builder) => {
    try {
      frag.appendChild(builder());
    } catch (e) {
      console.warn("a details section failed to render", e);
    }
  };
  add(() => signalsSection(rain));
  let refresh = null;
  try {
    refresh = refreshSection();
  } catch (e) {
    console.warn("the details refresh section failed to render", e);
    valueEls = null; // the old spans are detached; tick() must not touch them
  }
  if (refresh) {
    valueEls = refresh.values;
    add(() => refresh.wrap);
  }
  add(() => sourcesSection(sources));
  add(() => accuracySection(accuracy));
  const stations = stationsSection({ now, accuracy, location, radiusKm, lang, locale, section });
  if (stations) add(() => stations);

  /* Nothing rendered? Keep the old card instead of an empty one. */
  if (frag.childElementCount > 0) {
    els.body.textContent = "";
    els.body.appendChild(frag);
  }
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
