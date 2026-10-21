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

test("chartMetrics: the box's size 1:1, margins from the text, hours spaced by the label width", () => {
  const pads = { padL: 26, padR: 26, padT: 12, padB: 29 };
  assert.deepEqual(chartMetrics(628, 240, 24, 12, 52, 8), { w: 628, h: 240, ...pads, labelEvery: 3 });
  assert.deepEqual(chartMetrics(628.7, 240.9, 24, 12, 52, 8), { w: 628, h: 240, ...pads, labelEvery: 3 }); // whole px
  assert.deepEqual(chartMetrics(300, 200, 24, 12, 52, 8), { w: 300, h: 200, ...pads, labelEvery: 6 }); // narrow: sparser
  assert.deepEqual(chartMetrics(100, 50, 24, 12, 52, 8), { w: 100, h: 50, ...pads, labelEvery: 24 }); // no room: one label
  assert.deepEqual(chartMetrics(1190, 250, 24, 20, 80, 14), // larger text: wider margins, a label every 2nd hour
    { w: 1190, h: 250, padL: 40, padR: 40, padT: 20, padB: 48, labelEvery: 2 });
  assert.deepEqual(chartMetrics(0, 0, 24), { w: 1, h: 1, padL: 28, padR: 24, padT: 12, padB: 29, labelEvery: 24 }); // defaults
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
