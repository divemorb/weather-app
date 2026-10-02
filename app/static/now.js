/* now.js — the Now section (step W5): the current conditions.
 *
 * Rendered from /api/now. The hierarchy: temperature and condition big,
 * the rest as a quiet two-column grid, the observation time under it.
 * Wind and gusts are km/h (Bright Sky sends km/h despite the _ms field
 * names); the wind direction is one of the eight compass points
 * (German letters in German). When the observation is missing
 * (available false or conditions null) the section shows the fixed
 * "no observation" line and hides the values.
 */
import {
  DASH, conditionKey, fmtMm, fmtPercent, fmtPressure, fmtTemp, fmtTime, fmtWind, windDir,
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
};

/* The section's own texts (title, the grid's labels); called once from
 * app.js with the picked language. */
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
}
