/* glance.js — the glance: the rain answer for the next hour (steps W2/W4).
 *
 * Rendered from /api/rain-probability and /api/radar/next-hour. The texts
 * come from rainAnswer()/fmtPercent() (format.js); without data
 * (weights_used empty, probability_pct then a meaningless 0) the
 * probability shows no number. #radar-strip gets the 60-minute strip in W4.
 */
import { DASH, fmtPercent, rainAnswer } from "./format.js";

const els = {
  answer: document.getElementById("rain-answer"),
  when: document.getElementById("rain-when"),
  prob: document.getElementById("rain-probability"),
};

export function renderGlance(rain, radar, lang, locale, tz) {
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
}
