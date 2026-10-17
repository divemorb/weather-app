/* report.js — the "Not right?" flip tile: the picker, saving (a kind tap
 * POSTs /api/reports; rain first asks for its intensity; a failure keeps
 * the back open with its message; the front's line carries the undo), and
 * the sky and its "why" line follow the fresh report. The host is found by its data-report-host attribute (never by an id). */
import { KINDS, kindScene, sceneKind, isDayAt } from "./reportkind.js";
import { t } from "./i18n.js";
import { fmtTime } from "./format.js";
import { getJSON, postJSON, deleteJSON } from "./api.js";

let host = null, back = null, backInner = null, openBtn = null, closeBtn = null;
let showsEl = null, confirmBtn = null, kindBtns = [], whenBtns = [];
let kindsEl = null, intensityEl = null, errorEl = null;
let lineWrap = null, lineEl = null, lineUndoBtn = null;
let lang = null;
let locale = "en";
let tz = "UTC";
let location = null; // /api/config's location (app.js), for day/night
let isOpen = false;
let saving = false;
let currentReport = null;

/* app.js listens: after a save or undo the sky and "why" line follow. */
function notifyReportChanged() {
  document.dispatchEvent(new Event("report-changed"));
}

/* The eight kind pictures: inline SVG, currentColor (follows the theme). */
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
/* A slanted pencil, tip at the bottom left. */
const OPEN_ICON = '<path d="M4 20l1-4L16 5l3 3L8 19z"/>' + '<path d="M14 7l3 3"/>';
const CLOSE_ICON = '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>';

// a button with the given class, data-test hook, label and icon (aria-label when both)
function makeBtn(cls, hook, label, icon, extra) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = cls;
  b.dataset.test = hook;
  if (extra) Object.assign(b.dataset, extra);
  if (icon) b.innerHTML = svg(icon);
  if (label != null) (icon ? b.setAttribute("aria-label", label) : (b.textContent = label));
  return b;
}

// builds the back (its parts) once, per host
function build() {
  /* The visible word is the accessible name (WCAG 2.5.3); the SVG is aria-hidden. */
  openBtn = makeBtn("report-open-btn", "report-open", null, OPEN_ICON);
  const openWord = document.createElement("span");
  openWord.textContent = t(lang, "report.open");
  openBtn.appendChild(openWord);
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
  confirmBtn.addEventListener("click", () => {
    const sk = sceneKind(document.documentElement.dataset.scene);
    if (sk) save({ kind: sk.kind, intensity: sk.intensity, minutes: selectedMinutes(), confirms: true });
  });
  showsRow.append(showsEl, confirmBtn);

  kindsEl = document.createElement("div");
  kindsEl.className = "report-kinds";
  kindBtns = KINDS.map((kind) => {
    const b = makeBtn("report-kind", "report-kind", t(lang, "report.kind." + kind), KIND_ICON[kind], {
      kind: kind,
    });
    const labelEl = document.createElement("span");
    labelEl.className = "report-kind-label";
    labelEl.textContent = t(lang, "report.kind." + kind);
    b.addEventListener("click", () => onKind(kind));
    b.append(labelEl);
    kindsEl.append(b);
    return b;
  });

  /* Rain's intensity in the kinds' place; "Skip" saves rain without one. */
  intensityEl = document.createElement("div");
  intensityEl.className = "report-intensities";
  intensityEl.hidden = true;
  ["light", "moderate", "heavy"].forEach((intensity) => {
    const b = makeBtn("report-intensity", "report-intensity", t(lang, "report.intensity." + intensity), null, {
      intensity: intensity,
    });
    b.addEventListener("click", () => save({ kind: "rain", intensity: intensity, minutes: selectedMinutes(), confirms: false }));
    intensityEl.append(b);
  });
  const skipBtn = makeBtn("report-intensity-skip", "report-intensity-skip", t(lang, "report.skip"), null);
  skipBtn.addEventListener("click", () => save({ kind: "rain", intensity: null, minutes: selectedMinutes(), confirms: false }));
  intensityEl.append(skipBtn);

  errorEl = document.createElement("div");
  errorEl.className = "report-error";
  errorEl.dataset.test = "report-error";
  errorEl.setAttribute("role", "alert");
  errorEl.hidden = true;

  /* The front's line for the current fresh report: the pill holds the sentence exactly and, beside it, the undo. */
  lineWrap = document.createElement("div");
  lineWrap.className = "report-line";
  lineWrap.hidden = true;
  lineEl = document.createElement("span");
  lineEl.className = "report-line-text";
  lineEl.dataset.test = "report-line";
  lineUndoBtn = makeBtn("report-undo-btn", "report-undo", t(lang, "report.undo"), null);
  lineUndoBtn.addEventListener("click", undo);
  lineWrap.append(lineEl, lineUndoBtn);

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

  backInner.append(titleRow, showsRow, kindsEl, intensityEl, errorEl, whenEl);
  back.append(backInner);
  host.append(openBtn, lineWrap, back);
}

/* The back's texts follow the current scene (what the page shows, the matching kind, a fresh "now" chip); opening starts on the kinds. */
function syncBack() {
  const scene = document.documentElement.dataset.scene;
  showsEl.textContent = t(lang, "report.shows", { scene: t(lang, "sky.scene." + scene) });
  const sk = sceneKind(scene);
  confirmBtn.hidden = !sk;
  hideError();
  showKinds();
  for (const w of whenBtns) w.setAttribute("aria-pressed", w.dataset.minutes === "0" ? "true" : "false");
}

// the host's front parts: everything but the back (the inert list)
function frontParts() {
  return [...host.querySelectorAll("[data-test]")].filter((el) => el !== back && !back.contains(el));
}

/* Saving. The time chip the user pressed: the report's minutes_ago. */
function selectedMinutes() {
  const m = whenBtns.find((w) => w.getAttribute("aria-pressed") === "true");
  return Number(m ? m.dataset.minutes : 0);
}

/* Rain asks for its intensity first; the other kinds save at once. */
function onKind(kind) {
  if (saving) return;
  if (kind === "rain") showIntensity();
  else save({ kind: kind, intensity: null, minutes: selectedMinutes(), confirms: false });
}

// the intensity step: the intensities instead of the kinds
function showIntensity() {
  kindsEl.hidden = true;
  intensityEl.hidden = false;
  for (const b of kindBtns) b.removeAttribute("aria-current");
}

// the kinds step: the kinds instead of the intensities (marks the scene's kind)
function showKinds() {
  intensityEl.hidden = true;
  kindsEl.hidden = false;
  const sk = sceneKind(document.documentElement.dataset.scene);
  for (const b of kindBtns) {
    if (sk && b.dataset.kind === sk.kind) b.setAttribute("aria-current", "true");
    else b.removeAttribute("aria-current");
  }
}

/* Save at once: POST with the pressed chip's minutes_ago; the server's clock sets the observed_at (the client sends no times). */
async function save({ kind, intensity, minutes, confirms }) {
  if (saving) return;
  saving = true;
  hideError();
  try {
    const body = { kind, minutes_ago: minutes, confirms };
    if (intensity) body.intensity = intensity;
    const res = await postJSON("/api/reports", body);
    if (res && res.report) currentReport = res.report;
    renderLine();
    close(); // the tile turns back
    notifyReportChanged();
  } catch (e) {
    console.warn(e); // a failed save keeps the back open, with its message
    showError();
  } finally {
    saving = false;
  }
}

// shows the failed-save message on the back
function showError() {
  errorEl.hidden = false;
  errorEl.textContent = t(lang, "report.failed");
}
// hides the failed-save message
function hideError() {
  errorEl.hidden = true;
}

/* The front's line: the scene's word (kindScene) and the server's observed_at in the user's zone. */
function renderLine() {
  if (!lineEl) return;
  const rep = currentReport;
  const scene = rep ? kindScene(rep.kind, rep.intensity, isDayAt(location, rep.observed_at)) : null;
  if (!scene) {
    lineWrap.hidden = true;
    return;
  }
  const key = rep.confirms ? "line-confirmed" : "line";
  lineEl.textContent = t(lang, "report." + key, {
    scene: t(lang, "sky.scene." + scene),
    time: fmtTime(rep.observed_at, locale, tz),
  });
  lineWrap.hidden = false;
}

/* Undo: delete, then re-read the current report (an older one may show). */
async function undo() {
  const rep = currentReport;
  if (!rep || saving) return;
  saving = true;
  try {
    await deleteJSON("/api/reports/" + rep.id);
  } catch (e) {
    console.warn(e); // a failed undo: the re-read below shows the truth
  }
  try {
    currentReport = null;
    renderLine();
    await reportCurrent(null, true); // an older fresh report may show again: the sky follows it
    notifyReportChanged();
  } finally {
    saving = false; // else no further save or undo until a reload
  }
}

/* The current fresh report (app.js passes the refresh's answer, the re-read after an undo fetches it itself); a failure counts as none. */
export async function reportCurrent(report, refetch) {
  if (refetch) {
    try {
      const res = await getJSON("/api/reports/current");
      report = res && res.report;
    } catch (e) {
      console.warn(e);
      report = null;
    }
  }
  currentReport = report;
  renderLine();
}

// turns the tile to the back: front inert, close button focused
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

// turns the tile to the front: back inert, open button focused
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

/* The sky follows a fresh report: its scene (kindScene) and the "why" line's
 * text (the "sky" / "sky-confirmed" string), or both null without a report. */
export function reportSky() {
  const rep = currentReport;
  if (!rep || !rep.kind || !rep.observed_at) return null;
  const scene = kindScene(rep.kind, rep.intensity, isDayAt(location, rep.observed_at));
  if (!scene) return null;
  const key = rep.confirms ? "sky-confirmed" : "sky";
  return {
    scene,
    text: t(lang, "report." + key, {
      scene: t(lang, "sky.scene." + scene),
      time: fmtTime(rep.observed_at, locale, tz),
    }),
  };
}

/* app.js calls once the config is known: the zone and coordinates. */
export function setReportEnv(locale_, tz_, location_) {
  locale = locale_;
  tz = tz_;
  location = location_;
  renderLine();
}

// wires the host (data-report-host) once the language is known
export function initReport(l) {
  lang = l;
  host = document.querySelector("[data-report-host]");
  if (host) build();
  /* The attribute may move to another card while the page runs: rebind. */
  new MutationObserver(() => {
    const h = document.querySelector("[data-report-host]");
    if (h === host) return;
    if (host && openBtn) {
      openBtn.remove();
      back.remove();
      if (lineWrap) lineWrap.remove();
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

/* app.js calls after every setSkyScene: the open back keeps naming the scene the page shows. */
export function reportScene() {
  if (host && isOpen) syncBack();
}
