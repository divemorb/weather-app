/* 24 h multi-model precipitation chart (inline SVG). Part of the step-5 frontend.
 *
 * Loaded before app.js via a <script> tag; exposes the global renderModelChart().
 * No external CDN — pure inline SVG so it works on a home network.
 */
"use strict";

const MODEL_COLORS = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#bc8cff", "#39c5cf"];
const SVG_NS = "http://www.w3.org/2000/svg";

function _svgEl(tag, attrs) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

/* Round a data max up to a "nice" upper bound for the y axis. */
function _niceMax(v) {
  if (v <= 0) return 1;
  const step = v <= 1 ? 0.2 : v <= 5 ? 1 : 2;
  return Math.max(step, Math.ceil(v / step) * step);
}

/**
 * Draw the multi-model precipitation chart into `containerEl` and build the
 * legend into `legendEl`. `fmtHour` / `fmtNum` are the shared formatters from
 * app.js (timestamps arrive as UTC ISO-8601 and are formatted in `tz`).
 */
function renderModelChart(containerEl, legendEl, data, fmtHour, fmtNum) {
  containerEl.innerHTML = "";
  legendEl.innerHTML = "";

  if (!data.available || !data.hours || data.hours.length === 0 ||
      !data.models || data.models.length === 0) {
    containerEl.innerHTML = '<span class="muted">No model forecast cached yet.</span>';
    return;
  }

  const hours = data.hours;
  const n = hours.length;
  const W = 720, H = 280, padL = 34, padR = 12, padT = 14, padB = 34;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  let maxV = 0;
  for (const m of data.models) {
    for (const v of m.precipitation_mm || []) if (v != null) maxV = Math.max(maxV, v);
  }
  const yMax = _niceMax(maxV);

  const x = (i) => padL + (n <= 1 ? 0 : (i / (n - 1)) * plotW);
  const y = (v) => padT + plotH - (v / yMax) * plotH;

  const svg = _svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "24 hour model comparison" });

  // Horizontal grid lines + y-axis labels.
  const yTicks = 4;
  for (let t = 0; t <= yTicks; t++) {
    const v = (yMax / yTicks) * t;
    const yy = y(v);
    svg.appendChild(_svgEl("line", { class: "grid", x1: padL, y1: yy, x2: W - padR, y2: yy }));
    const label = _svgEl("text", { class: "axis", x: padL - 6, y: yy + 3, "text-anchor": "end" });
    label.textContent = v.toFixed(v < 1 ? 1 : 0);
    svg.appendChild(label);
  }

  // x-axis hour labels (every 3rd).
  for (let i = 0; i < n; i += 3) {
    const label = _svgEl("text", { class: "axis", x: x(i), y: H - padB + 16, "text-anchor": "middle" });
    label.textContent = fmtHour(hours[i]);
    svg.appendChild(label);
  }

  // One line per model (breaks the path across nulls).
  data.models.forEach((m, mi) => {
    const color = MODEL_COLORS[mi % MODEL_COLORS.length];
    const vals = m.precipitation_mm || [];
    const segs = [];
    let cur = [];
    for (let i = 0; i < vals.length; i++) {
      const v = vals[i];
      if (v == null) {
        if (cur.length) segs.push(cur);
        cur = [];
      } else {
        cur.push([x(i), y(v)]);
      }
    }
    if (cur.length) segs.push(cur);

    for (const seg of segs) {
      const d = seg.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
      svg.appendChild(_svgEl("path", { class: "line", d, stroke: color }));
    }

    // Dots for each data point (with a native tooltip).
    for (let i = 0; i < vals.length; i++) {
      if (vals[i] == null) continue;
      const dot = _svgEl("circle", { class: "dot", cx: x(i), cy: y(vals[i]), r: 2, fill: color });
      const title = _svgEl("title", {});
      title.textContent = `${m.name} ${fmtHour(hours[i])}: ${fmtNum(vals[i], 2)} mm`;
      dot.appendChild(title);
      svg.appendChild(dot);
    }

    const item = document.createElement("span");
    item.className = "legend-item";
    const sw = document.createElement("i");
    sw.style.background = color;
    item.append(sw, m.name);
    legendEl.appendChild(item);
  });

  containerEl.appendChild(svg);
}
