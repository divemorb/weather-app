/* stationmap.js — the Details "Stations/Stationen" section: what the
 * stations are for, one row per station (distance and direction from the
 * place), and the schematic map with its legend.
 *
 * The station names are untrusted API text: textContent, never
 * innerHTML. The section wrapper is details.js's own section() builder,
 * passed in as `section`, so the markup stays identical to the other
 * details sections. The section (and the map) is absent without a Now
 * station and without observation stations.
 */
import { DASH, fmtNumber } from "./format.js";
import { compassPoint, mergeStations, stationMarks, stationOffsetKm } from "./stations.js";
import { t } from "./i18n.js";
import { placeLabels } from "./maplabels.js";

const SVG_NS = "http://www.w3.org/2000/svg";

// an SVG element with the given tag and attributes
function svgEl(tag, attrs) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

/* The scale bar's length in km: the first nice step that draws at least
 * 56 px (the last one when the map's scale is too small for all of them). */
const SCALE_KM = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100];

// the first scale step that draws at 56 px or more (the last, else)
function scaleBarKm(scale) {
  for (const km of SCALE_KM) if (km * scale >= 56) return km;
  return SCALE_KM[SCALE_KM.length - 1];
}

/* The Details section: a line on what the stations are for, the
 * observation stations (one per DWD station, nearest first) beside the
 * schematic map and its legend. */
export function stationsSection({ now, accuracy, location, radiusKm, lang, locale, section }) {
  const st = now && now.available && now.conditions ? now.conditions.station : null;
  const station = st && typeof st === "object" ? st : null;
  const obs = mergeStations(accuracy && Array.isArray(accuracy.stations) ? accuracy.stations : []);
  if (!station && obs.length === 0) return null;
  const sec = section(t(lang, "details.stations"));
  const loc = location
    && Number.isFinite(Number(location.latitude))
    && Number.isFinite(Number(location.longitude))
    ? location
    : null;
  const body = document.createElement("div");
  body.className = "stations-body";
  const text = document.createElement("div");
  const intro = document.createElement("p");
  intro.className = "stations-intro";
  intro.setAttribute("data-test", "stations-intro");
  intro.textContent = t(lang, "stations.intro");
  text.appendChild(intro);
  if (obs.length > 0) text.appendChild(obsList(obs, loc, lang, locale));
  body.appendChild(text);
  const marks = stationMarks(station, obs).filter(
    (m) => Number.isFinite(m.lat) && Number.isFinite(m.lon)
  );
  if (loc && marks.length > 0) {
    const fig = document.createElement("figure");
    fig.className = "stations-map";
    fig.append(buildMap(loc, marks, radiusKm, lang, locale), mapLegend(radiusKm, lang, locale));
    body.appendChild(fig);
  }
  sec.appendChild(body);
  return sec;
}

/* The legend under the map: the three symbols in words. */
function mapLegend(radiusKm, lang, locale) {
  const list = document.createElement("ul");
  list.className = "map-legend";
  list.setAttribute("data-test", "map-legend");
  const items = [["legend-here", t(lang, "map.here")], ["legend-station", t(lang, "map.legend-station")]];
  if (typeof radiusKm === "number" && Number.isFinite(radiusKm) && radiusKm > 0) {
    const km = fmtNumber(radiusKm, locale, radiusKm < 1 ? 1 : 0);
    items.splice(1, 0, ["legend-radar", t(lang, "map.legend-radar", { km })]);
  }
  for (const [cls, label] of items) {
    const li = document.createElement("li");
    const sym = document.createElement("i");
    sym.className = "legend-sym " + cls;
    li.append(sym, label);
    list.appendChild(li);
  }
  return list;
}

/* One row per observation station: its distance and direction from the
 * place (when known) and its hourly readings. The names are untrusted API
 * text: textContent, never innerHTML. */
function obsList(obs, loc, lang, locale) {
  const list = document.createElement("div");
  list.className = "obs-list";
  for (const s of obs) {
    if (!s || typeof s !== "object") continue;
    const row = document.createElement("div");
    row.className = "obs-row";
    row.setAttribute("data-test", "observation-station");
    const name = document.createElement("span");
    name.className = "obs-name";
    name.textContent = typeof s.name === "string" && s.name !== "" ? s.name : DASH;
    const parts = [];
    if (typeof s.distance_m === "number" && Number.isFinite(s.distance_m)) {
      const km = fmtNumber(s.distance_m / 1000, locale, 1);
      const o = loc ? stationOffsetKm(loc, s) : null;
      parts.push(o ? t(lang, "station.where", { km, dir: t(lang, "compass." + compassPoint(o.bearing)) }) : `${km} km`);
    }
    if (s.hours != null && s.hours !== "") {
      parts.push(t(lang, "station.hours", { n: String(s.hours) }));
    }
    const meta = document.createElement("span");
    meta.className = "obs-meta";
    meta.textContent = parts.join(" · ");
    row.append(name, " ", meta);
    list.appendChild(row);
  }
  return list;
}

let measurer = null; // the canvas's 2d context, made on the first measure

/* A text's drawn size at the map's 14-unit type, in the page's font (a
 * canvas measures it; the map isn't in the page yet): width, ascent, descent. */
function textSize(text, weight) {
  measurer = measurer || document.createElement("canvas").getContext("2d");
  if (!measurer) return { w: text.length * 8.4, asc: 13.3, desc: 3.5 };
  measurer.font = `${weight} 14px ${getComputedStyle(document.body).fontFamily}`;
  const m = measurer.measureText(text);
  return { w: m.width, asc: m.fontBoundingBoxAscent || 13.3, desc: m.fontBoundingBoxDescent || 3.5 };
}

// the box of a symbol centred at x, y (r: half its size, with its outline)
function circleBox(x, y, r) {
  return { l: x - r, t: y - r, r: x + r, b: y + r };
}

/* The schematic map: inline SVG, north is up. The location in the centre,
 * one mark per DWD station at its bearing and at a distance proportional
 * to the real distance (one linear scale for the marks and the radar
 * radius circle, the farthest mark kept inside the frame), the radar
 * radius as a circle around the location, a north arrow and a scale bar.
 * The names never cover each other or a symbol (maplabels.js). */
function buildMap(location, marks, radiusKm, lang, locale) {
  const size = 320;
  const c = size / 2;
  const margin = 34; // room for the mark radii, the north arrow, the scale bar
  const placed = [];
  for (const m of marks) {
    const o = stationOffsetKm(location, m);
    if (o) placed.push({ m, o });
  }
  const rKm = typeof radiusKm === "number" && Number.isFinite(radiusKm) && radiusKm > 0 ? radiusKm : 0;
  const maxKm = Math.max(rKm, ...placed.map((p) => p.o.km), 1e-3);
  const scale = (c - margin) / maxKm;

  const svg = svgEl("svg", {
    "data-test": "station-map",
    role: "img",
    "aria-label": t(lang, "map.aria"),
    viewBox: `0 0 ${size} ${size}`,
    class: "station-map",
  });
  if (rKm > 0) {
    svg.appendChild(svgEl("circle", {
      "data-test": "map-radius", class: "map-radius", cx: c, cy: c, r: rKm * scale,
    }));
  }
  const symbols = [circleBox(c, c, 6), northArrow(svg, size, lang), scaleBar(svg, size, scale, locale, lang)];
  const names = [];
  for (const { m, o } of placed) {
    const rad = (o.bearing * Math.PI) / 180;
    const x = c + o.km * scale * Math.sin(rad);
    const y = c - o.km * scale * Math.cos(rad);
    const mark = svgEl("circle", { "data-test": "map-station", "data-station": m.id, class: "map-mark", cx: x, cy: y, r: 4 });
    const title = document.createElementNS(SVG_NS, "title");
    title.textContent = m.name; // untrusted API text: textContent
    mark.appendChild(title);
    svg.appendChild(mark);
    symbols.push(circleBox(x, y, 5));
    names.push({ km: o.km, text: String(m.name), anchors: [{ x, y, r: 5 }], attrs: { class: "map-label" } });
  }
  names.sort((a, b) => a.km - b.km); // the nearest first, then the place: below its radar circle, else beside its mark
  names.push({ text: t(lang, "map.here"), weight: 600, anchors: [{ x: c, y: c, r: Math.max(rKm * scale + 1, 6) }, { x: c, y: c, r: 6 }],
    attrs: { class: "map-here", "data-test": "map-here" } });
  const loc = svgEl("g", { "data-test": "map-location", class: "map-location" });
  loc.appendChild(svgEl("circle", { class: "map-loc", cx: c, cy: c, r: 5 }));
  loc.appendChild(svgEl("circle", { class: "map-loc-hole", cx: c, cy: c, r: 1.8 }));
  svg.appendChild(loc);
  drawLabels(svg, names, symbols, size);
  return svg;
}

/* The names at their places (maplabels.js), each a text centred in its box
 * (untrusted station names: textContent). */
function drawLabels(svg, names, symbols, size) {
  const sized = names.map((n) => ({ ...n, ...textSize(n.text, n.weight || 400) }));
  const boxes = placeLabels(sized.map((n) => ({ anchors: n.anchors, w: n.w, h: n.asc + n.desc })),
    symbols, { l: 2, t: 2, r: size - 2, b: size - 2 });
  sized.forEach((n, i) => {
    const label = svgEl("text", { ...n.attrs, "text-anchor": "middle",
      x: (boxes[i].l + boxes[i].r) / 2, y: boxes[i].t + n.asc });
    label.textContent = n.text;
    svg.appendChild(label);
  });
}

// the north arrow in the top right corner; its box
function northArrow(svg, size, lang) {
  const north = svgEl("g", {
    "data-test": "map-north", class: "map-north", transform: `translate(${size - 24} 16)`,
  });
  north.appendChild(svgEl("path", { d: "M0 18V2M0 2L-4 8M0 2L4 8" }));
  const nText = svgEl("text", { x: 0, y: 32, "text-anchor": "middle" });
  nText.textContent = t(lang, "map.north");
  north.appendChild(nText);
  svg.appendChild(north);
  const n = textSize(nText.textContent, 400);
  return { l: size - 24 - Math.max(5, n.w / 2), t: 16, r: size - 24 + Math.max(5, n.w / 2), b: 16 + 32 + n.desc };
}

// the scale bar in the bottom left corner; its box
function scaleBar(svg, size, scale, locale, lang) {
  const barKm = scaleBarKm(scale);
  const bar = barKm * scale;
  const y = size - 16;
  const scaleG = svgEl("g", { "data-test": "map-scale", class: "map-scale" });
  scaleG.appendChild(svgEl("line", { x1: 12, y1: y, x2: 12 + bar, y2: y }));
  scaleG.appendChild(svgEl("line", { x1: 12, y1: y - 4, x2: 12, y2: y + 4 }));
  scaleG.appendChild(svgEl("line", { x1: 12 + bar, y1: y - 4, x2: 12 + bar, y2: y + 4 }));
  const sText = svgEl("text", { x: 12, y: y - 8, "text-anchor": "start" });
  sText.textContent = t(lang, "map.scale", { km: fmtNumber(barKm, locale, barKm < 1 ? 1 : 0) });
  scaleG.appendChild(sText);
  svg.appendChild(scaleG);
  const s = textSize(sText.textContent, 400);
  return { l: 11, t: y - 8 - s.asc, r: 13 + Math.max(bar, s.w), b: y + 5 };
}
