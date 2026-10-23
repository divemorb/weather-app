/* stations.js — the observation stations' pure helpers: a station's offset
 * and compass point from the place, one entry and one map mark per DWD
 * station id. No DOM; the contract is rust/uitest/unit (via format.js). */

/* The station's offset from the location, flat approximation (exact enough
 * at station distances): dx = Δlon·cos(lat)·111.32 km east,
 * dy = Δlat·110.57 km north. { bearing: degrees clockwise from north,
 * 0 ≤ b < 360, km: the distance }. null when a coordinate is missing. */
export function stationOffsetKm(from, to) {
  if (!from || typeof from !== "object" || !to || typeof to !== "object") return null;
  const lat = Number(from.lat ?? from.latitude);
  const lon = Number(from.lon ?? from.longitude);
  const lat2 = Number(to.lat ?? to.latitude);
  const lon2 = Number(to.lon ?? to.longitude);
  if (![lat, lon, lat2, lon2].every(Number.isFinite)) return null;
  const dy = (lat2 - lat) * 110.57; // km north
  const dx = (lon2 - lon) * Math.cos((lat * Math.PI) / 180) * 111.32; // km east
  const km = Math.hypot(dx, dy);
  const bearing = (Math.atan2(dx, dy) * 180) / Math.PI;
  return { bearing: (bearing + 360) % 360, km };
}

/* The compass point of a bearing in degrees: 0 north, 1 north-east, ...
 * 7 north-west (the nearest of the eight). */
export function compassPoint(bearing) {
  return ((Math.round(Number(bearing) / 45) % 8) + 8) % 8;
}

/* The observation stations, one per DWD station id: Bright Sky can list
 * one station under several sources (other names, coordinates, hours).
 * Keeps the first entry's name, distance and position (the API lists the
 * nearest first) and the largest hour count; entries without an id stay
 * as they are, in order. */
export function mergeStations(stations) {
  const out = [];
  const byId = new Map();
  for (const s of Array.isArray(stations) ? stations : []) {
    if (!s || typeof s !== "object") continue;
    const id = s.dwd_station_id == null ? null : String(s.dwd_station_id);
    const seen = id === null ? null : byId.get(id);
    if (!seen) {
      const copy = { ...s };
      out.push(copy);
      if (id !== null) byId.set(id, copy);
    } else if (Number(s.hours) > Number(seen.hours) || seen.hours == null) {
      seen.hours = s.hours;
    }
  }
  return out;
}

/* The map's marks: one per DWD station id — Now's station and an
 * observation station with the same id are one mark (Now's coordinates
 * win, it is the freshest). Returns { id, name, lat, lon, distance_m,
 * isNow } in first-seen order (Now's station first). */
export function stationMarks(station, stations) {
  const marks = new Map();
  const add = (s, isNow) => {
    if (!s || typeof s !== "object") return;
    const id = s.dwd_station_id == null ? null : String(s.dwd_station_id);
    if (id === null || marks.has(id)) return;
    marks.set(id, {
      id,
      name: typeof s.name === "string" ? s.name : "",
      lat: Number(s.lat),
      lon: Number(s.lon),
      distance_m: typeof s.distance_m === "number" ? s.distance_m : null,
      isNow,
    });
  };
  add(station, true);
  if (Array.isArray(stations)) for (const s of stations) add(s, false);
  return [...marks.values()];
}
