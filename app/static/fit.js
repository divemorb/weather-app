/* fit.js — F4: the big view's headline on a narrow screen: at most two
 * lines, as large as the text allows.
 *
 * Only the big view (html.kiosk) below 760 px: the size is fitted to the
 * rendered text, starting at 40 px and stepping down one px at a time
 * until the headline takes at most two lines, never below 20 px.
 * Everywhere else the inline size is removed, so the CSS (kiosk.css,
 * style.css) decides as before. Called after glance.js sets the text, on
 * resize, and when view.js switches the view.
 */

const NARROW = window.matchMedia("(max-width: 760px)");
const MAX_PX = 40; /* the largest size to try */
const MIN_PX = 20; /* never below this */
const LINES = 2;   /* at most this many */

/* The rendered line count: the distinct line bottoms of a Range over the
 * element's text (the same measurement the page checks use). */
function lines(el) {
  const range = document.createRange();
  range.selectNodeContents(el);
  return new Set([...range.getClientRects()].filter((r) => r.width > 0).map((r) => Math.round(r.bottom))).size;
}

export function fitHeadline(el) {
  if (!el) return;
  if (!document.documentElement.classList.contains("kiosk") || !NARROW.matches) {
    el.style.fontSize = "";
    return;
  }
  for (let px = MAX_PX; px >= MIN_PX; px--) {
    el.style.fontSize = px + "px";
    if (lines(el) <= LINES) break;
  }
}

window.addEventListener("resize", () => fitHeadline(document.getElementById("rain-answer")));
