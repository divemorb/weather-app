/* chart.js — the 24 h multi-model precipitation chart (step W6).
 *
 * renderChart() draws /api/models/24h as inline SVG (no external
 * libraries, no canvas): without any model data it shows the
 * "unavailable" line, a completely dry forecast the "dry" line, and
 * otherwise one line per model plus the legend. The y axis comes from
 * niceScale() (format.js) with mm/h as its unit; the hour labels and all
 * amounts use the browser's language and the location's time zone. A
 * model's line breaks at null values.
 *
 * The SVG's viewBox matches the container's pixel width, so the 12 px
 * axis labels stay 12 px on every screen (no scaled-down mush on a
 * phone). The module stays free of DOM access at the top level, so the
 * pure helpers can be unit-tested with node.
 */
import { fmtNumber, fmtTime, modelLabel, niceScale } from "./format.js";
import { t } from "./i18n.js";

/* Six series colours, each at least 3:1 against the light and the dark
 * card background (the WCAG bar for graphics, checked in
 * rust/uitest/unit/more/chart-w6.test.mjs). */
export const MODEL_COLORS = ["#1f6feb", "#2da44e", "#bf8700", "#cf222e", "#8250df", "#1b9aaa"];

const NS = "http://www.w3.org/2000/svg";

/* The chart's geometry for a container width in px: the viewBox matches
 * the width (clamped) so text is never scaled; a narrow container gets a
 * taller plot and a label every 6th hour instead of every 3rd; the kiosk
 * view gets a short, wide plot so the page fits one screen. */
export function chartMetrics(containerWidth, kiosk = false) {
  const w = Math.round(Math.max(300, Math.min(1800, containerWidth || 720)));
  const h = kiosk ? 100 : w < 520 ? 300 : 240;
  return { w, h, labelEvery: w < 520 && !kiosk ? 6 : 3 };
}

/* The data the chart can draw, or null when there is none at all
 * (available false, no hours, no models). */
export function chartData(data) {
  if (!data || data.available !== true) return null;
  const hours = Array.isArray(data.hours) ? data.hours : [];
  const models = Array.isArray(data.models) ? data.models : [];
  if (hours.length === 0 || models.length === 0) return null;
  return { hours, models };
}

function svgEl(tag, attrs) {
  const el = document.createElementNS(NS, tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

/* Draw the chart (or the dry/unavailable line) into the card's elements:
 * els = { body, legend, unavailable, dry, unit }. Called on every
 * refresh; it fully replaces what it drew before. */
export function renderChart(els, data, lang, locale, tz) {
  const d = chartData(data);
  let maxV = 0;
  if (d) {
    for (const m of d.models) {
      for (const v of m.precipitation_mm || []) {
        if (typeof v === "number" && Number.isFinite(v) && v > maxV) maxV = v;
      }
    }
  }

  els.body.textContent = "";
  els.legend.textContent = "";
  for (const el of [els.legend, els.unit, els.unavailable, els.dry]) el.hidden = true;

  if (!d) {
    els.unavailable.hidden = false;
    els.unavailable.textContent = t(lang, "chart.unavailable");
    return;
  }
  if (maxV <= 0) {
    els.dry.hidden = false;
    els.dry.textContent = t(lang, "chart.dry");
    return;
  }

  els.unit.hidden = false;
  els.unit.textContent = t(lang, "chart.unit");
  els.body.appendChild(buildSvg(els.body, d, maxV, lang, locale, tz));
  buildLegend(els.legend, d.models);
}

function buildSvg(body, { hours, models }, maxV, lang, locale, tz) {
  const kiosk = document.documentElement.classList.contains("kiosk");
  const { w, h, labelEvery } = chartMetrics(body.clientWidth, kiosk);
  const n = hours.length;
  const padL = 34, padR = 12, padT = 12, padB = 30;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  const scale = niceScale(maxV);
  const x = (i) => padL + (n <= 1 ? 0 : (i / (n - 1)) * plotW);
  const y = (v) => padT + plotH - (v / scale.max) * plotH;

  const svg = svgEl("svg", {
    "data-test": "chart",
    viewBox: `0 0 ${w} ${h}`,
    role: "img",
    "aria-label": t(lang, "chart.aria"),
    class: "chart-svg",
  });

  /* The grid lines and the y axis: exactly the niceScale ticks. */
  const digits = scale.step < 1 ? 1 : 0;
  for (const v of scale.ticks) {
    const yy = y(v);
    svg.appendChild(svgEl("line", { class: "grid", x1: padL, y1: yy, x2: w - padR, y2: yy }));
    const label = svgEl("text", {
      class: "axis", "data-test": "chart-y-label",
      x: padL - 7, y: yy + 4, "text-anchor": "end",
    });
    label.textContent = fmtNumber(v, locale, digits);
    svg.appendChild(label);
  }

  /* The hour axis: every 3rd (6th on narrow screens) hour start. */
  for (let i = 0; i < n; i += labelEvery) {
    const label = svgEl("text", {
      class: "axis", "data-test": "chart-x-label",
      x: x(i), y: h - padB + 20, "text-anchor": "middle",
    });
    label.textContent = fmtTime(hours[i], locale, tz);
    svg.appendChild(label);
  }

  /* One series per model, in API order; nulls break the line. */
  models.forEach((m, mi) => {
    const g = svgEl("g", { "data-test": "chart-series", "data-model": m.name });
    const color = MODEL_COLORS[mi % MODEL_COLORS.length];
    const vals = m.precipitation_mm || [];
    let cur = [];
    const flush = () => {
      if (cur.length > 1) {
        const dStr = cur.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
        g.appendChild(svgEl("path", { class: "line", d: dStr, stroke: color }));
      } else if (cur.length === 1) {
        g.appendChild(svgEl("circle", { cx: cur[0][0].toFixed(1), cy: cur[0][1].toFixed(1), r: 2.5, fill: color }));
      }
      cur = [];
    };
    for (let i = 0; i < Math.min(vals.length, n); i++) {
      const v = vals[i];
      if (typeof v !== "number" || !Number.isFinite(v)) { flush(); continue; }
      cur.push([x(i), y(v)]);
    }
    flush();
    svg.appendChild(g);
  });

  return svg;
}

/* The legend: one item per model (API order), the series colour and the
 * readable model name. */
function buildLegend(legend, models) {
  models.forEach((m, mi) => {
    const item = document.createElement("li");
    item.className = "chart-legend-item";
    item.setAttribute("data-test", "chart-legend-item");
    const swatch = document.createElement("i");
    swatch.className = "chart-swatch";
    swatch.style.background = MODEL_COLORS[mi % MODEL_COLORS.length];
    item.appendChild(swatch);
    item.appendChild(document.createTextNode(modelLabel(m.name)));
    legend.appendChild(item);
  });
  legend.hidden = false;
}
