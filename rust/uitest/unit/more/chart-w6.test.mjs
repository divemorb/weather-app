// Step W6: the 24 h chart's pure helpers (chart.js). The series colours
// must stay readable in both themes, so each one is checked against the
// light and the dark card background (WCAG 3:1 for graphics).
import { test } from "node:test";
import assert from "node:assert/strict";
import { MODEL_COLORS, chartData, chartMetrics } from "../../../../app/static/chart.js";

function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

const contrast = (a, b) => {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

test("W6: six distinct series colours, readable in both themes", () => {
  assert.equal(MODEL_COLORS.length, 6);
  assert.equal(new Set(MODEL_COLORS).size, 6, "the series colours are not distinct");
  for (const color of MODEL_COLORS) {
    assert.match(color, /^#[0-9a-f]{6}$/, `not a 6-digit hex colour: ${color}`);
    for (const [name, card] of [["light", "#ffffff"], ["dark", "#1b1e23"]]) {
      const ratio = contrast(color, card);
      assert.ok(ratio >= 3, `${color} on the ${name} card is ${ratio.toFixed(2)}:1, needs 3:1`);
    }
  }
});

test("W6: chartMetrics clamps the width, narrows narrow screens", () => {
  assert.deepEqual(chartMetrics(628), { w: 628, h: 240, labelEvery: 3 });
  assert.deepEqual(chartMetrics(0), { w: 720, h: 240, labelEvery: 3 }); // missing -> the default
  assert.deepEqual(chartMetrics(284), { w: 300, h: 300, labelEvery: 6 }); // clamped, taller, sparser
  assert.deepEqual(chartMetrics(5199), { w: 1800, h: 240, labelEvery: 3 }); // clamped from above
  assert.deepEqual(chartMetrics(1190, true), { w: 1190, h: 100, labelEvery: 3 }); // kiosk, no measured height
  assert.deepEqual(chartMetrics(1190, true, 250), { w: 1190, h: 250, labelEvery: 3 }); // kiosk: the card's free height
  assert.deepEqual(chartMetrics(1190, true, 10), { w: 1190, h: 140, labelEvery: 3 }); // clamped from below
  assert.deepEqual(chartMetrics(1190, true, 9999), { w: 1190, h: 480, labelEvery: 3 }); // clamped from above
});

test("W6: chartData is null without any usable data", () => {
  assert.equal(chartData(null), null);
  assert.equal(chartData({}), null);
  assert.equal(chartData({ available: false, hours: [], models: [] }), null);
  assert.equal(chartData({ available: true, hours: [], models: [{ name: "a", precipitation_mm: [] }] }), null);
  assert.equal(chartData({ available: true, hours: ["2026-09-30T10:00:00Z"], models: [] }), null);
});

test("W6: chartData keeps hours and the models in API order", () => {
  const data = {
    available: true,
    hours: ["2026-09-30T10:00:00Z", "2026-09-30T11:00:00Z"],
    models: [
      { name: "icon_d2", precipitation_mm: [0, 1] },
      { name: "arome_france", precipitation_mm: [2.5, null] },
    ],
  };
  const d = chartData(data);
  assert.deepEqual(d.hours, data.hours);
  assert.deepEqual(d.models.map((m) => m.name), ["icon_d2", "arome_france"]);
});
