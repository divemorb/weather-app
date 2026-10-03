/* stationmap.js — the Details "Stations/Stationen" section: the
 * observation stations (one row each) and the schematic map of them.
 *
 * The station names are untrusted API text: textContent, never
 * innerHTML. The section wrapper is details.js's own section() builder,
 * passed in as `section`, so the markup stays identical to the other
 * details sections. The section (and the map) is absent without a Now
 * station and without observation stations.
 */
import { DASH, fmtNumber, stationMarks, stationOffsetKm } from "./format.js";
import { t } from "./i18n.js";

const SVG_NS = "http://www.w3.org/2000/svg";

function svgEl(tag, attrs) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

/* The scale bar's length in km: the first nice step that draws at least
 * 56 px (the last one when the map's scale is too small for all of them). */
const SCALE_KM = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100];

function scaleBarKm(scale) {
  for (const km of SCALE_KM) if (km * scale >= 56) return km;
  return SCALE_KM[SCALE_KM.length - 1];
}

/* The Details section: the observation stations (API order, nearest
 * first) and the schematic map. */
export function stationsSection({ now, accuracy, location, radiusKm, lang, locale, section }) {
  const st = now && now.available && now.conditions ? now.conditions.station : null;
  const station = st && typeof st === "object" ? st : null;
  const obs = accuracy && Array.isArray(accuracy.stations) ? accuracy.stations : [];
  if (!station && obs.length === 0) return null;
  const sec = section(t(lang, "details.stations"));
  if (obs.length > 0) sec.appendChild(obsList(obs, lang, locale));
  const marks = stationMarks(station, obs).filter(
    (m) => Number.isFinite(m.lat) && Number.isFinite(m.lon)
  );
  const loc = location
    && Number.isFinite(Number(location.latitude))
    && Number.isFinite(Number(location.longitude))
    ? location
    : null;
  if (loc && marks.length > 0) sec.appendChild(buildMap(loc, marks, radiusKm, lang, locale));
  return sec;
}

/* One row per observation station. The names are untrusted API text:
 * textContent, never innerHTML. */
function obsList(obs, lang, locale) {
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
      parts.push(`${fmtNumber(s.distance_m / 1000, locale, 1)} km`);
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

/* The schematic map: inline SVG, north is up. The location in the centre,
 * one mark per DWD station at its bearing and at a distance proportional
 * to the real distance (one linear scale for the marks and the radar
 * radius circle, the farthest mark kept inside the frame), the radar
 * radius as a circle around the location, a north arrow and a scale bar. */
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
  for (const { m, o } of placed) {
    const rad = (o.bearing * Math.PI) / 180;
    const mark = svgEl("circle", {
      "data-test": "map-station", "data-station": m.id, class: "map-mark",
      cx: c + o.km * scale * Math.sin(rad),
      cy: c - o.km * scale * Math.cos(rad),
      r: 4,
    });
    const title = document.createElementNS(SVG_NS, "title");
    title.textContent = m.name; // untrusted API text: textContent
    mark.appendChild(title);
    svg.appendChild(mark);
    // The name under the mark (above it near the bottom), shifted to stay inside
    // the map (width estimated at 6 px per character).
    const x = Number(mark.getAttribute("cx"));
    const y = Number(mark.getAttribute("cy"));
    const half = Math.min((String(m.name).length * 6) / 2, c - 4);
    const label = svgEl("text", {
      class: "map-label", "text-anchor": "middle",
      x: Math.min(Math.max(x, half + 4), size - half - 4), y: y > size - 50 ? y - 8 : y + 16,
    });
    label.textContent = m.name;
    svg.appendChild(label);
  }
  const loc = svgEl("g", { "data-test": "map-location", class: "map-location" });
  loc.appendChild(svgEl("circle", { class: "map-loc", cx: c, cy: c, r: 5 }));
  loc.appendChild(svgEl("circle", { class: "map-loc-hole", cx: c, cy: c, r: 1.8 }));
  svg.appendChild(loc);

  const north = svgEl("g", {
    "data-test": "map-north", class: "map-north", transform: `translate(${size - 24} 16)`,
  });
  north.appendChild(svgEl("path", { d: "M0 18V2M0 2L-4 8M0 2L4 8" }));
  const nText = svgEl("text", { x: 0, y: 32, "text-anchor": "middle" });
  nText.textContent = t(lang, "map.north");
  north.appendChild(nText);
  svg.appendChild(north);

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
  return svg;
}
