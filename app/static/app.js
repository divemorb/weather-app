/* app.js — the page's entry module.
 *
 * Sets the language (<html lang>, the aria-labels, the footer) and the
 * theme, then reads /api/config: unconfigured -> the wizard in "first"
 * mode; configured -> the glance, the Now section, the chart and the
 * details. A failed /api/config at startup is retried every 10 s (the
 * place line says the app can't be reached meanwhile). A refresh
 * re-fetches all the data endpoints; each endpoint fails on its own and
 * each page part renders on its own (an exception is caught and logged
 * with console.warn, the part keeps its old content or its unavailable
 * state), and the next page reload is scheduled whatever failed
 * (details.js: 10 s after a backend refresh, at the latest every 60 s,
 * via the onReload callback). Nothing throws uncaught.
 */
import { pickLang, t } from "./i18n.js";
import { getJSON } from "./api.js";
import { CONFIG_RETRY_MS, locationText, locationDetail, scene } from "./format.js";
import { renderGlance, renderSkyReason } from "./glance.js";
import { initSky } from "./sky.js";
import { initNow, renderNow } from "./now.js";
import { renderChart } from "./chart.js";
import { initDetails, renderDetails, scheduleFrom } from "./details.js";
import { initSetup, openSetup } from "./setup.js";

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
$("glance-prob-label").textContent = t(lang, "glance.prob-label");
$("rain-answer").textContent = t(lang, "answer.loading");
$("chart-title").textContent = t(lang, "chart.title");
initNow(lang);
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

function applyTheme() {
  document.documentElement.dataset.theme = stored || (mq.matches ? "dark" : "light");
}
applyTheme();
mq.addEventListener("change", applyTheme);

/* ---- the sky: one fixed layer behind the tiles. The scene name goes on
 * <html data-scene>; scene() (format.js) maps the Now observation and the
 * radar's first step to it. It starts "none" (plain background) and follows
 * every refresh; the particles are built once by initSky(). ---- */
initSky();
let skyNow = null;
let skyRadar = null;
function setSkyScene() {
  document.documentElement.dataset.scene = scene(skyNow, skyRadar);
}
setSkyScene();

/* Kiosk view (?kiosk): the wall tablet gets one screen of big type; the
 * class goes on <html>, where kiosk.css and chart.js look for it. */
if (new URLSearchParams(location.search).has("kiosk")) {
  document.documentElement.classList.add("kiosk");
}
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

/* The header's place line and the muted detail under it (the time zone,
 * plus the coordinates when the place shows a label); set everywhere a
 * location is known — startup, after a save, and the error path. */
function setPlace(location) {
  $("location").textContent = locationText(location) || t(lang, "location.unset");
  $("location-detail").textContent = locationDetail(location);
}

/* The place line while /api/config does not answer: the location is set,
 * the app just didn't answer; the page keeps trying (10 s). */
function setUnreachable() {
  $("location").textContent = t(lang, "location.unreachable");
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

/* One refresh: the glance, the Now section, the chart and the details.
 * Each endpoint fails on its own (a failing source never breaks the
 * other parts), so a null reaches the renderer, which shows its
 * "unavailable" state; each part renders on its own; and the next page
 * reload is scheduled whatever failed (details.js). */
async function refresh() {
  const fetchOrNull = (path) =>
    getJSON(path).catch((e) => {
      console.warn(e); // keep the old content; a failure is not a page error
      return null;
    });
  const data = { rain: null, radar: null, now: null, models: null, sources: null, schedule: null, accuracy: null };
  try {
    /* The radius comes from the config loaded once at startup, not from a
     * fetch per refresh (the caption under the radar strip). */
    [data.rain, data.radar, data.now, data.models, data.sources, data.schedule, data.accuracy] = await Promise.all([
      fetchOrNull("/api/rain-probability"),
      fetchOrNull("/api/radar/next-hour"),
      fetchOrNull("/api/now"),
      fetchOrNull("/api/models/24h"),
      fetchOrNull("/api/sources"),
      fetchOrNull("/api/schedule"),
      fetchOrNull("/api/model-accuracy"),
    ]);
  } catch (e) {
    console.warn(e);
  }
  if (data.now != null) skyNow = data.now;
  if (data.radar != null) skyRadar = data.radar;
  renderPart("sky", setSkyScene); // its own part: a bad answer must not stop the others
  renderPart("glance", () => renderGlance(data.rain, data.radar, lang, locale, tz, cfg && cfg.radar_radius_km));
  /* The sky's "why" line: the same part as the glance, so one failed
   * endpoint (now or radar) never stops the other. */
  renderPart("sky-reason", () => renderSkyReason(data.now, data.radar, lang, locale));
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
    }
    await refresh(); // the reload is scheduled inside (details.js)
  },
});
