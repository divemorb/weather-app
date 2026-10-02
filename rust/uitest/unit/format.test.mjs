// Contract for app/static/format.js (step W1). Run: node --test rust/uitest/unit/
// Pure functions: the locale (navigator.language) and the location's time
// zone are parameters, never read from the browser inside format.js.
// Intl puts no-break spaces into some outputs ("75 %", "12:50 PM"); the tests
// compare with ordinary spaces (norm), the page may keep Intl's characters.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  conditionKey, fmtAge, fmtCountdown, fmtMm, fmtNumber, fmtPercent, fmtPressure, fmtTemp, fmtTime,
  fmtWind, modelLabel, niceScale, radarWindow, rainAnswer, rainLevel, windDir,
} from "../../../app/static/format.js";

const norm = (s) => s.replace(/[   ]/g, " ");
const TZ = "Europe/Berlin";

test("fmtTime: the browser's time format, the location's time zone", () => {
  assert.equal(norm(fmtTime("2026-09-30T10:50:00Z", "de-DE", TZ)), "12:50");
  assert.equal(norm(fmtTime("2026-09-30T10:50:00Z", "en-US", TZ)), "12:50 PM");
  assert.equal(norm(fmtTime("2026-09-30T11:05:00Z", "en-US", TZ)), "1:05 PM");
  assert.equal(norm(fmtTime("2026-09-30T10:50:00Z", "en-GB", TZ)), "12:50");
  assert.equal(norm(fmtTime("2026-09-30T07:05:00Z", "de-DE", TZ)), "9:05");
  assert.equal(norm(fmtTime("2026-09-30T10:50:00Z", "de-DE", "UTC")), "10:50");
  assert.equal(fmtTime(null, "de-DE", TZ), "—");
  assert.equal(fmtTime("garbage", "de-DE", TZ), "—");
});

test("fmtNumber / fmtPercent / fmtMm / fmtPressure", () => {
  assert.equal(fmtNumber(0.2, "de-DE", 1), "0,2");
  assert.equal(fmtNumber(1234.5, "en-US", 1), "1,234.5");
  assert.equal(fmtNumber(2, "en-US", 0), "2");
  assert.equal(fmtNumber(null, "en-US", 1), "—");
  assert.equal(fmtNumber(NaN, "en-US", 1), "—");
  assert.equal(norm(fmtPercent(74.9, "en-US")), "75%");
  assert.equal(norm(fmtPercent(74.9, "de-DE")), "75 %");
  assert.equal(norm(fmtPercent(0, "de-DE")), "0 %");
  assert.equal(fmtPercent(null, "de-DE"), "—");
  assert.equal(norm(fmtMm(0.2, "de-DE")), "0,2 mm");
  assert.equal(norm(fmtMm(0, "en-US")), "0.0 mm");
  assert.equal(norm(fmtMm(0.143, "en-US", 2)), "0.14 mm");
  assert.equal(fmtMm(null, "en-US"), "—");
  assert.equal(norm(fmtPressure(1025, "de-DE")), "1025 hPa");
  assert.equal(norm(fmtPressure(1025.4, "en-US")), "1025 hPa");
  assert.equal(fmtPressure(null, "en-US"), "—");
});

test("fmtTemp: whole degrees, no negative zero", () => {
  assert.equal(fmtTemp(21.0, "de-DE"), "21°");
  assert.equal(fmtTemp(8.04, "en-US"), "8°");
  assert.equal(fmtTemp(-0.4, "de-DE"), "0°");
  assert.equal(fmtTemp(-3.6, "en-US"), "-4°");
  assert.equal(fmtTemp(null, "en-US"), "—");
});

test("fmtWind / windDir: km/h as Bright Sky sends it, 8-point compass", () => {
  assert.equal(norm(fmtWind(18.4, "de-DE")), "18 km/h");
  assert.equal(norm(fmtWind(37.4, "en-US")), "37 km/h");
  assert.equal(fmtWind(null, "en-US"), "—");
  assert.equal(windDir(130, "en"), "SE");
  assert.equal(windDir(130, "de"), "SO");
  assert.equal(windDir(90, "de"), "O");
  assert.equal(windDir(0, "en"), "N");
  assert.equal(windDir(359, "en"), "N");
  assert.equal(windDir(225, "de"), "SW");
  assert.equal(windDir(null, "en"), "");
});

test("modelLabel: readable names", () => {
  assert.equal(modelLabel("icon_d2"), "ICON-D2 (DWD)");
  assert.equal(modelLabel("icon_eu"), "ICON-EU (DWD)");
  assert.equal(modelLabel("ecmwf_ifs025"), "ECMWF IFS");
  assert.equal(modelLabel("gfs_seamless"), "GFS (NOAA)");
  assert.equal(modelLabel("arome_france"), "AROME (Météo-France)");
  assert.equal(modelLabel("ukmo_seamless"), "UKMO (Met Office)");
  assert.equal(modelLabel("some_new_model"), "some_new_model");
});

test("conditionKey: Bright Sky condition, sky from cloud cover when dry", () => {
  assert.equal(conditionKey("dry", 100), "overcast");
  assert.equal(conditionKey("dry", 71), "overcast");
  assert.equal(conditionKey("dry", 70), "partly");
  assert.equal(conditionKey("dry", 21), "partly");
  assert.equal(conditionKey("dry", 20), "clear");
  assert.equal(conditionKey("dry", null), "dry");
  assert.equal(conditionKey("rain", 100), "rain");
  assert.equal(conditionKey("thunderstorm", 40), "thunderstorm");
  assert.equal(conditionKey(null, 50), null);
  assert.equal(conditionKey("something-new", 50), null);
});

test("rainLevel: thresholds on the probability", () => {
  assert.equal(rainLevel(0), "dry");
  assert.equal(rainLevel(19.9), "dry");
  assert.equal(rainLevel(20), "possible");
  assert.equal(rainLevel(59.9), "possible");
  assert.equal(rainLevel(60), "likely");
  assert.equal(rainLevel(100), "likely");
});

const step = (min, mm) => ({ start_utc: new Date(Date.UTC(2026, 8, 30, 10, 50 + 5 * min)).toISOString(), precip_mm: mm });
const steps = (...mm) => mm.map((v, i) => step(i, v));
const RAIN_STEPS = steps(0, 0.2, 0.2, 0, 0, 0, 0, 0, 0, 0, 0, 0);

test("radarWindow: first to last rainy 5-minute step", () => {
  const w = radarWindow(RAIN_STEPS);
  assert.equal(Date.parse(w.from), Date.parse("2026-09-30T10:55:00Z"));
  assert.equal(Date.parse(w.to), Date.parse("2026-09-30T11:05:00Z")); // end of the last rainy step
  assert.equal(w.now, false);
  const open = radarWindow(steps(0.3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.1));
  assert.equal(open.now, true);
  assert.equal(open.to, null); // rain in the last step: the end is unknown
  assert.equal(radarWindow(steps(0, 0, 0)), null);
  assert.equal(radarWindow([]), null);
  assert.equal(radarWindow(null), null);
});

// API bodies as in rust/contract/golden (rain, live and errors scenarios)
const RAIN = { probability_pct: 74.9, weights_used: { radar: 0.5, models: 0.3, ensemble: 0.2 } };
const DRY = { probability_pct: 0.0, weights_used: { radar: 0.5, models: 0.3, ensemble: 0.2 } };
const NONE = { probability_pct: 0.0, weights_used: {} };
const answer = (...args) => {
  const a = rainAnswer(...args);
  return { level: a.level, headline: norm(a.headline), detail: norm(a.detail) };
};

test("rainAnswer: headline from the probability, detail from the radar", () => {
  assert.deepEqual(answer(RAIN, { available: true, steps: RAIN_STEPS }, "en", "en-US", TZ), {
    level: "likely", headline: "Rain likely in the next hour", detail: "Radar: rain from 12:55 PM to 1:05 PM" });
  assert.deepEqual(answer(RAIN, { available: true, steps: RAIN_STEPS }, "de", "de-DE", TZ), {
    level: "likely", headline: "In der nächsten Stunde wird es wahrscheinlich regnen",
    detail: "Radar: Regen von 12:55 bis 13:05" });
  assert.deepEqual(answer(DRY, { available: true, steps: steps(0, 0, 0) }, "de", "de-DE", TZ), {
    level: "dry", headline: "In der nächsten Stunde kein Regen erwartet", detail: "Radar: kein Regen in der Nähe" });
  assert.deepEqual(answer(NONE, { available: false, steps: steps(0, 0) }, "en", "en-US", TZ), {
    level: "nodata", headline: "No forecast data yet", detail: "" });
  assert.deepEqual(answer({ ...DRY, probability_pct: 35 }, { available: false, steps: [] }, "en", "en-US", TZ), {
    level: "possible", headline: "Rain possible in the next hour", detail: "Radar: not available" });
  assert.equal(answer(RAIN, { available: true, steps: steps(0.4, 0.2, 0, 0) }, "en", "en-US", TZ).detail,
    "Radar: raining now, until 1:00 PM");
  assert.equal(answer(RAIN, { available: true, steps: steps(0.4, 0.2, 0.1) }, "de", "de-DE", TZ).detail,
    "Radar: es regnet jetzt");
  assert.equal(answer(RAIN, { available: true, steps: steps(0, 0, 0.1) }, "de", "de-DE", TZ).detail,
    "Radar: Regen ab 13:00");
});

test("niceScale: y axis for the 24 h chart (mm per hour)", () => {
  assert.deepEqual(niceScale(2.5), { step: 1, max: 3, ticks: [0, 1, 2, 3] });
  assert.deepEqual(niceScale(1.2), { step: 0.5, max: 1.5, ticks: [0, 0.5, 1, 1.5] });
  assert.deepEqual(niceScale(4), { step: 1, max: 4, ticks: [0, 1, 2, 3, 4] });
  assert.deepEqual(niceScale(12), { step: 5, max: 15, ticks: [0, 5, 10, 15] });
  assert.deepEqual(niceScale(0.7), { step: 0.2, max: 0.8, ticks: [0, 0.2, 0.4, 0.6, 0.8] });
  assert.deepEqual(niceScale(0.6), { step: 0.2, max: 0.6, ticks: [0, 0.2, 0.4, 0.6] });
  assert.deepEqual(niceScale(0), { step: 0.2, max: 0.6, ticks: [0, 0.2, 0.4, 0.6] }); // at least 0.5
  assert.deepEqual(niceScale(0.3), { step: 0.2, max: 0.6, ticks: [0, 0.2, 0.4, 0.6] });
});

test("fmtAge / fmtCountdown", () => {
  assert.equal(fmtAge(0, "en"), "0 s");
  assert.equal(fmtAge(45, "en"), "45 s");
  assert.equal(fmtAge(600, "de"), "10 min");
  assert.equal(fmtAge(3600, "en"), "1 h");
  assert.equal(fmtAge(7500, "en"), "2 h 5 min");
  assert.equal(fmtAge(null, "en"), "n/a");
  assert.equal(fmtAge(null, "de"), "k. A.");
  assert.equal(fmtCountdown(300000), "5:00");
  assert.equal(fmtCountdown(299001), "5:00");
  assert.equal(fmtCountdown(61000), "1:01");
  assert.equal(fmtCountdown(3600000), "1:00:00");
  assert.equal(fmtCountdown(-5), "0:00");
});
