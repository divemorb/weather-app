/* fit.js — the big view fits its window (kiosk.css: the arrangements).
 *
 * fit() lays the page out as one screen (the arrangement the window's
 * shape picks) and measures it: if a card's content or the page is larger
 * than its box, the compact arrangement (one column that scrolls). The
 * text keeps the type scale either way (type.css). It starts over from
 * one screen each time, so the result depends only on the window and the
 * content. Runs once per frame after a resize, a size change of .wrap or
 * a content change; view.js calls scheduleFit().
 */

const root = document.documentElement;
const wrap = document.querySelector(".wrap");
const dash = document.getElementById("dashboard");
const setup = document.getElementById("setup");
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

// one screen when it fits, else compact (keeps the scroll position)
export function fit() {
  const top = document.scrollingElement.scrollTop;
  root.classList.remove("compact");
  if (root.classList.contains("kiosk") && (dash.hidden || !setup.hidden || overflows())) {
    root.classList.add("compact");
  }
  document.scrollingElement.scrollTop = top;
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
