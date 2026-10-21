/* fit.js — the big view fits its window (kiosk.css: arrangements, tokens).
 *
 * fit() measures a one-screen arrangement and searches the largest --k at
 * which the cards' content fits: up to K_MAX (a large window is filled),
 * down to K_MIN (every token at its floor); if even the floors don't fit,
 * the compact arrangement (one column that scrolls, the headline fitted to
 * two lines). It starts over from --k 1 each time, so the result depends
 * only on the window and the content. Runs once per frame after a resize,
 * a size change of .wrap or a content change; view.js calls scheduleFit().
 */

const K_MIN = 0.2; /* every token is at its floor below this */
const K_MAX = 1.6; /* the most a one-screen view grows to fill a large window */
const STEPS = 6;   /* binary search steps: --k to about 1 % */
const HEAD_MAX = 40, HEAD_MIN = 20, HEAD_LINES = 2; /* the compact headline */

const root = document.documentElement;
const wrap = document.querySelector(".wrap");
const dash = document.getElementById("dashboard");
const setup = document.getElementById("setup");
const answer = document.getElementById("rain-answer");
const chartBody = document.getElementById("chart-body");

// true if the page or a card's content is larger than its box
function overflows() {
  if (root.scrollWidth > root.clientWidth + 1 || root.scrollHeight > root.clientHeight + 1) return true;
  const bottom = dash.getBoundingClientRect().bottom;
  for (const card of dash.children) {
    if (!card.checkVisibility()) continue;
    if (card.scrollHeight > card.clientHeight + 1 || card.scrollWidth > card.clientWidth + 1) return true;
    // a card held taller than its row (the open report picker) reaches past the grid
    if (card.getBoundingClientRect().bottom > bottom + 1) return true;
  }
  return false;
}

const setK = (k) => wrap.style.setProperty("--k", String(k));

/* The rendered line count: the distinct line bottoms of a Range over the
 * element's text (the same measurement the page checks use). */
function lines(el) {
  const range = document.createRange();
  range.selectNodeContents(el);
  return new Set([...range.getClientRects()].filter((r) => r.width > 0).map((r) => Math.round(r.bottom))).size;
}

// the compact headline: as large as fits in two lines
function fitHeadline() {
  for (let px = HEAD_MAX; px >= HEAD_MIN; px--) {
    answer.style.fontSize = px + "px";
    if (lines(answer) <= HEAD_LINES) break;
  }
}

// one-screen at the largest --k that fits, else compact (keeps the scroll position)
export function fit() {
  const top = document.scrollingElement.scrollTop;
  search();
  document.scrollingElement.scrollTop = top;
}

// the search itself: it leaves compact on the way, which scrolls to the top
function search() {
  answer.style.fontSize = "";
  root.classList.remove("compact");
  setK(1);
  if (!root.classList.contains("kiosk")) return;
  let lo, hi;
  if (dash.hidden || !setup.hidden) {
    lo = null;
  } else if (!overflows()) {
    [lo, hi] = [1, K_MAX];
  } else {
    [lo, hi] = [K_MIN, 1];
    setK(K_MIN);
    if (overflows()) lo = null;
  }
  if (lo === null) {
    setK(1);
    root.classList.add("compact");
    fitHeadline();
    return;
  }
  setK(hi);
  if (!overflows()) return;
  for (let i = 0; i < STEPS; i++) {
    const mid = (lo + hi) / 2;
    setK(mid);
    if (overflows()) hi = mid;
    else lo = mid;
  }
  setK(lo);
}

let queued = 0;
// fit() once in the next frame, however often it is asked for
export function scheduleFit() {
  if (!queued) queued = requestAnimationFrame(() => { queued = 0; fit(); });
}

window.addEventListener("resize", scheduleFit);
new ResizeObserver(scheduleFit).observe(wrap);
/* Content changes (data arriving, a line shown or hidden). Left out: the
 * chart's own redraws inside its body (they change no size) and text
 * changes in parts that aren't shown (the Details card's countdowns tick
 * every second in the big view, where the card is hidden). */
const counts = (r) => {
  if (chartBody.contains(r.target)) return false;
  if (r.type === "attributes") return true;
  const el = r.target.nodeType === Node.ELEMENT_NODE ? r.target : r.target.parentElement;
  return !el || el.checkVisibility();
};
new MutationObserver((records) => {
  if (records.some(counts)) scheduleFit();
}).observe(wrap, { subtree: true, childList: true, characterData: true, attributes: true,
  attributeFilter: ["hidden", "class"] });
