/* reportkind.js — the user's weather reports and the page's scenes.
 *
 * Pure module: no DOM, no navigator. KINDS is the eight kinds in the
 * picker's order; kindScene(kind, intensity, day) is the scene a report
 * shows (null for an unknown kind); sceneKind(scene) is what "That's
 * right" reports for the scene the page shows, {kind, intensity} or null;
 * isDay(lat, lon, date) is the sun up: its centre above -0.833 degrees,
 * for a JS Date.
 */

// the eight kinds, in the picker's order
export const KINDS = [
  "clear", "partly-cloudy", "cloudy", "fog",
  "rain", "thunderstorm", "snow", "hail",
];

const RAD = Math.PI / 180;
const DEG = 180 / Math.PI;

/* The scene a report of `kind` shows: clear and partly cloudy depend on
 * day and night, heavy rain has its own scene, and unknown kinds show
 * nothing of their own. */
export function kindScene(kind, intensity, day) {
  if (kind === "clear" || kind === "partly-cloudy") {
    return kind + (day ? "-day" : "-night");
  }
  if (kind === "rain") return intensity === "heavy" ? "heavy-rain" : "rain";
  return KINDS.includes(kind) ? kind : null;
}

const SCENE_KIND = {
  "clear-day": ["clear", null],
  "clear-night": ["clear", null],
  "partly-cloudy-day": ["partly-cloudy", null],
  "partly-cloudy-night": ["partly-cloudy", null],
  cloudy: ["cloudy", null],
  fog: ["fog", null],
  rain: ["rain", null],
  "heavy-rain": ["rain", "heavy"],
  thunderstorm: ["thunderstorm", null],
  snow: ["snow", null],
  hail: ["hail", null],
};

/* The report that confirms the scene the page shows, if any. */
export function sceneKind(scene) {
  const entry = SCENE_KIND[scene];
  return entry ? { kind: entry[0], intensity: entry[1] } : null;
}

// degrees into [0, 360)
function normDeg(x) {
  x %= 360;
  return x < 0 ? x + 360 : x;
}

/* The sun's altitude in degrees: the usual solar-position approximation
 * (Astronomical Almanac), good to well under a degree. */
function sunAltitude(lat, lon, date) {
  const d = date.getTime() / 86400000 - 10957.5; // days since J2000.0
  const g = normDeg(357.529 + 0.98560028 * d);   // mean anomaly
  const q = normDeg(280.459 + 0.98564736 * d);   // mean longitude
  const l = normDeg(q + 1.915 * Math.sin(g * RAD) + 0.02 * Math.sin(2 * g * RAD));
  const e = 23.439 - 0.00000036 * d;             // obliquity
  let ra = Math.atan2(Math.cos(e * RAD) * Math.sin(l * RAD), Math.cos(l * RAD)) * DEG / 15;
  if (Math.sign(ra) < Math.sign(q)) ra += 24;
  if (Math.sign(ra) < 0) ra += 24;
  ra *= 15;
  const decl = Math.asin(Math.sin(e * RAD) * Math.sin(l * RAD)) * DEG;
  const st = normDeg(280.46061837 + 360.98564736629 * d + lon);
  let lha = st - ra;
  if (lha < -180) lha += 360;
  else if (lha > 180) lha -= 360;
  const zenith = Math.acos(
    Math.sin(lat * RAD) * Math.sin(decl * RAD) +
    Math.cos(lat * RAD) * Math.cos(decl * RAD) * Math.cos(lha * RAD),
  );
  return 90 - zenith * DEG;
}

/* Is the sun up: its centre above -0.833 degrees (the usual
 * sunrise/sunset), for a JS Date. */
export function isDay(lat, lon, date) {
  const d = date instanceof Date ? date : new Date(date);
  return sunAltitude(lat, lon, d) > -0.833;
}

/* Day or night for a report observed at observedIso, at location (the
 * /api/config shape: latitude, longitude); without one, 05-17 UTC. */
export function isDayAt(location, observedIso) {
  const d = new Date(observedIso);
  if (isNaN(d.getTime())) return false;
  if (!location || typeof location.latitude !== "number" || typeof location.longitude !== "number") {
    const h = d.getUTCHours();
    return h >= 5 && h < 17;
  }
  return isDay(location.latitude, location.longitude, d);
}
