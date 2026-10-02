/* format.js — pure formatting helpers (step W1).
 *
 * No DOM, no navigator, no Date.now(): the locale (the browser's
 * navigator.language) and the location's time zone (from /api/config)
 * are parameters. The contract is rust/uitest/unit/format.test.mjs.
 * Intl puts non-breaking spaces into some outputs ("75 %", "12:50 PM");
 * that is fine — the UI harness compares with ordinary spaces.
 */

import { t } from "./i18n.js";

export const DASH = "—"; // every missing value

function validNumber(v) {
  return typeof v === "number" && Number.isFinite(v);
}

function formatNumber(value, locale, options) {
  if (!validNumber(value)) return DASH;
  try {
    return new Intl.NumberFormat(locale, options).format(value);
  } catch {
    return DASH;
  }
}

/* The browser's time format (numeric hour, two-digit minute) in the
 * location's time zone; invalid or missing input -> "—". */
export function fmtTime(utcStr, locale, timeZone) {
  if (utcStr == null || utcStr === "") return DASH;
  const d = new Date(utcStr);
  if (isNaN(d.getTime())) return DASH;
  try {
    return new Intl.DateTimeFormat(locale, { hour: "numeric", minute: "2-digit", timeZone }).format(d);
  } catch {
    return DASH;
  }
}

/* A number with exactly `digits` decimals; null/NaN -> "—". */
export function fmtNumber(value, locale, digits = 1) {
  return formatNumber(value, locale, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/* A percentage 0..100 as "75%" (en) / "75 %" (de), no decimals. */
export function fmtPercent(pct, locale) {
  if (!validNumber(pct)) return DASH;
  try {
    return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }).format(pct / 100);
  } catch {
    return DASH;
  }
}

/* Millimetres, one decimal by default: "0.2 mm". */
export function fmtMm(value, locale, digits = 1) {
  const n = formatNumber(value, locale, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return n === DASH ? DASH : `${n} mm`;
}

/* Hectopascals without grouping: "1025 hPa". */
export function fmtPressure(value, locale) {
  const n = formatNumber(value, locale, { minimumFractionDigits: 0, maximumFractionDigits: 0, useGrouping: false });
  return n === DASH ? DASH : `${n} hPa`;
}

/* Whole degrees, no negative zero: "21°", "-4°", "0°". */
export function fmtTemp(value, locale) {
  if (!validNumber(value)) return DASH;
  let deg = Math.round(value);
  if (deg === 0) deg = 0; // Math.round(-0.4) is -0, which Intl would print "-0"
  const n = formatNumber(deg, locale, { maximumFractionDigits: 0 });
  return n === DASH ? DASH : `${n}\u00B0`;
}

/* Wind speed as Bright Sky sends it (km/h despite the _ms field names). */
export function fmtWind(speed, locale) {
  const n = formatNumber(speed, locale, { maximumFractionDigits: 0 });
  return n === DASH ? DASH : `${n} km/h`;
}

/* The eight compass points; German letters (O for East, …) when lang is
 * German; negative degrees normalised; missing -> "". */
export function windDir(deg, lang) {
  if (!validNumber(deg)) return "";
  const german = String(lang || "").toLowerCase().split("-")[0] === "de";
  const pts = german ? ["N", "NO", "O", "SO", "S", "SW", "W", "NW"]
                     : ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  return pts[((Math.round(deg / 45) % 8) + 8) % 8];
}

const MODEL_LABELS = {
  icon_d2: "ICON-D2 (DWD)",
  icon_eu: "ICON-EU (DWD)",
  ecmwf_ifs025: "ECMWF IFS",
  gfs_seamless: "GFS (NOAA)",
  arome_france: "AROME (Météo-France)",
  ukmo_seamless: "UKMO (Met Office)",
};

/* Readable model name; unknown names pass through unchanged. */
export function modelLabel(name) {
  return MODEL_LABELS[name] ?? name;
}

const CONDITIONS = new Set(["dry", "fog", "rain", "sleet", "snow", "hail", "thunderstorm"]);

/* The key for the condition text (t(lang, "cond." + key)): a dry sky is
 * decided from the cloud cover, the six wet conditions map to
 * themselves, anything else (and null) -> null. */
export function conditionKey(condition, cloudPct) {
  if (typeof condition !== "string" || !CONDITIONS.has(condition)) return null;
  if (condition !== "dry") return condition;
  if (!validNumber(cloudPct)) return "dry";
  if (cloudPct <= 20) return "clear";
  if (cloudPct <= 70) return "partly";
  return "overcast";
}

/* < 20 dry, < 60 possible, otherwise likely. */
export function rainLevel(pct) {
  if (pct < 20) return "dry";
  if (pct < 60) return "possible";
  return "likely";
}

/* The rainy window over the five-minute radar steps: { from: start_utc
 * of the first rainy step, to: the end of the last rainy step (its start
 * plus 5 min, ISO) or null when the rain continues in the last step,
 * now: the first step already rains }. null when no step is rainy. */
export function radarWindow(steps) {
  if (!Array.isArray(steps) || steps.length === 0) return null;
  let first = -1;
  let last = -1;
  for (let i = 0; i < steps.length; i++) {
    const mm = steps[i] && steps[i].precip_mm;
    if (typeof mm === "number" && mm > 0) {
      if (first < 0) first = i;
      last = i;
    }
  }
  if (first < 0) return null;
  let to = null;
  if (last < steps.length - 1) {
    const end = new Date(Date.parse(steps[last].start_utc) + 5 * 60 * 1000);
    if (!isNaN(end.getTime())) to = end.toISOString();
  }
  return { from: steps[first].start_utc, to, now: first === 0 };
}

/* The glance: { level, headline, detail }. The headline comes from the
 * probability ("nodata" when weights_used is empty, then
 * probability_pct is a meaningless 0); the detail from the radar
 * window, with the times formatted for the location's time zone. */
export function rainAnswer(rain, radar, lang, locale, tz) {
  const weights = rain && rain.weights_used;
  if (!weights || Object.keys(weights).length === 0) {
    return { level: "nodata", headline: t(lang, "answer.nodata"), detail: "" };
  }
  const level = rainLevel(rain.probability_pct);
  const headline = t(lang, "answer." + level);
  let detail;
  if (!radar || !radar.available) {
    detail = t(lang, "radar.unavailable");
  } else {
    const w = radarWindow(radar.steps);
    if (!w) {
      detail = t(lang, "radar.none");
    } else if (w.now && w.to) {
      detail = t(lang, "radar.nowUntil", { to: fmtTime(w.to, locale, tz) });
    } else if (w.now) {
      detail = t(lang, "radar.now");
    } else if (w.to) {
      detail = t(lang, "radar.fromTo", { from: fmtTime(w.from, locale, tz), to: fmtTime(w.to, locale, tz) });
    } else {
      detail = t(lang, "radar.from", { from: fmtTime(w.from, locale, tz) });
    }
  }
  return { level, headline, detail };
}

const SCALE_STEPS = [0.2, 0.5, 1, 2, 5, 10, 20, 50, 100];

function makeScale(step, n) {
  const ticks = [];
  for (let i = 0; i <= n; i++) ticks.push(Number((i * step).toFixed(1)));
  return { step, max: ticks[n], ticks };
}

/* The y axis of the 24 h chart (mm per hour): max is clamped to at
 * least 0.5, then the first nice step whose 0..n ticks fit (n <= 4). */
export function niceScale(max) {
  const v = Number(max);
  const m = Number.isFinite(v) ? Math.max(0.5, v) : 0.5;
  let fallback = null;
  for (const step of SCALE_STEPS) {
    const n = Math.ceil(m / step - 1e-9);
    if (n <= 4) return makeScale(step, n);
    fallback = { step, n };
  }
  return makeScale(fallback.step, fallback.n);
}

/* How old data is: "45 s", "10 min", "2 h 5 min" (or "1 h");
 * null -> t("age.na"). */
export function fmtAge(seconds, lang) {
  if (!validNumber(seconds)) return t(lang, "age.na");
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest === 0 ? `${h} h` : `${h} h ${rest} min`;
}

/* Countdown to the next event: "m:ss" or "h:mm:ss", never negative
 * (the old countdown.js behaviour). */
export function fmtCountdown(ms) {
  const value = validNumber(ms) ? ms : 0;
  const total = Math.max(0, Math.ceil(value / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}
