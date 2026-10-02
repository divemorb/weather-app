/* glance.js — the glance: the rain answer for the next hour and the
 * 60-minute radar strip (steps W2/W4).
 *
 * Rendered from /api/rain-probability and /api/radar/next-hour. The texts
 * come from rainAnswer()/fmtPercent() (format.js); without data
 * (weights_used empty, probability_pct then a meaningless 0) the
 * probability shows no number. The strip (W4): one visible column per
 * five-minute step (a track with a fill inside, the height the amount
 * relative to max(1.0 mm, the largest step)), the axis labels (the first
 * step, two in between, the end of the hour) and the caption with the
 * radar radius from /api/config. When every step is dry the tracks stay
 * (faint) and the "dry" line shows; when it rains, the max amount sits
 * above the first column with that amount. Without a radar the strip
 * gives way to the "not available" line.
 */
import { DASH, fmtMm, fmtNumber, fmtPercent, fmtTime, rainAnswer } from "./format.js";
import { t } from "./i18n.js";

const els = {
  answer: document.getElementById("rain-answer"),
  when: document.getElementById("rain-when"),
  prob: document.getElementById("rain-probability"),
  unavailable: document.getElementById("radar-unavailable"),
  visual: document.getElementById("radar-visual"),
  max: document.getElementById("radar-max"),
  dry: document.getElementById("radar-dry"),
  strip: document.getElementById("radar-strip"),
  labels: document.getElementById("radar-labels"),
  caption: document.getElementById("radar-caption"),
};

/* The strip's scale: the tallest fill reaches 100% at at least this many
 * millimetres, so 0.2 mm is a short but visible fill. */
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
    /* no data: the placeholder stays neutral, the accent means rain */
    els.prob.textContent = DASH;
    els.prob.classList.add("muted");
  }
  renderRadar(radar, lang, locale, tz, radiusKm, a.detail);
}

/* The 60-minute strip and its surroundings; called on every refresh. */
function renderRadar(radar, lang, locale, tz, radiusKm, detail) {
  const steps = radar && Array.isArray(radar.steps) ? radar.steps : [];
  if (!radar || !radar.available || steps.length === 0) {
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

  /* The columns: one per step, the track stays visible when dry. */
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

  /* The axis: the first step, two in between, the end of the hour. */
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

  /* Dry: the line over the (empty) tracks. Rain: the max amount above
   * the first column with that amount, so the height means something. */
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

  /* The caption: one line under the strip, the radius from /api/config. */
  const km = fmtNumber(radiusKm, locale, Number.isInteger(radiusKm) ? 0 : 1);
  els.caption.hidden = false;
  els.caption.textContent = t(lang, "radar.caption", { km });
}
