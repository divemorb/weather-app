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

/* The page reload's timing (W9b): the page re-fetches at the latest every
 * PAGE_REFRESH_MS, sooner PAGE_RELOAD_AFTER_REFRESH_MS after a scheduled
 * backend refresh; a failed /api/config at startup is retried every
 * CONFIG_RETRY_MS. Exported so details.js and app.js share one source and
 * the unit tests can pin the values. */
export const PAGE_REFRESH_MS = 60_000;
export const PAGE_RELOAD_AFTER_REFRESH_MS = 10_000;
export const CONFIG_RETRY_MS = 10_000;

/* The delay until the next page reload, in ms: at most `refreshMs`,
 * sooner right after a scheduled backend refresh — `reloadAfterRefreshMs`
 * after the job's next_run_utc, the soonest job winning. Jobs that are
 * missing, not objects, or carry no parsable next_run_utc are skipped.
 * Pure (unit-tested in rust/uitest/unit/more/refresh-w9b.test.mjs). */
export function nextLoadDelay(jobs, serverNowMs, refreshMs, reloadAfterRefreshMs) {
  let delay = refreshMs;
  if (!jobs || typeof jobs !== "object") return delay;
  for (const job of Object.values(jobs)) {
    if (!job || typeof job !== "object" || !job.next_run_utc) continue;
    const until = Date.parse(job.next_run_utc) - serverNowMs + reloadAfterRefreshMs;
    if (until > 0 && until < delay) delay = until;
  }
  return delay;
}

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

/* The header's place line: the label, else the coordinates to three
 * decimals; "" without a location (the page shows its own text). */
export function locationText(location) {
  if (!location) return "";
  if (location.label) return location.label;
  if (!validNumber(location.latitude) || !validNumber(location.longitude)) return "";
  return `${location.latitude.toFixed(3)}, ${location.longitude.toFixed(3)}`;
}

/* The muted line under the place: the time zone, and — when the place
 * shows a label — the coordinates before it:
 * "52.522, 13.414 · Europe/Berlin". Empty without a location. */
export function locationDetail(location) {
  if (!location) return "";
  const parts = [];
  if (location.label && validNumber(location.latitude) && validNumber(location.longitude)) {
    parts.push(`${location.latitude.toFixed(3)}, ${location.longitude.toFixed(3)}`);
  }
  if (location.timezone) parts.push(location.timezone);
  return parts.join(" · ");
}

/* The station's offset from the location, flat approximation (exact enough
 * at station distances): dx = Δlon·cos(lat)·111.32 km east,
 * dy = Δlat·110.57 km north. { bearing: degrees clockwise from north,
 * 0 ≤ b < 360, km: the distance }. null when a coordinate is missing. */
export function stationOffsetKm(from, to) {
  if (!from || typeof from !== "object" || !to || typeof to !== "object") return null;
  const lat = Number(from.lat ?? from.latitude);
  const lon = Number(from.lon ?? from.longitude);
  const lat2 = Number(to.lat ?? to.latitude);
  const lon2 = Number(to.lon ?? to.longitude);
  if (![lat, lon, lat2, lon2].every(Number.isFinite)) return null;
  const dy = (lat2 - lat) * 110.57; // km north
  const dx = (lon2 - lon) * Math.cos((lat * Math.PI) / 180) * 111.32; // km east
  const km = Math.hypot(dx, dy);
  const bearing = (Math.atan2(dx, dy) * 180) / Math.PI;
  return { bearing: (bearing + 360) % 360, km };
}

/* The map's marks: one per DWD station id — Now's station and an
 * observation station with the same id are one mark, and the Now's
 * station's coordinates win (it is the freshest). Returns
 * { id, name, lat, lon, distance_m, isNow } in first-seen order
 * (Now's station first, then the observation stations' API order). */
export function stationMarks(station, stations) {
  const marks = new Map();
  const add = (s, isNow) => {
    if (!s || typeof s !== "object") return;
    const id = s.dwd_station_id == null ? null : String(s.dwd_station_id);
    if (id === null || marks.has(id)) return;
    marks.set(id, {
      id,
      name: typeof s.name === "string" ? s.name : "",
      lat: Number(s.lat),
      lon: Number(s.lon),
      distance_m: typeof s.distance_m === "number" ? s.distance_m : null,
      isNow,
    });
  };
  add(station, true);
  if (Array.isArray(stations)) for (const s of stations) add(s, false);
  return [...marks.values()];
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

/* Has any model seen a rain hour at all (a hit or a miss)? Without one,
 * the accuracy table can only show false alarms, and a 100 % hit rate
 * means nothing yet (the "no rain measured" note). */
export function rainObserved(models) {
  const entries = models && typeof models === "object" ? Object.values(models) : [];
  return entries.some((m) => (m.hits || 0) + (m.misses || 0) > 0);
}

/* The accuracy table's row order: the models with enough data first,
 * each group by event accuracy, best first. Returns the model names.
 * Ties keep the API order (stable sort). */
export function sortAccuracy(models) {
  const names = models && typeof models === "object" ? Object.keys(models) : [];
  return [...names].sort((a, b) => {
    const ma = models[a] || {};
    const mb = models[b] || {};
    if (!!ma.enough_data !== !!mb.enough_data) return ma.enough_data ? -1 : 1;
    const acc = (m) => (typeof m.event_accuracy === "number" ? m.event_accuracy : -1);
    return acc(mb) - acc(ma);
  });
}
