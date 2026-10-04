// Contract for scene() and sceneReason() in app/static/format.js (sky steps A3, B1).
// scene(now, radar) takes the /api/now and /api/radar/next-hour answers (or null)
// and names the sky the page shows; the page sets it as <html data-scene>.
// The radar at the location decides about precipitation right now (its first
// 5-minute step); rule B (the user, 2026-10-04): a dry radar turns the station's
// rain, sleet, snow or hail into cloudy, a thunderstorm stays.
import { test } from "node:test";
import assert from "node:assert/strict";
import { scene, sceneReason } from "../../../app/static/format.js";

const ICONS = ["clear-day", "clear-night", "partly-cloudy-day", "partly-cloudy-night", "cloudy", "fog",
  "wind", "rain", "sleet", "snow", "hail", "thunderstorm"];
const now = (icon) => ({ available: true, age_seconds: 60, stale: false, conditions: { condition: "dry", icon } });
const radar = (...mm) => ({ available: true, steps: mm.map((v, i) => ({ start_utc: `2026-10-04T10:${String(5 * i).padStart(2, "0")}:00Z`, precip_mm: v })) });
const DRY = radar(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);

const WET = ["rain", "sleet", "snow", "hail"];

test("scene: Bright Sky's icon when the radar is dry, but no precipitation (rule B)", () => {
  for (const icon of ICONS) assert.equal(scene(now(icon), DRY), WET.includes(icon) ? "cloudy" : icon, icon);
  assert.equal(scene(now("thunderstorm"), DRY), "thunderstorm");
});

test("scene: without a usable radar the icon stays", () => {
  for (const icon of ICONS) {
    assert.equal(scene(now(icon), null), icon, icon);
    assert.equal(scene(now(icon), { available: false, steps: [] }), icon, icon);
    assert.equal(scene(now(icon), { available: true, steps: [] }), icon, icon);
    assert.equal(scene(now(icon), { available: true, steps: [{ precip_mm: null }] }), icon, icon);
  }
});

test("scene: none without an icon or with an unknown one", () => {
  assert.equal(scene(null, null), "none");
  assert.equal(scene(now(null), DRY), "none");
  assert.equal(scene(now(undefined), DRY), "none");
  assert.equal(scene(now("tornado"), DRY), "none");
  assert.equal(scene(now("CLOUDY"), DRY), "none");
  assert.equal(scene({ available: false, age_seconds: null, stale: false, conditions: null }, DRY), "none");
});

test("scene: rain on the radar right now (the first step) overrides a dry icon", () => {
  assert.equal(scene(now("clear-day"), radar(0.1, 0, 0)), "rain");
  assert.equal(scene(now("partly-cloudy-night"), radar(0.01)), "rain");
  assert.equal(scene(now("cloudy"), radar(0.19, 0)), "rain");
  assert.equal(scene(now("cloudy"), radar(0.2, 0)), "heavy-rain"); // >= 0.2 mm per 5 minutes
  assert.equal(scene(now("wind"), radar(1.5)), "heavy-rain");
  assert.equal(scene(now("rain"), radar(0.1)), "rain");
  assert.equal(scene(now("rain"), radar(0.5)), "heavy-rain");
  assert.equal(scene(now(null), radar(0.1)), "rain"); // the radar alone is data too
  assert.equal(scene(null, radar(0.3)), "heavy-rain");
});

test("scene: a precipitation icon stays (radar can't tell snow from rain)", () => {
  for (const icon of ["sleet", "snow", "hail", "thunderstorm"]) {
    assert.equal(scene(now(icon), radar(0.1)), icon, icon);
    assert.equal(scene(now(icon), radar(0.9)), icon, icon);
  }
});

test("scene: only the first step counts; an unavailable radar doesn't", () => {
  assert.equal(scene(now("cloudy"), radar(0, 0, 0, 0.5)), "cloudy");
  assert.equal(scene(now("fog"), { available: false, steps: [] }), "fog");
  assert.equal(scene(now("fog"), { available: false, steps: [{ start_utc: "x", precip_mm: 0.5 }] }), "fog");
});

test("scene: malformed answers don't throw", () => {
  for (const [n, r] of [[{}, {}], [undefined, undefined], [{ conditions: {} }, { available: true }],
    [now("cloudy"), { available: true, steps: [null] }], [now("cloudy"), { available: true, steps: "x" }],
    [now("cloudy"), { available: true, steps: [{ precip_mm: null }] }], [now("cloudy"), { available: true, steps: [{ precip_mm: "1" }] }],
    [{ available: true, conditions: null }, null], ["x", 5]]) {
    const s = scene(n, r);
    assert.ok(ICONS.includes(s) || s === "heavy-rain" || s === "none", `${JSON.stringify([n, r])} -> ${s}`);
  }
  assert.equal(scene(now("cloudy"), { available: true, steps: [null] }), "cloudy");
  assert.equal(scene(now("cloudy"), { available: true, steps: [{ precip_mm: "1" }] }), "cloudy");
  assert.equal(scene({}, {}), "none");
});

// sceneReason: the scene plus what decided it, for the "why" line under the glance.
// source: "station" (Bright Sky's icon), "radar" (the radar at the location overrode
// the icon, either way), "none"; stationIcon: the valid icon or null; radarDry: the
// radar is available and its first step is 0 mm.
test("sceneReason: who decided the sky", () => {
  assert.deepEqual(sceneReason(now("cloudy"), DRY), { scene: "cloudy", source: "station", stationIcon: "cloudy", radarDry: true });
  assert.deepEqual(sceneReason(now("fog"), null), { scene: "fog", source: "station", stationIcon: "fog", radarDry: false });
  assert.deepEqual(sceneReason(now("clear-day"), radar(0.1)), { scene: "rain", source: "radar", stationIcon: "clear-day", radarDry: false });
  assert.deepEqual(sceneReason(now("rain"), radar(0.5)), { scene: "heavy-rain", source: "radar", stationIcon: "rain", radarDry: false });
  assert.deepEqual(sceneReason(now("rain"), DRY), { scene: "cloudy", source: "radar", stationIcon: "rain", radarDry: true });
  assert.deepEqual(sceneReason(now("snow"), DRY), { scene: "cloudy", source: "radar", stationIcon: "snow", radarDry: true });
  assert.deepEqual(sceneReason(now("snow"), radar(0.5)), { scene: "snow", source: "station", stationIcon: "snow", radarDry: false });
  assert.deepEqual(sceneReason(now("thunderstorm"), DRY), { scene: "thunderstorm", source: "station", stationIcon: "thunderstorm", radarDry: true });
  assert.deepEqual(sceneReason(null, radar(0.1)), { scene: "rain", source: "radar", stationIcon: null, radarDry: false });
  assert.deepEqual(sceneReason(now(null), DRY), { scene: "none", source: "none", stationIcon: null, radarDry: true });
  assert.deepEqual(sceneReason(null, null), { scene: "none", source: "none", stationIcon: null, radarDry: false });
});

test("sceneReason agrees with scene()", () => {
  for (const icon of [...ICONS, null, "tornado"]) {
    for (const r of [DRY, radar(0.1), radar(0.3), null, { available: false, steps: [] }]) {
      assert.equal(sceneReason(now(icon), r).scene, scene(now(icon), r), `${icon} ${JSON.stringify(r)}`);
    }
  }
});
