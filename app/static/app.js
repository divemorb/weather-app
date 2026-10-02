/* app.js — the page's entry module (step W2, the Details card in W7).
 *
 * Sets the language (<html lang>, the aria-labels, the footer) and the
 * theme, then reads /api/config: unconfigured -> the wizard in "first"
 * mode; configured -> the glance, the Now section, the chart and the
 * details. A failed fetch keeps the old content and logs with
 * console.warn (failures are not page errors). The page reload is
 * scheduled by details.js (10 s after a backend refresh, at the latest
 * every 60 s) via the onReload callback.
 */
import { pickLang, t } from "./i18n.js";
import { getJSON } from "./api.js";
import { locationText, locationDetail } from "./format.js";
import { renderGlance } from "./glance.js";
import { initNow, renderNow } from "./now.js";
import { renderChart } from "./chart.js";
import { initDetails, renderDetails } from "./details.js";
import { initSetup, openSetup } from "./setup.js";

const lang = pickLang(navigator.languages);
const locale = navigator.language;
document.documentElement.lang = lang;

const $ = (id) => document.getElementById(id);

/* Fixed texts the user reads: aria-labels, the loading answer and the
 * footer (W9 moves the remaining fixed texts out of index.html). */
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

/* Kiosk view (?kiosk): the wall tablet gets one screen of big type. */
if (new URLSearchParams(location.search).has("kiosk")) {
  document.body.classList.add("kiosk");
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

const chartEls = {
  body: $("chart-body"),
  legend: $("chart-legend"),
  unavailable: $("chart-unavailable"),
  dry: $("chart-dry"),
  unit: $("chart-unit"),
};

/* One refresh: the glance, the Now section, the chart and the details.
 * Each endpoint fails on its own (a failing source never breaks the
 * other parts), so a null reaches the renderer, which shows its
 * "unavailable" state. */
async function loadGlance() {
  const fetchOrNull = (path) =>
    getJSON(path).catch((e) => {
      console.warn(e); // keep the old content; a failure is not a page error
      return null;
    });
  const [rain, radar, now, models, sources, schedule, accuracy] = await Promise.all([
    fetchOrNull("/api/rain-probability"),
    fetchOrNull("/api/radar/next-hour"),
    fetchOrNull("/api/now"),
    fetchOrNull("/api/models/24h"),
    fetchOrNull("/api/sources"),
    fetchOrNull("/api/schedule"),
    fetchOrNull("/api/model-accuracy"),
  ]);
  /* The radius comes from the config loaded once at startup, not from a
   * fetch per refresh (the caption under the radar strip). */
  renderGlance(rain, radar, lang, locale, tz, cfg && cfg.radar_radius_km);
  renderNow(now, lang, locale, tz);
  renderChart(chartEls, models, lang, locale, tz);
  renderDetails({ rain, sources, schedule, accuracy });
}

(async function start() {
  $("location").textContent = t(lang, "location.loading");
  try {
    cfg = await getJSON("/api/config");
  } catch (e) {
    console.warn(e);
    setPlace(null);
    return;
  }
  if (cfg.location) tz = cfg.location.timezone || "UTC";
  setPlace(cfg.location);
  if (cfg.configured === false || !cfg.location) {
    openSetup("first"); // ask for the location; the reload starts after a save
    return;
  }
  await loadGlance(); // the page reload is scheduled inside (details.js)
})();

/* The Details card: the schedule, the countdowns and the page reload
 * live there; onReload runs one refresh, which reschedules the next. */
initDetails(lang, locale, {
  onReload: () => {
    loadGlance();
  },
});

initSetup({
  lang,
  isConfigured: () => !!(cfg && cfg.configured !== false && cfg.location),
  onSaved: async () => {
    try {
      cfg = await getJSON("/api/config");
      if (cfg.location) tz = cfg.location.timezone || "UTC";
      setPlace(cfg.location);
      await loadGlance(); // the reload is scheduled inside (details.js)
    } catch (e) {
      console.warn(e);
    }
  },
});
