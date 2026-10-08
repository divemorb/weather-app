/* report.js — the "Not right?" flip tile: W1a, the picker.
 *
 * The host is found by the data-report-host attribute (never by an id), so
 * the tile keeps working when the attribute moves to another card. The
 * button on the front corner, the back and its picker all live inside the
 * host; nothing here names #now or the Now tile.
 *
 * W1a only: the flip, the picker and the open/close state. Saving
 * (W1b), the sky following a fresh report (W2) and the Details table
 * (W3) build on this module. No network here yet: nothing is saved while
 * the back is open, and closing keeps the page exactly as it was.
 */
import { KINDS, sceneKind } from "./reportkind.js";
import { t } from "./i18n.js";

let host = null;
let back = null;
let backInner = null;
let openBtn = null;
let closeBtn = null;
let showsEl = null;
let confirmBtn = null;
let kindBtns = [];
let whenBtns = [];
let lang = null;
let isOpen = false;

/* The eight kind pictures: inline SVG (no image files), drawn with
 * currentColor so they follow the text colour of the theme. */
function svg(inner) {
  return '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false"'
    + ' fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"'
    + ' stroke-linejoin="round">' + inner + "</svg>";
}

const CLOUD = '<path d="M6.8 17.5h9.7a3.6 3.6 0 0 0 .7-7.14A5.1 5.1 0 0 0 7.1 9.3 3.6 3.6 0 0 0 6.8 17.5z"/>';
const KIND_ICON = {
  clear: '<circle cx="12" cy="12" r="4"/>'
    + '<path d="M12 2.5v2.6M12 18.9v2.6M2.5 12h2.6M18.9 12h2.6M5.2 5.2l1.9 1.9M16.9 16.9l1.9 1.9M18.8 5.2l-1.9 1.9M7.1 16.9l-1.9 1.9"/>',
  "partly-cloudy": '<circle cx="8" cy="7.5" r="3"/>'
    + '<path d="M8 1.8v1.7M2.3 7.5h1.7M3.9 3.4l1.2 1.2M12.1 3.4 10.9 4.6"/>'
    + '<path d="M8 18.5h8.6a3.2 3.2 0 0 0 .6-6.35A4.6 4.6 0 0 0 8.2 10.4 3.2 3.2 0 0 0 8 18.5z"/>',
  cloudy: CLOUD,
  fog: '<path d="M6.8 14.5h9.7a3.6 3.6 0 0 0 .7-7.14A5.1 5.1 0 0 0 7.1 6.3 3.6 3.6 0 0 0 6.8 14.5z"/>'
    + '<path d="M5.5 18h13M8 21h10"/>',
  rain: CLOUD
    + '<path d="M8.5 19.5 7.5 22M12.5 19.5l-1 2.5M16.5 19.5l-1 2.5"/>',
  thunderstorm: CLOUD
    + '<path d="M12.8 15.5 10 20h2.6l-1.4 4 4.2-5.5h-2.8z"/>',
  snow: CLOUD
    + '<path d="M8.5 20.2h.01M12.5 21.5h.01M16.5 20.2h.01" stroke-width="2.4"/>',
  hail: CLOUD
    + '<rect x="7.4" y="19.4" width="2" height="2" rx="0.5" fill="currentColor" stroke="none"/>'
    + '<rect x="11.5" y="20.4" width="2" height="2" rx="0.5" fill="currentColor" stroke="none"/>'
    + '<rect x="15.4" y="19.4" width="2" height="2" rx="0.5" fill="currentColor" stroke="none"/>',
};
const OPEN_ICON = '<path d="M20 12a8 8 0 1 1-2.4-5.7"/>' + '<path d="M20 3.5v4.8h-4.8"/>';
const CLOSE_ICON = '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>';

function makeBtn(cls, hook, label, icon, extra) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = cls;
  b.dataset.test = hook;
  if (extra) Object.assign(b.dataset, extra);
  if (icon) b.innerHTML = svg(icon);
  if (label != null) {
    if (icon) {
      b.setAttribute("aria-label", label);
    } else {
      b.textContent = label;
    }
  }
  return b;
}

function build() {
  openBtn = makeBtn("report-open-btn", "report-open", t(lang, "report.open"), OPEN_ICON);
  openBtn.addEventListener("click", open);

  back = document.createElement("div");
  back.className = "report-back";
  back.dataset.test = "report-back";
  back.setAttribute("role", "dialog");
  back.setAttribute("aria-modal", "true");
  back.setAttribute("aria-labelledby", "report-title-el");
  back.inert = true;

  backInner = document.createElement("div");
  backInner.className = "report-back-inner";

  const titleRow = document.createElement("div");
  titleRow.className = "report-row report-title-row";
  const titleEl = document.createElement("span");
  titleEl.className = "report-title";
  titleEl.id = "report-title-el";
  titleEl.dataset.test = "report-title";
  titleEl.textContent = t(lang, "report.title");
  closeBtn = makeBtn("report-icon-btn", "report-close", t(lang, "report.close"), CLOSE_ICON);
  closeBtn.addEventListener("click", close);
  titleRow.append(titleEl, closeBtn);

  const showsRow = document.createElement("div");
  showsRow.className = "report-row report-shows-row";
  showsEl = document.createElement("span");
  showsEl.className = "report-shows";
  showsEl.dataset.test = "report-shows";
  confirmBtn = makeBtn("report-confirm", "report-confirm", t(lang, "report.confirm"), null);
  showsRow.append(showsEl, confirmBtn);

  const kindsEl = document.createElement("div");
  kindsEl.className = "report-kinds";
  kindBtns = KINDS.map((kind) => {
    const b = makeBtn("report-kind", "report-kind", t(lang, "report.kind." + kind), KIND_ICON[kind], {
      kind: kind,
    });
    const labelEl = document.createElement("span");
    labelEl.className = "report-kind-label";
    labelEl.textContent = t(lang, "report.kind." + kind);
    b.append(labelEl);
    kindsEl.append(b);
    return b;
  });

  const whenEl = document.createElement("div");
  whenEl.className = "report-whens";
  whenBtns = ["0", "15", "30"].map((m) => {
    const b = makeBtn("report-when", "report-when", t(lang, "report.when." + m), null, {
      minutes: m,
    });
    b.setAttribute("aria-pressed", m === "0" ? "true" : "false");
    b.addEventListener("click", () => {
      for (const w of whenBtns) w.setAttribute("aria-pressed", w.dataset.minutes === m ? "true" : "false");
    });
    whenEl.append(b);
    return b;
  });

  backInner.append(titleRow, showsRow, kindsEl, whenEl);
  back.append(backInner);
  host.append(openBtn, back);
}

/* The back's texts follow the current scene: what the page shows, the
 * kind it names (aria-current, and the "That's right" button) and a fresh
 * "now" chip. */
function syncBack() {
  const scene = document.documentElement.dataset.scene;
  showsEl.textContent = t(lang, "report.shows", { scene: t(lang, "sky.scene." + scene) });
  const sk = sceneKind(scene);
  confirmBtn.hidden = !sk;
  for (const b of kindBtns) {
    if (sk && b.dataset.kind === sk.kind) b.setAttribute("aria-current", "true");
    else b.removeAttribute("aria-current");
  }
  for (const w of whenBtns) w.setAttribute("aria-pressed", w.dataset.minutes === "0" ? "true" : "false");
}

function frontParts() {
  return [...host.querySelectorAll("[data-test]")].filter((el) => el !== back && !back.contains(el));
}

function open() {
  if (isOpen) return;
  isOpen = true;
  syncBack();
  back.inert = false;
  for (const el of frontParts()) el.inert = true;
  host.classList.add("report-open");
  void backInner.offsetWidth; // start the turn immediately, in this tick
  closeBtn.focus();
}

function close() {
  if (!isOpen) return;
  isOpen = false;
  host.classList.remove("report-open");
  for (const el of frontParts()) el.inert = false;
  back.inert = true;
  openBtn.focus();
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && isOpen) close();
});

export function initReport(l) {
  lang = l;
  host = document.querySelector("[data-report-host]");
  if (host) build();
  /* The attribute may move to another card (the glance) while the page
   * runs: rebind the button and the back to the new host. */
  new MutationObserver(() => {
    const h = document.querySelector("[data-report-host]");
    if (h === host) return;
    if (host && openBtn) {
      openBtn.remove();
      back.remove();
      isOpen = false;
    }
    host = h;
    if (host) build();
  }).observe(document.documentElement, {
    subtree: true,
    attributes: true,
    attributeFilter: ["data-report-host"],
  });
}

/* app.js calls this after every setSkyScene (and the sky follows a fresh
 * report, W2): the open back keeps naming the scene the page shows. */
export function reportScene() {
  if (host && isOpen) syncBack();
}
