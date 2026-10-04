/* glance.js — the rain answer for the next hour and the 60-minute
 * radar strip, rendered from /api/rain-probability and
 * /api/radar/next-hour.
 *
 * Without data (weights_used empty) the probability shows no number: a 0
 * would be meaningless. A broken step (not an object with a parsable
 * start_utc) or no radar shows the "unavailable" line instead of the
 * strip.
 */
import { DASH, fmtMm, fmtNumber, fmtPercent, fmtTime, rainAnswer, sceneReason } from "./format.js";
import { t } from "./i18n.js";

const els = {
  answer: document.getElementById("rain-answer"),
  when: document.getElementById("rain-when"),
  reason: document.getElementById("sky-reason"),
  prob: document.getElementById("rain-probability"),
  unavailable: document.getElementById("radar-unavailable"),
  visual: document.getElementById("radar-visual"),
  max: document.getElementById("radar-max"),
  dry: document.getElementById("radar-dry"),
  strip: document.getElementById("radar-strip"),
  labels: document.getElementById("radar-labels"),
  caption: document.getElementById("radar-caption"),
};

/* Minimum strip scale in mm, so small amounts still get a visible fill. */
const RADAR_MAX_MM = 1.0;

export function renderGlance(rain, radar, lang, locale, tz, radiusKm) {
  const a = rainAnswer(rain, radar, lang, locale, tz);
  els.answer.textContent = a.headline;
  if (a.detail) {
    els.when.textContent = a.detail;
    els.when.hidden = false;
  } else {
    els.when.textContent = "";
    els.when.hidden = true;
  }
  const weights = rain && rain.weights_used;
  if (weights && Object.keys(weights).length > 0) {
    els.prob.textContent = fmtPercent(rain.probability_pct, locale);
    els.prob.classList.remove("muted");
  } else {
    /* no data: the dash stays neutral, since the accent color means rain */
    els.prob.textContent = DASH;
    els.prob.classList.add("muted");
  }
  renderRadar(radar, lang, locale, tz, radiusKm, a.detail);
}

/* The "why" line under the rain answer (step B1): what the sky shows and
 * which source decided it (sceneReason). Hidden when the source is "none"
 * (nothing to show). {km} like the Now card's station line; station names
 * are untrusted API text: textContent only. */
export function renderSkyReason(now, radar, lang, locale) {
  const r = sceneReason(now, radar);
  if (r.source === "none") {
    els.reason.hidden = true;
    els.reason.textContent = "";
    return;
  }
  const c = now && now.available && now.conditions ? now.conditions : null;
  const st = c && c.station && typeof c.station === "object" ? c.station : null;
  const listed = !!(st && typeof st.name === "string" && st.name !== "");
  const name = listed ? st.name : "";
  const km = listed && typeof st.distance_m === "number" ? `${fmtNumber(st.distance_m / 1000, locale, 1)} km` : DASH;
  const label = (s) => t(lang, "sky.scene." + s);
  let text;
  if (r.source === "radar") {
    if (r.radarDry && listed) {
      text = t(lang, "sky.radar-dry", { name, km, station: label(r.stationIcon) });
    } else {
      text = t(lang, "sky.radar", { scene: label(r.scene) });
    }
  } else if (r.radarDry && r.stationIcon === "thunderstorm" && listed) {
    text = t(lang, "sky.station-radar-dry", { scene: label(r.scene), name, km });
  } else if (listed) {
    text = t(lang, "sky.station", { scene: label(r.scene), name, km });
  } else {
    text = t(lang, "sky.nearest", { scene: label(r.scene) });
  }
  els.reason.textContent = text;
  els.reason.hidden = false;
}

function renderRadar(radar, lang, locale, tz, radiusKm, detail) {
  const steps = radar && Array.isArray(radar.steps) ? radar.steps : [];
  /* A step that is not an object with a parsable start_utc makes the
   * whole strip undrawable: the unavailable line, like without a radar. */
  const sound = steps.length > 0 && steps.every(
    (s) => s && typeof s === "object" && typeof s.start_utc === "string" && !isNaN(Date.parse(s.start_utc)));
  if (!radar || !radar.available || !sound) {
    els.visual.hidden = true;
    els.unavailable.hidden = false;
    els.unavailable.textContent = t(lang, "radar.unavailable");
    return;
  }
  els.unavailable.hidden = true;
  els.unavailable.textContent = "";
  els.visual.hidden = false;

  const mm = steps.map((s) => (s && typeof s.precip_mm === "number" ? s.precip_mm : 0));
  const peak = Math.max(0, ...mm);
  const scale = Math.max(RADAR_MAX_MM, peak);
  const times = steps.map((s) => fmtTime(s && s.start_utc, locale, tz));
  const endMs = Date.parse(steps[steps.length - 1].start_utc) + 5 * 60 * 1000;
  const endIso = isNaN(endMs) ? null : new Date(endMs).toISOString();

  /* One column per step; the track stays visible when dry. */
  els.strip.textContent = "";
  const frag = document.createDocumentFragment();
  for (let i = 0; i < steps.length; i++) {
    const col = document.createElement("div");
    col.className = "radar-col" + (mm[i] > 0 ? " is-rain" : "");
    col.dataset.test = "radar-step";
    col.dataset.rain = mm[i] > 0 ? "1" : "0";
    col.setAttribute("aria-label", `${times[i]} · ${fmtMm(mm[i], locale)}`);
    const fill = document.createElement("div");
    fill.className = "radar-fill";
    fill.style.height = `${((mm[i] / scale) * 100).toFixed(2)}%`;
    col.appendChild(fill);
    frag.appendChild(col);
  }
  els.strip.appendChild(frag);
  els.strip.setAttribute("aria-label", detail || t(lang, "radar.dry"));

  els.labels.textContent = "";
  const at = (i) => Math.min(i, steps.length - 1);
  const labelAts = [
    ["rl-a", times[at(0)]],
    ["rl-b", times[at(4)]],
    ["rl-c", times[at(8)]],
    ["rl-d", endIso ? fmtTime(endIso, locale, tz) : times[at(11)]],
  ];
  for (const [cls, text] of labelAts) {
    const el = document.createElement("span");
    el.className = `radar-label ${cls}`;
    el.dataset.test = "radar-label";
    el.textContent = text;
    els.labels.appendChild(el);
  }

  /* The max amount sits above its first column, so the height stays
   * meaningful. */
  if (peak > 0) {
    els.dry.hidden = true;
    els.dry.textContent = "";
    els.max.hidden = false;
    els.max.textContent = fmtMm(peak, locale);
    const first = mm.indexOf(peak);
    const frac = Math.min(0.95, Math.max(0.05, (first + 0.5) / steps.length));
    els.max.style.left = `${(frac * 100).toFixed(2)}%`;
  } else {
    els.max.hidden = true;
    els.max.textContent = "";
    els.dry.hidden = false;
    els.dry.textContent = t(lang, "radar.dry");
  }

  const km = fmtNumber(radiusKm, locale, Number.isInteger(radiusKm) ? 0 : 1);
  els.caption.hidden = false;
  els.caption.textContent = t(lang, "radar.caption", { km });
}
