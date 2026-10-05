/* view.js — the two views: "big" (the one-screen wall look, what ?kiosk
 * gave before) and "detailed" (the tile grid with the Details card).
 *
 * The query decides first (?kiosk: the big view, locked — the wall display
 * shows neither the view nor the location button; ?detailed: the detailed
 * view), then the per-device choice (localStorage "view", wrapped in try),
 * then the big view. Sets <html data-view>, the kiosk class (kiosk.css and
 * chart.js key the big look on it) and the locked class; the button
 * toggles between the two views and stores the choice.
 */
import { pickLang, t } from "./i18n.js";
import { fitHeadline } from "./fit.js";

const KEY = "view";
const root = document.documentElement;
const params = new URLSearchParams(location.search);
const locked = params.has("kiosk");
const lang = pickLang(navigator.languages);

let stored = null;
try {
  const value = localStorage.getItem(KEY);
  stored = value === "big" || value === "detailed" ? value : null;
} catch { /* storage can be blocked */ }

const button = document.getElementById("view-toggle");

function setView(view) {
  root.dataset.view = view;
  root.classList.toggle("kiosk", view === "big");
  // The visible text is the accessible name (F3, WCAG 2.5.3): it says where
  // a click goes, "Details" / "Big view" (de "Details" / "Große Ansicht").
  button.textContent = t(lang, view === "big" ? "view.to-detailed" : "view.to-big");
  /* F4: switching views changes the headline's width (and the kiosk
   * class), so refit the big view's text-fitted size (or remove it). */
  fitHeadline(document.getElementById("rain-answer"));
}

setView(locked ? "big" : params.has("detailed") ? "detailed" : stored || "big");
root.classList.toggle("locked", locked);
button.addEventListener("click", () => {
  const next = root.dataset.view === "big" ? "detailed" : "big";
  setView(next);
  try {
    localStorage.setItem(KEY, next);
  } catch { /* ignore */ }
});
