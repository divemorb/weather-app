/* Setup wizard (step 8d): the home location is picked in the browser.
 *
 * Loaded before app.js via a <script> tag; exposes the functions
 * openSetup(mode), closeSetup(), doSearch(), doSave() and the wizard
 * state (setupMode, pickedLabel). Markup: <section id="setup"> in
 * index.html, styles: style.css (".setup").
 *
 * Only its own names may be used at load time (this script runs before
 * app.js); the shared helpers from app.js (getJSON, cfg,
 * onLocationSaved) are used at call time.
 *
 * No <form> on purpose: the CSP is form-action 'none', so all buttons
 * are type="button" and Enter in the search field triggers the search
 * via a keydown listener.
 */
"use strict";

/* Element handles (end-of-body script: the DOM is already parsed). */
const setupEls = {
  section: document.getElementById("setup"),
  locationBtn: document.getElementById("location-btn"),
  search: document.getElementById("setup-search"),
  searchBtn: document.getElementById("setup-search-btn"),
  results: document.getElementById("setup-results"),
  lat: document.getElementById("setup-lat"),
  lon: document.getElementById("setup-lon"),
  tz: document.getElementById("setup-tz"),
  save: document.getElementById("setup-save"),
  cancel: document.getElementById("setup-cancel"),
  status: document.getElementById("setup-status"),
};

let setupMode = "first"; // "first" = no location yet, "change" = opened via 📍
let pickedLabel = ""; // display label of the picked search result

function setupStatus(text, isError) {
  setupEls.status.textContent = text || "";
  setupEls.status.classList.toggle("error", !!isError);
}

function browserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch (_) {
    return "";
  }
}

/* ---- open / close ---- */
function openSetup(mode) {
  setupMode = mode;
  pickedLabel = "";
  clearResults();
  setupStatus("");
  setupEls.cancel.hidden = mode !== "change";
  if (!setupEls.tz.value) setupEls.tz.value = browserTimezone();
  setupEls.section.hidden = false;
  setupEls.search.focus();
}

function closeSetup() {
  setupEls.section.hidden = true;
  setupStatus("");
}

/* ---- address search ---- */
function clearResults() {
  setupEls.results.hidden = true;
  setupEls.results.innerHTML = "";
}

async function doSearch() {
  const text = setupEls.search.value.trim();
  if (text.length < 3) {
    setupStatus("Type at least 3 characters to search.", true);
    return;
  }
  pickedLabel = "";
  clearResults();
  setupStatus("Searching…");
  try {
    const data = await getJSON(`/api/geocode?q=${encodeURIComponent(text)}`);
    renderResults(data.results || []);
  } catch (e) {
    console.error(e);
    setupStatus("Address search failed — try again, or enter the coordinates directly.", true);
  }
}

function renderResults(results) {
  if (results.length === 0) {
    setupStatus("No match — try a more specific address, or enter coordinates.", true);
    return;
  }
  setupStatus("");
  setupEls.results.hidden = false;
  for (const r of results) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "setup-result";
    btn.textContent = r.label;
    btn.title = r.label;
    btn.addEventListener("click", () => {
      setupEls.lat.value = r.latitude;
      setupEls.lon.value = r.longitude;
      pickedLabel = r.label;
      setupStatus("Selected — review the coordinates, then press “Save location”.");
    });
    li.appendChild(btn);
    setupEls.results.appendChild(li);
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
  const latRaw = setupEls.lat.value.trim();
  const lonRaw = setupEls.lon.value.trim();
  const tzName = setupEls.tz.value.trim();
  const lat = Number(latRaw);
  const lon = Number(lonRaw);
  if (!latRaw || !Number.isFinite(lat) || lat < -90 || lat > 90) {
    setupStatus("Latitude must be a number between -90 and 90.", true);
    return;
  }
  if (!lonRaw || !Number.isFinite(lon) || lon < -180 || lon > 180) {
    setupStatus("Longitude must be a number between -180 and 180.", true);
    return;
  }
  if (!tzName) {
    setupStatus("Timezone is required (e.g. Europe/Berlin).", true);
    return;
  }
  if (
    setupMode === "change" &&
    !confirm("Changing the location deletes the cached data and the model-accuracy history. Continue?")
  ) {
    return;
  }
  setupStatus("Saving…");
  try {
    const res = await fetch("/api/location", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ latitude: lat, longitude: lon, timezone: tzName, label: pickedLabel }),
    });
    if (res.status === 422) {
      const data = await res.json().catch(() => null);
      const first = data && Array.isArray(data.detail) && data.detail[0];
      setupStatus((first && first.msg) || "The location was rejected — check the values.", true);
      return;
    }
    if (!res.ok) throw new Error(`/api/location -> ${res.status}`);
    const data = await res.json();
    closeSetup();
    onLocationSaved(data.location || null);
  } catch (e) {
    console.error(e);
    setupStatus("Could not save the location — try again.", true);
  }
}

/* ---- boot wiring (listeners only; app.js helpers are used at call time) ---- */
setupEls.locationBtn.addEventListener("click", () => {
  // While nothing is stored yet the wizard stays in "first" mode (no confirm).
  openSetup(cfg && cfg.configured === false ? "first" : "change");
});
setupEls.searchBtn.addEventListener("click", doSearch);
setupEls.search.addEventListener("keydown", (e) => {
  if (e.key === "Enter") doSearch();
});
setupEls.lat.addEventListener("input", () => onCoordInput(setupEls.lat, setupEls.lon));
setupEls.lon.addEventListener("input", () => onCoordInput(setupEls.lon, setupEls.lat));
setupEls.save.addEventListener("click", doSave);
setupEls.cancel.addEventListener("click", closeSetup);
