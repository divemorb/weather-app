// Extra edge cases for app/static/format.js and app/static/i18n.js
// (step W1, beyond the contract in format.test.mjs / i18n.test.mjs).
import { test } from "node:test";
import assert from "node:assert/strict";
import { STRINGS, pickLang, t } from "../../../../app/static/i18n.js";
import {
  conditionKey, fmtAge, fmtCountdown, fmtPercent, fmtTime, fmtTemp, modelLabel,
  niceScale, radarWindow, rainAnswer, rainLevel, windDir,
} from "../../../../app/static/format.js";

const TZ = "Europe/Berlin";

test("pickLang: skips empty and non-string entries, long subtag chains", () => {
  assert.equal(pickLang(["", "fr", "de-DE-x-liv", null, 3]), "de");
  assert.equal(pickLang(["EN-us", "fr-CA"]), "en");
  assert.equal(pickLang(["deu"]), "en"); // only the exact primary subtags de/en
});

test("t: placeholder values are inserted literally, missing params stay", () => {
  assert.equal(t("en", "radar.fromTo", { from: "1{2} (a|b)", to: "{n}" }), "Radar: rain from 1{2} (a|b) to {n}");
  assert.equal(t("en", "signals.models", { n: 4 }), "4 of {total}");
  assert.equal(t("de", "age.na"), STRINGS.de["age.na"]); // both languages defined
});

test("fmtTime: an invalid time zone is a missing value", () => {
  assert.equal(fmtTime("2026-09-30T10:50:00Z", "en-US", "Not/AZone"), "—");
  assert.equal(fmtTime("2026-09-30T10:50:00Z", "en-US", "UTC"), "10:50 AM");
});

test("fmtCountdown: zero, rounding up, and non-finite input", () => {
  assert.equal(fmtCountdown(0), "0:00");
  assert.equal(fmtCountdown(59999), "1:00"); // ceils to the whole second
  assert.equal(fmtCountdown(3599000), "59:59");
  assert.equal(fmtCountdown(3599999), "1:00:00"); // ceils over the hour
  assert.equal(fmtCountdown(Number.NaN), "0:00");
});

test("fmtAge: the minute boundary rounds to the hour", () => {
  assert.equal(fmtAge(59, "en"), "59 s");
  assert.equal(fmtAge(3599, "en"), "1 h"); // 59.98 min -> 60 min -> 1 h
  assert.equal(fmtAge(7200, "de"), "2 h");
});

test("windDir: negative and over-360 degrees", () => {
  assert.equal(windDir(-90, "en"), "W");
  assert.equal(windDir(450, "en"), "E");
  assert.equal(windDir(-45, "de"), "NW"); // -45 ≡ 315°
});

test("radarWindow: rain with a gap between the steps", () => {
  const step = (min, mm) => ({ start_utc: new Date(Date.UTC(2026, 8, 30, 10, 50 + 5 * min)).toISOString(), precip_mm: mm });
  const w = radarWindow([step(0, 0), step(1, 0.3), step(2, 0), step(3, 0), step(4, 0), step(5, 0.1), step(6, 0), step(7, 0)]);
  assert.equal(Date.parse(w.from), Date.parse("2026-09-30T10:55:00Z"));
  assert.equal(Date.parse(w.to), Date.parse("2026-09-30T11:20:00Z")); // end of the last rainy step
  assert.equal(w.now, false);
});

test("rainAnswer: nodata for missing or null weights_used", () => {
  for (const rain of [null, { probability_pct: 40, weights_used: null }, { probability_pct: 40 }]) {
    assert.deepEqual(rainAnswer(rain, null, "en", "en-US", TZ),
      { level: "nodata", headline: "No forecast data yet", detail: "" });
  }
});

test("niceScale: big maxima use the wide steps (and the last fallback)", () => {
  assert.deepEqual(niceScale(100), { step: 50, max: 100, ticks: [0, 50, 100] });
  assert.deepEqual(niceScale(400), { step: 100, max: 400, ticks: [0, 100, 200, 300, 400] });
  const big = niceScale(1000); // beyond the table: the widest step, 5 ticks
  assert.equal(big.step, 100);
  assert.deepEqual(big.ticks, [0, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]);
});

test("conditionKey and rainLevel: the boundary values", () => {
  assert.equal(conditionKey("dry", 0), "clear");
  assert.equal(conditionKey("dry", 20.0001), "partly");
  assert.equal(conditionKey("fog", null), "fog");
  assert.equal(rainLevel(19.999), "dry");
  assert.equal(rainLevel(59.999), "possible");
});

test("fmtTemp and fmtPercent: the extremes", () => {
  assert.equal(fmtTemp(-0.6, "en-US"), "-1°");
  assert.equal(fmtTemp(0.49, "de-DE"), "0°");
  assert.equal(fmtPercent(100, "en-US"), "100%");
  assert.equal(modelLabel(null), null); // unknown names pass through
});
