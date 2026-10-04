// Contract for scene() in app/static/format.js (sky step A3, qwen/sky/00_plan.md).
// scene(now, radar) takes the /api/now and /api/radar/next-hour answers (or null)
// and names the sky the page shows; the page sets it as <html data-scene>.
import { test } from "node:test";
import assert from "node:assert/strict";
import { scene } from "../../../app/static/format.js";

const ICONS = ["clear-day", "clear-night", "partly-cloudy-day", "partly-cloudy-night", "cloudy", "fog",
  "wind", "rain", "sleet", "snow", "hail", "thunderstorm"];
const now = (icon) => ({ available: true, age_seconds: 60, stale: false, conditions: { condition: "dry", icon } });
const radar = (...mm) => ({ available: true, steps: mm.map((v, i) => ({ start_utc: `2026-10-04T10:${String(5 * i).padStart(2, "0")}:00Z`, precip_mm: v })) });
const DRY = radar(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);

test("scene: Bright Sky's icon when the radar is dry", () => {
  for (const icon of ICONS) assert.equal(scene(now(icon), DRY), icon, icon);
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
