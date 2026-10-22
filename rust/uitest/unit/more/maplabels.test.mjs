// The station map's label placement (maplabels.js): each name at the first
// free spot around its symbol, never on another label or symbol, inside the map.
import { test } from "node:test";
import assert from "node:assert/strict";
import { LABEL_GAP, placeLabels, spots } from "../../../../app/static/maplabels.js";

const MAP = { l: 2, t: 2, r: 318, b: 318 };
const box = (x, y, r) => ({ l: x - r, t: y - r, r: x + r, b: y + r });
const apart = (a, b) => a.r <= b.l || b.r <= a.l || a.b <= b.t || b.b <= a.t;
const inside = (a) => a.l >= MAP.l && a.t >= MAP.t && a.r <= MAP.r && a.b <= MAP.b;

test("spots: below, above, right, left, then the corners, LABEL_GAP off the symbol's box", () => {
  const [below, above, right, left, ...corners] = spots({ x: 100, y: 100, r: 5 }, 40, 18, MAP);
  assert.deepEqual(below, { l: 80, t: 100 + 5 + LABEL_GAP, r: 120, b: 126 });
  assert.deepEqual(above, { l: 80, t: 74, r: 120, b: 92 });
  assert.deepEqual(right, { l: 108, t: 91, r: 148, b: 109 });
  assert.deepEqual(left, { l: 52, t: 91, r: 92, b: 109 });
  assert.equal(corners.length, 4);
});

test("spots: a label below or above a symbol near the edge is shifted inside the map", () => {
  const [below] = spots({ x: 310, y: 100, r: 5 }, 120, 18, MAP);
  assert.equal(below.r, MAP.r);
  const [, above] = spots({ x: 4, y: 100, r: 5 }, 120, 18, MAP);
  assert.equal(above.l, MAP.l);
});

test("placeLabels: a lone name goes under its mark", () => {
  const [b] = placeLabels([{ anchors: [{ x: 160, y: 100, r: 5 }], w: 60, h: 18 }], [box(160, 100, 5)], MAP);
  assert.deepEqual(b, spots({ x: 160, y: 100, r: 5 }, 60, 18, MAP)[0]);
});

test("placeLabels: the map's case — a near station's long name takes the room under the place, the place's name goes above its circle", () => {
  const scaleBar = { l: 11, t: 283, r: 121, b: 309 };
  const symbols = [box(160, 160, 6), box(192, 184, 5), box(164, 286, 5), scaleBar];
  const [near, far, here] = placeLabels([
    { anchors: [{ x: 192, y: 184, r: 5 }], w: 180, h: 18 },
    { anchors: [{ x: 164, y: 286, r: 5 }], w: 112, h: 18 },
    { anchors: [{ x: 160, y: 160, r: 23 }, { x: 160, y: 160, r: 6 }], w: 58, h: 18 },
  ], symbols, MAP);
  assert.equal(near.t, 184 + 5 + LABEL_GAP, "the near station's name under its mark");
  assert.equal(far.b, 286 - 5 - LABEL_GAP, "the far one above its mark (the scale bar under it)");
  assert.equal(here.b, 160 - 23 - LABEL_GAP, "the place's name above its radar circle");
  for (const b of [near, far, here]) assert.ok(inside(b));
});

test("placeLabels: a tight cluster — no name on another name or on any mark", () => {
  const marks = [[150, 150], [170, 150], [160, 165], [150, 180]];
  const symbols = marks.map(([x, y]) => box(x, y, 5));
  const boxes = placeLabels(marks.map(([x, y]) => ({ anchors: [{ x, y, r: 5 }], w: 70, h: 18 })), symbols, MAP);
  boxes.forEach((a, i) => {
    assert.ok(inside(a), `label ${i} inside the map`);
    boxes.slice(i + 1).forEach((b, j) => assert.ok(apart(a, b), `labels ${i} and ${i + j + 1} apart`));
    symbols.forEach((s, k) => assert.ok(apart(a, s), `label ${i} off mark ${k}`));
  });
});

test("placeLabels: with no free spot, the one covering least (never outside the map)", () => {
  const blocker = { l: 0, t: 0, r: 320, b: 150 };
  const [b] = placeLabels([{ anchors: [{ x: 160, y: 140, r: 5 }], w: 60, h: 18 }], [blocker], MAP);
  assert.ok(inside(b));
  assert.equal(b.t, 140 + 5 + LABEL_GAP, "under the mark: it covers the blocker least");
});
