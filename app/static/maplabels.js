/* maplabels.js — where the station map writes its names. Each label goes
 * to the first of its spots (below its symbol, above, right, left, then the
 * four corners) that stays inside the map and covers no symbol and no label
 * placed before it; when every spot is taken, to the one covering least.
 * Pure: boxes in, boxes out (no DOM), so the unit tests run it in node.
 *
 * A box is {l, t, r, b} in the map's units; a label is {anchors, w, h}:
 * its text's size and the symbols it may sit around ({x, y, r}: r is half
 * the symbol's box, tried in order), e.g. the radar circle first and the
 * place's own mark second. */

export const LABEL_GAP = 3; // between a label and its symbol or another label

// the area two boxes share (0 when apart)
function shared(a, b) {
  const w = Math.min(a.r, b.r) - Math.max(a.l, b.l);
  const h = Math.min(a.b, b.b) - Math.max(a.t, b.t);
  return w > 0 && h > 0 ? w * h : 0;
}

// a box grown by d on every side
function grown(a, d) {
  return { l: a.l - d, t: a.t - d, r: a.r + d, b: a.b + d };
}

/* The spots for a w x h label around a symbol, LABEL_GAP off its box, best
 * first: centred below and above it (shifted sideways to stay inside the
 * map), right and left of it, then its four corners. */
export function spots({ x, y, r }, w, h, bounds) {
  const d = r + LABEL_GAP;
  const inside = (l) => Math.min(Math.max(l, bounds.l), bounds.r - w);
  const at = (l, t) => ({ l, t, r: l + w, b: t + h });
  return [
    at(inside(x - w / 2), y + d), at(inside(x - w / 2), y - d - h),
    at(x + d, y - h / 2), at(x - d - w, y - h / 2),
    at(x + d, y + d), at(x - d - w, y + d), at(x + d, y - d - h), at(x - d - w, y - d - h),
  ];
}

// how much a spot covers: of the symbols and labels, and past the map's edge (counted 4x)
function cost(box, taken, bounds) {
  const outside = (box.r - box.l) * (box.b - box.t) - shared(box, bounds);
  return 4 * outside + taken.reduce((sum, o) => sum + shared(grown(box, LABEL_GAP), o), 0);
}

/* The labels' boxes, in the given order (each one's box becomes an obstacle
 * for the labels after it); `symbols` are the boxes no label may cover. */
export function placeLabels(labels, symbols, bounds) {
  const taken = [...symbols];
  return labels.map(({ anchors, w, h }) => {
    let best = null;
    let bestCost = Infinity;
    for (const a of anchors) {
      for (const box of spots(a, w, h, bounds)) {
        const c = cost(box, taken, bounds);
        if (c < bestCost) [best, bestCost] = [box, c];
        if (c === 0) break;
      }
      if (bestCost === 0) break;
    }
    taken.push(best);
    return best;
  });
}
