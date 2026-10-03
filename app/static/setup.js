/* setup.js — the location wizard.
 *
 * initSetup({lang, isConfigured, onSaved}) fills the (empty) <section
 * data-test="setup"> markup and remembers the callback for a saved
 * location; openSetup("first"|"change") shows the wizard (first hides
 * <main>). Every text lives in i18n.js, so index.html stays
 * language-neutral.
 *
 * No <form> on purpose: the CSP is form-action 'none', so all buttons
 * are type="button" and Enter in the search field triggers the search.
 */
import { t } from "./i18n.js";
import { ApiError, getJSON, postJSON } from "./api.js";

const els = {
  section: document.getElementById("setup"),
  locationBtn: document.getElementById("location-btn"),
  title: document.getElementById("setup-title"),
  intro: document.getElementById("setup-intro"),
  searchLabel: document.getElementById("setup-search-label"),
  search: document.getElementById("setup-search"),
  searchBtn: document.getElementById("setup-search-btn"),
  results: document.getElementById("setup-results"),
  divider: document.getElementById("setup-divider"),
  latLabel: document.getElementById("setup-lat-label"),
  lonLabel: document.getElementById("setup-lon-label"),
  tzLabel: document.getElementById("setup-tz-label"),
  lat: document.getElementById("setup-lat"),
  lon: document.getElementById("setup-lon"),
  tz: document.getElementById("setup-tz"),
  save: document.getElementById("setup-save"),
  cancel: document.getElementById("setup-cancel"),
  status: document.getElementById("setup-status"),
  note: document.getElementById("setup-note"),
  main: document.getElementById("dashboard"),
};

let lang = "en";
let isConfigured = () => true;
let onSaved = () => {};
let mode = "first"; // "first" = no location yet, "change" = opened via the button
let pickedLabel = ""; // display label of the picked search result

function status(text, isError) {
  els.status.textContent = text || "";
  els.status.classList.toggle("error", !!isError);
}

function browserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
}

/* ---- open / close ---- */
export function openSetup(m) {
  mode = m;
  pickedLabel = "";
  clearResults();
  status("");
  els.cancel.hidden = m !== "change";
  if (m === "first") els.main.hidden = true;
  if (!els.tz.value) els.tz.value = browserTimezone();
  els.section.hidden = false;
  els.search.focus();
}

function closeSetup() {
  els.section.hidden = true;
  status("");
}

/* ---- wiring (called once from app.js) ---- */
export function initSetup(opts) {
  lang = opts.lang || "en";
  isConfigured = opts.isConfigured || (() => true);
  onSaved = opts.onSaved || (() => {});
  els.title.textContent = t(lang, "setup.title");
  els.intro.textContent = t(lang, "setup.intro");
  els.searchLabel.textContent = t(lang, "setup.search-label");
  els.search.placeholder = t(lang, "setup.search-placeholder");
  els.searchBtn.textContent = t(lang, "setup.search-btn");
  els.divider.textContent = t(lang, "setup.divider");
  els.latLabel.textContent = t(lang, "setup.lat");
  els.lonLabel.textContent = t(lang, "setup.lon");
  els.tzLabel.textContent = t(lang, "setup.tz");
  /* The placeholders keep the dot as decimal point: the fields are parsed
   * with Number(), so a German "48,137" would not be accepted. */
  els.lat.placeholder = t(lang, "setup.lat-placeholder");
  els.lon.placeholder = t(lang, "setup.lon-placeholder");
  els.tz.placeholder = t(lang, "setup.tz-placeholder");
  els.save.textContent = t(lang, "setup.save");
  els.cancel.textContent = t(lang, "setup.cancel");
  els.note.textContent = t(lang, "setup.note");
  els.locationBtn.addEventListener("click", () =>
    openSetup(isConfigured() ? "change" : "first")
  );
  els.searchBtn.addEventListener("click", doSearch);
  els.search.addEventListener("keydown", (e) => {
    if (e.key === "Enter") doSearch();
  });
  els.lat.addEventListener("input", () => onCoordInput(els.lat, els.lon));
  els.lon.addEventListener("input", () => onCoordInput(els.lon, els.lat));
  els.save.addEventListener("click", doSave);
  els.cancel.addEventListener("click", closeSetup);
}

/* ---- address search ---- */
function clearResults() {
  els.results.hidden = true;
  els.results.innerHTML = "";
}

async function doSearch() {
  const text = els.search.value.trim();
  if (text.length < 3) {
    status(t(lang, "setup.status.min-length"), true);
    return;
  }
  pickedLabel = "";
  clearResults();
  status(t(lang, "setup.status.searching"));
  try {
    const data = await getJSON(`/api/geocode?q=${encodeURIComponent(text)}`);
    renderResults(data.results || []);
  } catch {
    status(t(lang, "setup.status.search-failed"), true);
  }
}

function pickResult(r, btn) {
  els.lat.value = r.latitude;
  els.lon.value = r.longitude;
  pickedLabel = r.label;
  for (const b of els.results.querySelectorAll(".setup-result")) {
    const isPicked = b === btn;
    b.classList.toggle("selected", isPicked);
    b.setAttribute("aria-pressed", isPicked ? "true" : "false");
  }
  status(t(lang, "setup.status.selected", { label: r.label }));
}

function renderResults(results) {
  if (results.length === 0) {
    status(t(lang, "setup.status.no-match"), true);
    return;
  }
  status("");
  els.results.hidden = false;
  const buttons = [];
  for (const r of results) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "setup-result";
    btn.setAttribute("data-test", "setup-result");
    btn.textContent = r.label;
    btn.title = r.label;
    btn.setAttribute("aria-pressed", "false");
    btn.addEventListener("click", () => pickResult(r, btn));
    li.appendChild(btn);
    els.results.appendChild(li);
    buttons.push(btn);
  }
  if (buttons.length === 1) {
    pickResult(results[0], buttons[0]);
  } else {
    status(t(lang, "setup.status.click-result"));
  }
}

/* ---- coordinates ("48.137, 11.575" pasted into either field is split) ---- */
function onCoordInput(self, other) {
  const m = self.value.trim().match(/^(-?\d+(?:\.\d+)?)[,\s]+(-?\d+(?:\.\d+)?)$/);
  if (m) {
    self.value = m[1];
    other.value = m[2];
  }
  pickedLabel = ""; // manual coordinates override a picked search result
}

/* ---- save ---- */
async function doSave() {
  const latRaw = els.lat.value.trim();
  const lonRaw = els.lon.value.trim();
  const tzName = els.tz.value.trim();
  if (!latRaw && !lonRaw) {
    status(
      els.results.hidden
        ? t(lang, "setup.status.need-input")
        : t(lang, "setup.status.need-result"),
      true
    );
    return;
  }
  const lat = Number(latRaw);
  const lon = Number(lonRaw);
  if (!latRaw || !Number.isFinite(lat) || lat < -90 || lat > 90) {
    status(t(lang, "setup.status.lat-range"), true);
    return;
  }
  if (!lonRaw || !Number.isFinite(lon) || lon < -180 || lon > 180) {
    status(t(lang, "setup.status.lon-range"), true);
    return;
  }
  if (!tzName) {
    status(t(lang, "setup.status.tz-required"), true);
    return;
  }
  if (
    mode === "change" &&
    !confirm(t(lang, "setup.confirm-change"))
  ) {
    return;
  }
  status(t(lang, "setup.status.saving"));
  try {
    const data = await postJSON("/api/location", {
      latitude: lat,
      longitude: lon,
      timezone: tzName,
      label: pickedLabel,
    });
    closeSetup();
    els.main.hidden = false;
    onSaved(data.location || null);
  } catch (e) {
    if (e instanceof ApiError && e.status === 422) {
      const first = Array.isArray(e.detail) && e.detail[0];
      status((first && first.msg) || t(lang, "setup.status.rejected"), true);
      return;
    }
    status(t(lang, "setup.status.save-failed"), true);
  }
}
