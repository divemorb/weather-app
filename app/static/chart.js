/* chart.js — the 24 h multi-model precipitation chart, inline SVG
 * (no external libraries, no canvas).
 *
 * Without any model data it shows the "unavailable" line, a completely
 * dry forecast the "dry" line, otherwise one line per model plus the
 * legend. The y axis comes from niceScale() (format.js) with mm/h; the
 * hour labels and amounts use the browser's language and the location's
 * time zone. A model's line breaks at null values. The viewBox matches
 * the container's pixel size, so the 12 px axis labels stay 12 px.
 */
import { fmtNumber, fmtTime, modelLabel, niceScale } from "./format.js";
import { t } from "./i18n.js";

/* Six series colours, each at least 3:1 against the light and the dark
 * card background (WCAG for graphics; checked in
 * rust/uitest/unit/more/chart-w6.test.mjs). */
export const MODEL_COLORS = ["#1f6feb", "#2da44e", "#bf8700", "#cf222e", "#8250df", "#1b9aaa"];

const NS = "http://www.w3.org/2000/svg";

const EVERY = [1, 2, 3, 4, 6, 12]; /* the hour steps a label may take */

/* The chart's geometry for a box of w x h px with n hours and axis text
 * of fontPx: the margins follow the text and the widest labels (xLabelW,
 * yLabelW px, measured), and the hour labels are spaced so neighbours keep
 * a gap of half a text height, at least 4 px (a label every EVERY-th
 * hour). The viewBox is the box itself, so the text is never scaled. */
export function chartMetrics(w, h, n, fontPx = 12, xLabelW = 48, yLabelW = 20) {
  w = Math.max(1, Math.floor(w));
  h = Math.max(1, Math.floor(h));
  const padL = Math.ceil(Math.max(yLabelW + 8, xLabelW / 2));
  const padR = Math.ceil(xLabelW / 2);
  const padT = Math.ceil(fontPx);
  const padB = Math.ceil(fontPx * 2.4);
  const step = (w - padL - padR) / Math.max(1, n - 1);
  const labelEvery = EVERY.find((e) => e * step >= xLabelW + Math.max(4, fontPx / 2)) || 24;
  return { w, h, padL, padR, padT, padB, labelEvery };
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

// an SVG element with the given tag and attributes
function svgEl(tag, attrs) {
  const el = document.createElementNS(NS, tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

/* What the chart drew last, for a redraw at a new size. */
let last = null;

/* Draw the chart (or the dry/unavailable line) into the card's elements:
 * els = { body, legend, unavailable, dry, unit }. Fully replaces what it
 * drew before. The has-chart class on the body gives the body the card's
 * free height (kiosk.css); the SVG is drawn at the body's size and drawn
 * again whenever the body changes size. */
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
  els.body.classList.remove("has-chart");
  els.legend.textContent = "";
  for (const el of [els.legend, els.unit, els.unavailable, els.dry]) el.hidden = true;
  last = null;

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
  buildLegend(els.legend, d.models); // in place before the body is measured
  els.body.classList.add("has-chart");
  last = { body: els.body, d, maxV, lang, locale, tz, size: "" };
  draw();
  observe(els.body);
}

// (re)draws the SVG at the body's size, if the size changed
function draw() {
  if (!last) return;
  const { body } = last;
  const size = body.clientWidth + "x" + body.clientHeight;
  if (size === last.size) return;
  last.size = size;
  body.textContent = "";
  body.appendChild(buildSvg(body, last.d, last.maxV, last.lang, last.locale, last.tz));
}

let observer = null;
// redraw when the body changes size (a resize, a turn, the type refitted)
function observe(body) {
  if (observer) return;
  observer = new ResizeObserver(draw);
  observer.observe(body);
}

let ctx = null;
// the widest of the texts in px at the body's axis font
function widest(texts, font) {
  ctx = ctx || document.createElement("canvas").getContext("2d");
  ctx.font = font;
  return Math.max(0, ...texts.map((s) => ctx.measureText(s).width));
}

// the chart's <svg>: the axes, the grid and one line per model
function buildSvg(body, { hours, models }, maxV, lang, locale, tz) {
  const n = hours.length;
  const scale = niceScale(maxV);
  const digits = scale.step < 1 ? 1 : 0;
  const xTexts = hours.map((hr) => fmtTime(hr, locale, tz));
  const yTexts = scale.ticks.map((v) => fmtNumber(v, locale, digits));
  /* The axis text has the body's font size (type.css: the caption style);
   * a narrow chart labels fewer hours, never smaller ones. */
  const style = getComputedStyle(body);
  const fontPx = parseFloat(style.fontSize) || 12;
  const font = `${fontPx}px ${style.fontFamily}`;
  const m = chartMetrics(body.clientWidth, body.clientHeight, n, fontPx, widest(xTexts, font), widest(yTexts, font));
  const { w, h, padL, padR, padT, padB, labelEvery } = m;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  const x = (i) => padL + (n <= 1 ? 0 : (i / (n - 1)) * plotW);
  const y = (v) => padT + plotH - (v / scale.max) * plotH;

  const svg = svgEl("svg", {
    "data-test": "chart",
    viewBox: `0 0 ${w} ${h}`,
    role: "img",
    "aria-label": t(lang, "chart.aria"),
    class: "chart-svg",
  });
  svg.style.fontSize = fontPx + "px"; // the axis text (.axis is 1em)

  /* The grid lines and y axis, exactly the niceScale ticks. */
  scale.ticks.forEach((v, i) => {
    const yy = y(v);
    svg.appendChild(svgEl("line", { class: "grid", x1: padL, y1: yy, x2: w - padR, y2: yy }));
    const label = svgEl("text", {
      class: "axis", "data-test": "chart-y-label",
      x: padL - 7, y: yy + fontPx / 3, "text-anchor": "end",
    });
    label.textContent = yTexts[i];
    svg.appendChild(label);
  });

  for (let i = 0; i < n; i += labelEvery) {
    const label = svgEl("text", {
      class: "axis", "data-test": "chart-x-label",
      x: x(i), y: h - padB + fontPx * 1.6, "text-anchor": "middle",
    });
    label.textContent = xTexts[i];
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

/* The legend: the series colour and readable name, one item per model
 * (API order). */
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
