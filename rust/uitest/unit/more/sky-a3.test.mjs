// Steps A3a, B1: the sky scene's pure helper (format.js scene() and
// sceneReason()). The contract (scene.test.mjs) covers the main cases;
// these pin the edges the page relies on: malformed answers never throw,
// only the first radar step counts, the heavy-rain threshold is
// inclusive, and rule B (a dry radar turns the station's precipitation
// into cloudy, a thunderstorm stays) plus who decided the sky.
import { test } from "node:test";
import assert from "node:assert/strict";
import { scene, sceneReason, SKY_ICONS, HEAVY_RAIN_MM } from "../../../../app/static/format.js";

const now = (icon) =>
  icon == null
    ? { available: false, age_seconds: null, stale: false, conditions: null }
    : { available: true, age_seconds: 5, stale: false,
        conditions: { icon, label: icon, temp_c: 20, feels_like_c: 18,
                      wind_speed_kmh: 10, wind_direction_deg: 90, gust_kmh: 20,
                      humidity_pct: 50, pressure_hpa: 1013, rain_mm: 0, cloud_cover_pct: 0 } };

const radar = (mm, opts = {}) => ({
  available: opts.available !== false,
  steps: [{ start: "2026-09-30T10:25:00Z", precip_mm: mm }],
  ...(opts.extra ? { extra: opts.extra } : {}),
});

test("A3a: scene exports the twelve icons and the inclusive heavy threshold", () => {
  assert.equal(SKY_ICONS.length, 12);
  assert.ok(SKY_ICONS.includes("clear-day"));
  assert.ok(SKY_ICONS.includes("thunderstorm"));
  assert.equal(HEAVY_RAIN_MM, 0.2);
});

test("A3a: nothing to show is the plain background scene", () => {
  assert.equal(scene(null, null), "none");
  assert.equal(scene(undefined, undefined), "none");
  assert.equal(scene({}, {}), "none");
  assert.equal(scene(now(null), radar(0)), "none");
});

test("A3a: a dry icon shows itself, radar rain overrides it at step 0 only", () => {
  assert.equal(scene(now("fog"), radar(0)), "fog");
  assert.equal(scene(now("clear-day"), radar(0.1)), "rain");
  assert.equal(scene(now("clear-day"), radar(0.2)), "heavy-rain"); // threshold is inclusive
  assert.equal(scene(now("clear-day"), radar(0.199)), "rain");
  // rain later in the hour is not rain now: step 1 and beyond never count
  const later = { available: true, steps: [{ precip_mm: 0 }, { precip_mm: 5 }, { precip_mm: 5 }] };
  assert.equal(scene(now("cloudy"), later), "cloudy");
});

test("A3a: a rain icon is heavy only when the first step is heavy", () => {
  assert.equal(scene(now("rain"), radar(0.199)), "rain");
  assert.equal(scene(now("rain"), radar(0.2)), "heavy-rain");
  assert.equal(scene(now("rain"), radar(0.5)), "heavy-rain");
});

test("B1: rule B — a dry radar turns the station's precipitation into cloudy", () => {
  for (const icon of ["rain", "sleet", "snow", "hail"]) assert.equal(scene(now(icon), radar(0)), "cloudy", icon);
  assert.equal(scene(now("thunderstorm"), radar(0)), "thunderstorm"); // a thunderstorm stays
  // a wet radar keeps the icon (it can't tell snow from rain)
  for (const icon of ["sleet", "snow", "hail", "thunderstorm"]) assert.equal(scene(now(icon), radar(0.5)), icon, icon);
});

test("B1: sceneReason says who decided the sky", () => {
  assert.deepEqual(sceneReason(now("cloudy"), radar(0)), { scene: "cloudy", source: "station", stationIcon: "cloudy", radarDry: true });
  assert.deepEqual(sceneReason(now("rain"), radar(0)), { scene: "cloudy", source: "radar", stationIcon: "rain", radarDry: true });
  assert.deepEqual(sceneReason(now("snow"), radar(0)), { scene: "cloudy", source: "radar", stationIcon: "snow", radarDry: true });
  assert.deepEqual(sceneReason(now("thunderstorm"), radar(0)), { scene: "thunderstorm", source: "station", stationIcon: "thunderstorm", radarDry: true });
  assert.deepEqual(sceneReason(now("rain"), radar(0.5)), { scene: "heavy-rain", source: "radar", stationIcon: "rain", radarDry: false });
  // without a usable radar the icon decides
  assert.deepEqual(sceneReason(now("rain"), null), { scene: "rain", source: "station", stationIcon: "rain", radarDry: false });
  assert.deepEqual(sceneReason(now("clear-day"), radar(0.2)), { scene: "heavy-rain", source: "radar", stationIcon: "clear-day", radarDry: false });
  assert.deepEqual(sceneReason(null, null), { scene: "none", source: "none", stationIcon: null, radarDry: false });
  assert.deepEqual(sceneReason(now(null), radar(0)), { scene: "none", source: "none", stationIcon: null, radarDry: true });
});

test("A3a: the precipitation icons stay whatever a wet radar says", () => {
  for (const icon of ["sleet", "snow", "hail", "thunderstorm"]) {
    assert.equal(scene(now(icon), radar(5)), icon, icon);
    assert.equal(scene(now(icon), null), icon, icon + " without radar");
  }
});

test("A3a: malformed answers never throw and count as no data", () => {
  // string millimetres are not millimetres
  assert.equal(scene(now("clear-day"), radar("1")), "clear-day");
  assert.equal(scene(now("clear-day"), radar(NaN)), "clear-day");
  assert.equal(scene(now("clear-day"), radar(Infinity)), "clear-day");
  // unavailable or broken radar
  assert.equal(scene(now("clear-day"), radar(0.5, { available: false })), "clear-day");
  assert.equal(scene(now("clear-day"), { available: true }), "clear-day");
  assert.equal(scene(now("clear-day"), { available: true, steps: "nope" }), "clear-day");
  assert.equal(scene(now("clear-day"), { available: true, steps: [null] }), "clear-day");
  assert.equal(scene(now("clear-day"), { available: true, steps: [{ precip_mm: "0.3" }] }), "clear-day");
  assert.equal(scene(now("clear-day"), { available: true, steps: [] }), "clear-day");
  assert.equal(scene(null, radar(0.1)), "rain"); // rain on the radar without an observation
  assert.equal(scene(null, radar(0.3)), "heavy-rain");
  assert.equal(scene("junk", "junk"), "none");
  assert.equal(scene([1, 2], [3]), "none");
  assert.equal(scene({ conditions: 42 }, null), "none");
  assert.equal(scene({ conditions: { icon: 7 } }, null), "none");
  assert.equal(scene({ conditions: { icon: "tornado" } }, null), "none"); // unknown icon: no scene
});

test("A3a: every known icon is a scene of its own (with no radar)", () => {
  for (const icon of SKY_ICONS) {
    if (icon === "rain") continue; // rain without radar stays rain, but the contract covers it
    assert.equal(scene(now(icon), null), icon);
  }
  assert.equal(scene(now("rain"), null), "rain");
});
