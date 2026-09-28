/* Weather app frontend (step 5).
 *
 * Reads the REST API (all timestamps UTC) and renders:
 *   - headline rain probability for the next 60 min
 *   - "Now" current-conditions tile
 *   - 60-minute radar nowcast bar (12 x 5-min)
 *   - 24 h multi-model precipitation chart (inline SVG)
 *   - model accuracy card (accuracy.js, step 6f)
 *   - per-source age / staleness
 *
 * No build step, no external CDN: plain JS + inline SVG so it works on a
 * home network with no outbound calls beyond the API itself.
 */
"use strict";

const REFRESH_MS = 60_000;
const RADAR_MAX_MM = 1.0; // bar full-height reference (5-min step)

/* ------------------------------------------------------------------ *
 * Element handles
 * ------------------------------------------------------------------ */
const $ = (id) => document.getElementById(id);
const els = {
  subtitle: $("subtitle"),
  themeToggle: $("theme-toggle"),
  refreshBadge: $("refresh-badge"),
  heroCard: $("hero-card"),
  heroValue: $("hero-value"),
  heroExplain: $("hero-explain"),
  heroChips: $("hero-chips"),
  nowBadge: $("now-badge"),
  nowGrid: $("now-grid"),
  radarBadge: $("radar-badge"),
  radarBar: $("radar-bar"),
  radarNote: $("radar-note"),
  radarScale: $("radar-scale"),
  radarScaleMin: $("radar-scale-min"),
  radarScaleMax: $("radar-scale-max"),
  chart: $("chart"),
  chartBadge: $("chart-badge"),
  legend: $("legend"),
  accuracyBadge: $("accuracy-badge"),
  accuracyStatus: $("accuracy-status"),
  accuracyTable: $("accuracy-table"),
  sources: $("sources"),
};

let cfg = null;
let tz = "UTC";

/* ------------------------------------------------------------------ *
 * Fetching
 * ------------------------------------------------------------------ */
async function getJSON(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

/* ------------------------------------------------------------------ *
 * Formatting helpers (UTC -> display timezone)
 * ------------------------------------------------------------------ */
function fmtClock(utcStr) {
  if (!utcStr) return "—";
  const d = new Date(utcStr);
  if (isNaN(d)) return "—";
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", timeZone: tz }).format(d);
}

function fmtHour(utcStr) {
  if (!utcStr) return "";
  const d = new Date(utcStr);
  if (isNaN(d)) return "";
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", timeZone: tz }).format(d);
}

function fmtAge(seconds) {
  if (seconds == null) return "n/a";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m}m`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

function fmtNum(v, digits = 1) {
  if (v == null || isNaN(v)) return "—";
  return Number(v).toFixed(digits);
}

function windDir(deg) {
  if (deg == null || isNaN(deg)) return "";
  const pts = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  return pts[Math.round(((deg % 360) / 45)) % 8];
}

/* ------------------------------------------------------------------ *
 * Theme (dark by default; respect system preference on first load)
 * ------------------------------------------------------------------ */
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  els.themeToggle.textContent = theme === "dark" ? "🌙" : "☀️";
  try { localStorage.setItem("theme", theme); } catch (_) { /* ignore */ }
}

function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("theme"); } catch (_) { /* ignore */ }
  const prefersLight = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
  applyTheme(saved || (prefersLight ? "light" : "dark"));
}

/* ------------------------------------------------------------------ *
 * Rendering: headline rain probability
 * ------------------------------------------------------------------ */
function renderHero(data) {
  const pct = data.probability_pct;
  const hasSignal = data.weights_used && Object.keys(data.weights_used).length > 0;

  els.heroValue.textContent = hasSignal ? Math.round(pct) : "—";
  els.heroCard.classList.remove("low", "mid", "high");
  if (hasSignal) {
    els.heroCard.classList.add(pct < 34 ? "low" : pct < 67 ? "mid" : "high");
  }

  els.heroExplain.textContent = hasSignal
    ? data.explanation
    : "Waiting for the first cached forecast (radar + models).";
  els.heroExplain.classList.toggle("muted", !hasSignal);

  // Breakdown chips.
  const chips = [];
  const w = data.weights_used || {};
  if (data.radar_available) {
    chips.push({
      text: `Radar: ${data.radar_raining ? "yes" : "no"}`,
      on: !!data.radar_raining,
      age: data.radar_age_seconds,
    });
  }
  if (data.models_total > 0) {
    chips.push({ text: `Models: ${data.models_rain_count} of ${data.models_total}`, on: data.models_rain_count > 0, age: data.models_age_seconds });
  }
  if (data.ensemble_pct != null) {
    chips.push({ text: `Ensemble: ${Math.round(data.ensemble_pct)} %`, on: data.ensemble_pct > 0 });
  }
  if (w.radar != null) chips.push({ text: `weights ${w.radar}/${w.models}/${w.ensemble}` });

  els.heroChips.innerHTML = "";
  for (const c of chips) {
    const el = document.createElement("span");
    el.className = "chip" + (c.on ? " on" : "");
    el.innerHTML = c.text;
    if (c.age != null) {
      const t = document.createElement("span");
      t.className = "muted";
      t.textContent = ` · ${fmtAge(c.age)}`;
      el.appendChild(t);
    }
    els.heroChips.appendChild(el);
  }
}

/* ------------------------------------------------------------------ *
 * Rendering: Now tile
 * ------------------------------------------------------------------ */
function renderNow(data) {
  setBadge(els.nowBadge, data);
  if (!data.available || !data.conditions) {
    els.nowGrid.innerHTML = '<span class="muted">No observation cached yet.</span>';
    return;
  }
  const c = data.conditions;
  const stats = [
    ["Feels like", `${fmtNum(c.feels_like_c)}°`],
    ["Wind", c.wind_speed_ms != null ? `${fmtNum(c.wind_speed_ms, 0)} m/s ${windDir(c.wind_direction_deg)}` : "—"],
    ["Gust", c.wind_gust_ms != null ? `${fmtNum(c.wind_gust_ms, 0)} m/s` : "—"],
    ["Cloud cover", c.cloud_cover_pct != null ? `${fmtNum(c.cloud_cover_pct, 0)} %` : "—"],
    ["Humidity", c.humidity_pct != null ? `${fmtNum(c.humidity_pct, 0)} %` : "—"],
    ["Pressure", c.pressure_hpa != null ? `${fmtNum(c.pressure_hpa, 0)} hPa` : "—"],
    ["Dew point", `${fmtNum(c.dew_point_c)}°`],
    ["Rain 10 min", `${fmtNum(c.precipitation_10mm)} mm`],
    ["Rain 60 min", `${fmtNum(c.precipitation_60mm)} mm`],
  ];
  els.nowGrid.innerHTML = "";
  const main = document.createElement("div");
  main.className = "now-main";
  main.innerHTML = `<span class="now-temp">${fmtNum(c.temperature_c, 0)}°</span>` +
    `<span class="now-cond">${c.condition || "—"} · ${fmtClock(c.timestamp_utc)} local</span>`;
  els.nowGrid.appendChild(main);

  const grid = document.createElement("div");
  grid.className = "now-stats";
  for (const [label, value] of stats) {
    const item = document.createElement("div");
    item.className = "now-item";
    item.innerHTML = `<span class="now-label">${label}</span><span class="now-val">${value}</span>`;
    grid.appendChild(item);
  }
  els.nowGrid.appendChild(grid);
}

/* ------------------------------------------------------------------ *
 * Rendering: radar nowcast bar
 * ------------------------------------------------------------------ */
function renderRadar(data) {
  setBadge(els.radarBadge, data);
  els.radarBar.hidden = true;
  els.radarScale.hidden = true;

  if (!data.available || !data.steps || data.steps.length === 0) {
    els.radarNote.textContent = "Radar not available for this location (models-only display).";
    return;
  }
  els.radarNote.textContent = "Strongest cell within the local radius, per 5-minute step.";

  let maxV = 0;
  for (const s of data.steps) maxV = Math.max(maxV, s.precip_mm || 0);
  const scale = Math.max(RADAR_MAX_MM, maxV);

  els.radarBar.innerHTML = "";
  const n = data.steps.length;
  for (let i = 0; i < n; i++) {
    const s = data.steps[i];
    const col = document.createElement("div");
    col.className = "radar-col";

    const track = document.createElement("div");
    track.className = "radar-track";
    const fill = document.createElement("div");
    fill.className = "radar-fill";
    const h = Math.round((Math.min((s.precip_mm || 0) / scale, 1) * 100));
    fill.style.height = `${h}%`;
    fill.title = `${fmtClock(s.start_utc)} · ${fmtNum(s.precip_mm, 2)} mm`;
    track.appendChild(fill);
    col.appendChild(track);

    const tick = document.createElement("div");
    tick.className = "radar-tick";
    // Label the first, every-6th, and last tick to avoid clutter.
    tick.textContent = (i === 0 || i === n - 1 || i % 6 === 0) ? fmtHour(s.start_utc) : "";
    col.appendChild(tick);
    els.radarBar.appendChild(col);
  }

  els.radarScale.hidden = false;
  els.radarScaleMin.textContent = fmtClock(data.steps[0].start_utc);
  els.radarScaleMax.textContent = fmtClock(data.steps[n - 1].start_utc);
  els.radarBar.hidden = false;
}

/* ------------------------------------------------------------------ *
 * Rendering: 24 h model comparison (SVG, see chart.js)
 * ------------------------------------------------------------------ */
function renderChart(data) {
  setBadge(els.chartBadge, data);
  renderModelChart(els.chart, els.legend, data, fmtHour, fmtNum);
}

/* ------------------------------------------------------------------ *
 * Rendering: data sources
 * ------------------------------------------------------------------ */
const SOURCE_LABELS = { radar: "Radar", current: "Now", forecast: "Models", ensemble: "Ensemble" };

function renderSources(data) {
  els.sources.innerHTML = "";
  const keys = ["radar", "current", "forecast", "ensemble"];
  for (const key of keys) {
    const s = data[key];
    if (!s) continue;
    const row = document.createElement("div");
    row.className = "source-row";
    const ageCls = s.stale ? "stale" : "";
    row.innerHTML =
      `<span class="source-name">${SOURCE_LABELS[key] || key}</span>` +
      `<span class="source-upstream">${s.upstream || ""}</span>` +
      `<span class="source-age ${ageCls}">${s.available ? fmtAge(s.age_seconds) + (s.stale ? " · stale" : "") : "no data"}</span>`;
    els.sources.appendChild(row);
    if (s.last_error) {
      const err = document.createElement("div");
      err.className = "source-err";
      err.textContent = s.last_error;
      els.sources.appendChild(err);
    }
  }
}

/* Shared badge: "age · stale" for a card with age_seconds/stale fields. */
function setBadge(badge, data) {
  if (!badge) return;
  if (data.available) {
    badge.hidden = false;
    badge.textContent = fmtAge(data.age_seconds) + (data.stale ? " · stale" : "");
    badge.classList.toggle("stale", !!data.stale);
  } else {
    badge.hidden = false;
    badge.textContent = "no data";
    badge.classList.remove("stale");
  }
}

/* ------------------------------------------------------------------ *
 * Config
 * ------------------------------------------------------------------ */
function renderConfig(c) {
  cfg = c;
  tz = (c.location && c.location.timezone) || "UTC";
  const { latitude, longitude } = c.location || {};
  els.subtitle.textContent = `${latitude.toFixed(3)}, ${longitude.toFixed(3)} · ${tz}`;
}

/* ------------------------------------------------------------------ *
 * Orchestration
 * ------------------------------------------------------------------ */
async function load() {
  try {
    const [now, rain, radar, models, sources] = await Promise.all([
      getJSON("/api/now"),
      getJSON("/api/rain-probability"),
      getJSON("/api/radar/next-hour"),
      getJSON("/api/models/24h"),
      getJSON("/api/sources"),
    ]);
    renderHero(rain);
    renderNow(now);
    renderRadar(radar);
    renderChart(models);
    renderAccuracyCard(); // step 6f; fetches /api/model-accuracy itself
    renderSources(sources);
    if (els.refreshBadge) {
      els.refreshBadge.hidden = false;
      const oldest = [rain.radar_age_seconds, rain.models_age_seconds]
        .filter((v) => v != null)
        .sort((a, b) => b - a)[0];
      els.refreshBadge.textContent = `updated ${fmtAge(oldest == null ? null : oldest)} ago`;
    }
  } catch (e) {
    console.error(e);
    els.heroExplain.textContent = "Could not reach the API. Refreshing…";
  }
}

/* ------------------------------------------------------------------ *
 * Boot
 * ------------------------------------------------------------------ */
initTheme();
els.themeToggle.addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme");
  applyTheme(cur === "dark" ? "light" : "dark");
});

(async function start() {
  try {
    renderConfig(await getJSON("/api/config"));
  } catch (e) {
    console.error(e);
    els.subtitle.textContent = "configuration unavailable";
  }
  await load();
  setInterval(load, REFRESH_MS);
})();
