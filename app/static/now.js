/* now.js — the Now section: the current conditions from /api/now.
 *
 * Temperature and condition big, the rest a quiet two-column grid, the
 * observation time under it. Wind and gusts are km/h (Bright Sky sends
 * km/h despite the _ms field names); the wind direction is one of the
 * eight compass points (German letters in German). When the observation
 * is missing (available false or conditions null) the section shows the
 * fixed "no observation" line and hides the values.
 */
import {
  DASH, conditionKey, fmtMm, fmtNumber, fmtPercent, fmtPressure, fmtTemp, fmtTime, fmtWind, windDir,
} from "./format.js";
import { t } from "./i18n.js";

const $ = (id) => document.getElementById(id);

const els = {
  body: $("now-body"),
  unavailable: $("now-unavailable"),
  temp: $("now-temp"),
  condition: $("now-condition"),
  feels: $("now-feels"),
  wind: $("now-wind"),
  gust: $("now-gust"),
  humidity: $("now-humidity"),
  pressure: $("now-pressure"),
  dewpoint: $("now-dewpoint"),
  clouds: $("now-clouds"),
  rain: $("now-rain"),
  time: $("now-time"),
  station: $("now-station"),
};

/* Which element a /api/now fallback entry points at. The wind direction
 * falls back with the wind speed, so both map to the wind value; a field
 * the page does not show gets no note. */
const FIELD_CELL = {
  temperature_c: "temp",
  feels_like_c: "feels",
  wind_speed_ms: "wind",
  wind_direction_deg: "wind",
  wind_gust_ms: "gust",
  humidity_pct: "humidity",
  pressure_hpa: "pressure",
  dew_point_c: "dewpoint",
  cloud_cover_pct: "clouds",
  precipitation_60mm: "rain",
};

/* The section's texts (title, grid labels); called once from app.js. */
export function initNow(lang) {
  $("now-title").textContent = t(lang, "now.title");
  $("now-feels-label").textContent = t(lang, "now.feels");
  $("now-wind-label").textContent = t(lang, "now.wind");
  $("now-gusts-label").textContent = t(lang, "now.gusts");
  $("now-humidity-label").textContent = t(lang, "now.humidity");
  $("now-pressure-label").textContent = t(lang, "now.pressure");
  $("now-dewpoint-label").textContent = t(lang, "now.dewpoint");
  $("now-clouds-label").textContent = t(lang, "now.clouds");
  $("now-rain-label").textContent = t(lang, "now.rain");
}

/* The values; called on every refresh. */
export function renderNow(now, lang, locale, tz) {
  const c = now && now.available && now.conditions ? now.conditions : null;
  if (!c) {
    els.body.hidden = true;
    els.unavailable.hidden = false;
    els.unavailable.textContent = t(lang, "now.unavailable");
    els.station.hidden = true;
    els.station.textContent = "";
    return;
  }
  els.unavailable.hidden = true;
  els.unavailable.textContent = "";
  els.body.hidden = false;

  els.temp.textContent = fmtTemp(c.temperature_c, locale);
  const key = conditionKey(c.condition, c.cloud_cover_pct);
  els.condition.textContent = key ? t(lang, "cond." + key) : DASH;

  els.feels.textContent = fmtTemp(c.feels_like_c, locale);
  const dir = windDir(c.wind_direction_deg, lang);
  els.wind.textContent = [fmtWind(c.wind_speed_ms, locale), dir].filter(Boolean).join(" ");
  els.gust.textContent = fmtWind(c.wind_gust_ms, locale);
  els.humidity.textContent = fmtPercent(c.humidity_pct, locale);
  els.pressure.textContent = fmtPressure(c.pressure_hpa, locale);
  els.dewpoint.textContent = fmtTemp(c.dew_point_c, locale);
  els.clouds.textContent = fmtPercent(c.cloud_cover_pct, locale);
  els.rain.textContent = fmtMm(c.precipitation_60mm, locale);
  els.time.textContent = `${t(lang, "now.as-of")} ${fmtTime(c.timestamp_utc, locale, tz)}`;
  renderStation(c, lang, locale);
  renderFallback(c, lang);
}

/* Who measured "Now": the station's name and its distance in km. Hidden
 * when /api/now carries no station. */
function renderStation(c, lang, locale) {
  const st = c.station && typeof c.station === "object" ? c.station : null;
  if (!st || typeof st.name !== "string" || st.name === "") {
    els.station.hidden = true;
    els.station.textContent = "";
    return;
  }
  const km = typeof st.distance_m === "number" ? fmtNumber(st.distance_m / 1000, locale, 1) : DASH;
  els.station.textContent = t(lang, "now.station", { name: st.name, km });
  els.station.hidden = false;
}

/* Values Bright Sky took from another station: a small muted note at the
 * value. Station names are untrusted API text: textContent, never
 * innerHTML. */
function renderFallback(c, lang) {
  for (const note of els.body.querySelectorAll("[data-test=now-fallback]")) note.remove();
  const fb = c.fallback && typeof c.fallback === "object" ? c.fallback : null;
  if (!fb) return;
  for (const [field, src] of Object.entries(fb)) {
    const cell = FIELD_CELL[field];
    if (!cell || !src || typeof src.name !== "string" || src.name === "") continue;
    const note = document.createElement("span");
    note.className = "now-fallback";
    note.setAttribute("data-test", "now-fallback");
    note.setAttribute("data-field", field);
    note.textContent = t(lang, "now.fallback", { name: src.name });
    els[cell].appendChild(note);
  }
}
