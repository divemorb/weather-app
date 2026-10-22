/* app.js — the page's entry module.
 *
 * Sets the language and the theme, then reads /api/config: unconfigured
 * -> the wizard in "first" mode, configured -> the glance, Now, the
 * chart and the details. A failed /api/config is retried every 10 s.
 * A refresh re-fetches all the data endpoints; each endpoint and page
 * part fails and renders on its own; a failed fetch keeps the part's
 * last good data, noted as outdated; the next reload is scheduled
 * whatever failed. Nothing throws uncaught.
 */

// the view (big/detailed) and the <html> classes, before anything reads them
import "./view.js";
import { pickLang, t } from "./i18n.js";
import { getJSON } from "./api.js";
import { CONFIG_RETRY_MS, fmtTime, locationText, locationDetail, scene } from "./format.js";
import { renderGlance, renderSkyReason } from "./glance.js";
import { initSky } from "./sky.js";
import { initNow, renderNow } from "./now.js";
import { renderChart } from "./chart.js";
import { initDetails, renderDetails, scheduleFrom } from "./details.js";
import { initSetup, openSetup } from "./setup.js";
import { initReport, reportScene, reportCurrent, setReportEnv, reportSky } from "./report.js";

const lang = pickLang(navigator.languages);
const locale = navigator.language;
document.documentElement.lang = lang;

const $ = (id) => document.getElementById(id);

/* Fixed texts the user reads: aria-labels, the loading answer, the
 * probability label, the chart title and the footer. Every page text
 * lives in i18n.js and the modules fill the (empty) elements, so
 * index.html stays language-neutral. */
$("location-btn").setAttribute("aria-label", t(lang, "location.aria"));
$("theme-toggle").setAttribute("aria-label", t(lang, "theme.aria"));
$("glance-title").textContent = t(lang, "glance.title");
$("glance-prob-label").textContent = t(lang, "glance.prob-label");
$("rain-answer").textContent = t(lang, "answer.loading");
$("chart-title").textContent = t(lang, "chart.title");
initNow(lang);
initReport(lang);
$("attribution").innerHTML = t(lang, "attribution", {
  dwd: '<a href="https://www.dwd.de" target="_blank" rel="noopener">DWD</a>',
  brightsky: '<a href="https://brightsky.dev" target="_blank" rel="noopener">Bright Sky</a>',
  openmeteo: '<a href="https://open-meteo.com" target="_blank" rel="noopener">Open-Meteo</a>',
  osm: '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
});

/* ---- theme: the stored choice (localStorage "theme", wrapped in try)
 * wins, else the system preference; it follows the system live unless
 * stored; the toggle stores the opposite of the current theme ---- */
const mq = window.matchMedia("(prefers-color-scheme: dark)");
let stored = null;
try {
  const value = localStorage.getItem("theme");
  stored = value === "light" || value === "dark" ? value : null;
} catch { /* storage can be blocked */ }

// the theme: the stored choice wins, else the system preference
function applyTheme() {
  document.documentElement.dataset.theme = stored || (mq.matches ? "dark" : "light");
}
applyTheme();
mq.addEventListener("change", applyTheme);

/* ---- the sky: one fixed layer behind the tiles. The scene name goes on
 * <html data-scene>. A fresh user report decides it (reportSky);
 * without one, scene() (format.js) maps the Now observation and the
 * radar's first step. It starts "none" (plain background) and follows
 * every refresh; the particles are built once by initSky(). ---- */
initSky();
let skyNow = null;
let skyRadar = null;
// the scene on <html data-scene>: a fresh report, else scene()
function setSkyScene() {
  const rep = reportSky(); // a fresh report decides the sky
  document.documentElement.dataset.scene = rep ? rep.scene : scene(skyNow, skyRadar);
}
setSkyScene();
/* A save or an undo (report.js dispatches "report-changed") turns the
 * sky and the "why" line to the fresh report at once, no reload. */
document.addEventListener("report-changed", () => {
  renderPart("sky", setSkyScene);
  renderPart("report", reportScene);
  const rep = reportSky();
  renderPart("sky-reason", () => renderSkyReason(skyNow, skyRadar, lang, locale, rep ? rep.text : null));
});

/* (The kiosk class on <html> comes from view.js: it is set for the big
 * view, whatever its source — the query, the stored choice or the default.) */
$("theme-toggle").addEventListener("click", () => {
  stored = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  try {
    localStorage.setItem("theme", stored);
  } catch { /* ignore */ }
  applyTheme();
});

/* ---- state and loading ---- */
let cfg = null;
let tz = "UTC";
/* The last good answer per data endpoint, with the Date.now() ms it
 * arrived (a failed refresh re-shows it, the note names the time). */
let lastGood = {};
/* The header's place (the city) and the details page's Place section
 * (the full label, the coordinates and the time zone); set everywhere a
 * location is known — startup, after a save, and the error path. */
function setPlace(location) {
  $("location").textContent = locationText(location) || t(lang, "location.unset");
  $("place-label").textContent = (location && location.label) || "";
  $("location-detail").textContent = locationDetail(location);
}

/* The place line while /api/config does not answer: the location is set,
 * the app just didn't answer; the page keeps trying (10 s). */
function setUnreachable() {
  $("location").textContent = t(lang, "location.unreachable");
  $("place-label").textContent = "";
  $("location-detail").textContent = "";
}

const chartEls = {
  body: $("chart-body"),
  legend: $("chart-legend"),
  unavailable: $("chart-unavailable"),
  dry: $("chart-dry"),
  unit: $("chart-unit"),
};

/* One page part, rendered on its own: an exception (bad data from one
 * endpoint) is caught and logged, the part keeps its old content or its
 * unavailable state, and the other parts still render. */
function renderPart(name, render) {
  try {
    render();
  } catch (e) {
    console.warn(`the ${name} part failed to render`, e);
  }
}

// the oldest arrival (Date.now() ms) among the part's failed endpoints, or null
function oldestOf(stale, keys) {
  let at = null;
  for (const key of keys) {
    if (stale[key] != null && (at == null || stale[key] < at)) at = stale[key];
  }
  return at;
}

/* The part's outdated note at the end of its tile (#glance, #now,
 * #chart-card, #details): a small muted line naming the arrival time of
 * the oldest failed endpoint, in the place's time zone. Removed when the
 * part's endpoints all fetch good again (or it never had good data). */
function setOutdated(part, at) {
  const tile = document.getElementById(part === "chart" ? "chart-card" : part);
  if (!tile) return;
  const old = tile.querySelector("[data-test=outdated][data-part=" + part + "]");
  if (at == null || !Number.isFinite(at)) {
    if (old) old.remove();
    return;
  }
  const text = t(lang, "outdated", { time: fmtTime(new Date(at).toISOString(), locale, tz) });
  if (old) {
    old.textContent = text;
    return;
  }
  const p = document.createElement("p");
  p.className = "outdated";
  p.setAttribute("data-test", "outdated");
  p.setAttribute("data-part", part);
  p.textContent = text;
  tile.appendChild(p);
}

/* One refresh: the glance, the Now section, the chart and the details.
 * Each endpoint fails on its own (a failing source never breaks the
 * other parts). A good answer updates that endpoint's last-good copy;
 * a failed fetch falls back to it, and the affected page parts get
 * their small "outdated" note (the oldest arrival time of the failed
 * endpoints). A part without any good answer yet keeps its "not
 * available" state. Each part renders on its own; the next page reload
 * is scheduled whatever failed (details.js). */
async function refresh() {
  const fetchOrNull = (path) =>
    getJSON(path).catch((e) => {
      console.warn(e); // keep the old content; a failure is not a page error
      return null;
    });
  const data = { rain: null, radar: null, now: null, models: null, sources: null, schedule: null, accuracy: null, report: null };
  try {
    /* The radius comes from the config loaded once at startup, not from a
     * fetch per refresh (the caption under the radar strip). A failed
     * report read counts as no report (the line just hides). */
    [data.rain, data.radar, data.now, data.models, data.sources, data.schedule, data.accuracy, data.report] = await Promise.all([
      fetchOrNull("/api/rain-probability"),
      fetchOrNull("/api/radar/next-hour"),
      fetchOrNull("/api/now"),
      fetchOrNull("/api/models/24h"),
      fetchOrNull("/api/sources"),
      fetchOrNull("/api/schedule"),
      fetchOrNull("/api/model-accuracy"),
      fetchOrNull("/api/reports/current"),
    ]);
  } catch (e) {
    console.warn(e);
  }
  /* A good answer (not null) is this endpoint's new last-good copy,
   * with the moment it arrived. A failed fetch falls back to the last
   * good answer; without one, the renderer gets null ("not available").
   * The arrival times of the failed endpoints feed the outdated notes. */
  const stale = {};
  for (const key of ["rain", "radar", "now", "models", "sources", "accuracy"]) {
    if (data[key] != null) {
      lastGood[key] = { answer: data[key], at: Date.now() };
    } else if (lastGood[key]) {
      data[key] = lastGood[key].answer;
      stale[key] = lastGood[key].at;
    }
  }
  /* One outdated note per affected page part; the next good refresh
   * removes it (a part without a last good answer keeps "not available"). */
  setOutdated("glance", oldestOf(stale, ["rain", "radar"]));
  setOutdated("now", oldestOf(stale, ["now"]));
  setOutdated("chart", oldestOf(stale, ["models"]));
  setOutdated("details", oldestOf(stale, ["rain", "sources", "accuracy"]));
  if (data.now != null) skyNow = data.now;
  if (data.radar != null) skyRadar = data.radar;
  /* The current report first: the sky and the "why" line follow it.
   * reportCurrent is synchronous without a refetch, so the sky below sees it. */
  renderPart("report-current", () => reportCurrent(data.report && data.report.report));
  renderPart("sky", setSkyScene); // its own part: a bad answer must not stop the others
  renderPart("report", reportScene); // the open back names the scene the page shows
  renderPart("glance", () => renderGlance(data.rain, data.radar, lang, locale, tz, cfg && cfg.radar_radius_km));
  /* The sky's "why" line: the report's text when fresh, else the same
   * part as the glance, so one failed endpoint never stops the other. */
  const repSky = reportSky();
  renderPart("sky-reason", () => renderSkyReason(data.now, data.radar, lang, locale, repSky ? repSky.text : null));
  renderPart("now", () => renderNow(data.now, lang, locale, tz));
  renderPart("chart", () => renderChart(chartEls, data.models, lang, locale, tz));
  /* The stations section (details.js) needs the Now's station and the
   * location's coordinates, the radar radius comes from the config. */
  renderPart("details", () => renderDetails({
    rain: data.rain,
    sources: data.sources,
    accuracy: data.accuracy,
    now: data.now,
    location: cfg && cfg.location,
    radiusKm: cfg && cfg.radar_radius_km,
  }));
  /* The reload can't be skipped: it is scheduled after the renderers,
   * whatever failed in them. */
  scheduleFrom(data.schedule);
}

/* Startup: /api/config is retried until it works (10 s between attempts,
 * the place line says the app can't be reached meanwhile), then the page
 * starts as usual: the wizard when unconfigured, else the data. */
async function start() {
  $("location").textContent = t(lang, "location.loading");
  while (true) {
    let c = null;
    try {
      c = await getJSON("/api/config");
    } catch (e) {
      console.warn(e);
    }
    if (c && typeof c === "object") {
      cfg = c;
      break;
    }
    if (c != null) console.warn("bad /api/config response", c);
    setUnreachable();
    await new Promise((resolve) => setTimeout(resolve, CONFIG_RETRY_MS));
  }
  if (cfg.location) tz = cfg.location.timezone || "UTC";
  setPlace(cfg.location);
  setReportEnv(locale, tz, cfg.location); // the report line's zone and day/night
  if (cfg.configured === false || !cfg.location) {
    openSetup("first"); // ask for the location; the reload starts after a save
    return;
  }
  await refresh(); // the page reload is scheduled inside (details.js)
}
start().catch((e) => console.warn("start failed", e));

/* The Details card: the schedule, the countdowns and the page reload
 * live there; onReload runs one refresh, which reschedules the next. */
initDetails(lang, locale, {
  onReload: () => {
    refresh().catch((e) => console.warn("the refresh failed", e));
  },
});

initSetup({
  lang,
  isConfigured: () => !!(cfg && cfg.configured !== false && cfg.location),
  onSaved: async () => {
    let newCfg = null;
    try {
      newCfg = await getJSON("/api/config");
    } catch (e) {
      console.warn(e);
    }
    if (newCfg) {
      cfg = newCfg;
      if (newCfg.location) tz = newCfg.location.timezone || "UTC";
      setPlace(newCfg.location);
      setReportEnv(locale, tz, newCfg.location);
    }
    await refresh(); // the reload is scheduled inside (details.js)
  },
});
