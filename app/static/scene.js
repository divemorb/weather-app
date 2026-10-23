/* scene.js — the page's sky scene: which one shows and what decided it.
 * No DOM; the contract is rust/uitest/unit/scene.test.mjs (via format.js). */

/* The page's sky: which scene to show, as the name the page
 * sets on <html data-scene> — one of Bright Sky's twelve weather icons
 * (the /api/now icon), "heavy-rain" (the radar rains hard right now),
 * "rain" (the radar rains right now), or "none" (nothing to show). The
 * radar at the location decides about precipitation right now: rain in
 * its first five-minute step overrides a dry icon (heavy at >= 0.2 mm);
 * a dry radar (first step 0 mm) turns the station's rain, sleet, snow or
 * hail into cloudy (rule B). A thunderstorm stays as a warning (it can
 * arrive fast), and so does every icon while the radar is unavailable;
 * only the first step counts (rain later is not rain now). Malformed
 * answers never throw — they count as no data. */
export const SKY_ICONS = ["clear-day", "clear-night", "partly-cloudy-day", "partly-cloudy-night",
  "cloudy", "fog", "wind", "rain", "sleet", "snow", "hail", "thunderstorm"];
/* Kept while the radar rains (it can't tell snow from rain); see rule B above. */
const STAYS_ICONS = new Set(["sleet", "snow", "hail", "thunderstorm"]);
// per five-minute step: about 2.4 mm/h
export const HEAVY_RAIN_MM = 0.2;

// the valid /api/now icon, or null (malformed answers count as no data)
function nowIcon(now) {
  if (!now || typeof now !== "object" || Array.isArray(now)) return null;
  const c = now.conditions;
  const icon = c && typeof c === "object" ? c.icon : null;
  return typeof icon === "string" && SKY_ICONS.includes(icon) ? icon : null;
}

// the first step's mm (rain right now), or null when unavailable
function firstStepMm(radar) {
  if (!radar || typeof radar !== "object" || Array.isArray(radar)) return null;
  if (radar.available !== true || !Array.isArray(radar.steps)) return null;
  const step = radar.steps[0];
  if (!step || typeof step !== "object" || Array.isArray(step)) return null;
  const mm = step.precip_mm;
  return typeof mm === "number" && Number.isFinite(mm) ? mm : null;
}

/* The scene plus what decided it (the "why" line under the glance):
 * source "station" (the /api/now icon decided), "radar" (the radar
 * overrode the icon, either way), or "none"; stationIcon: the valid
 * /api/now icon or null; radarDry: the radar is available, first step 0 mm. */
export function sceneReason(now, radar) {
  const mm = firstStepMm(radar);
  const icon = nowIcon(now);
  const radarDry = mm === 0;
  if (icon && STAYS_ICONS.has(icon)) {
    if (radarDry && icon !== "thunderstorm") {
      return { scene: "cloudy", source: "radar", stationIcon: icon, radarDry };
    }
    return { scene: icon, source: "station", stationIcon: icon, radarDry };
  }
  if (icon === "rain") {
    if (mm == null) return { scene: "rain", source: "station", stationIcon: icon, radarDry };
    const scene = radarDry ? "cloudy" : mm >= HEAVY_RAIN_MM ? "heavy-rain" : "rain";
    return { scene, source: "radar", stationIcon: icon, radarDry };
  }
  const wet = mm >= HEAVY_RAIN_MM ? "heavy-rain" : mm > 0 ? "rain" : null;
  if (wet) return { scene: wet, source: "radar", stationIcon: icon, radarDry };
  if (icon) return { scene: icon, source: "station", stationIcon: icon, radarDry };
  return { scene: "none", source: "none", stationIcon: null, radarDry };
}

// the scene name only (sceneReason without the "why" parts)
export function scene(now, radar) {
  return sceneReason(now, radar).scene;
}
