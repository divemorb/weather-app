/* i18n.js — the page texts (step W1).
 *
 * Pure module: no DOM, no navigator. The page (a later step) calls
 * pickLang(navigator.languages) once, sets <html lang>, and passes the
 * result to t(). Both languages carry the same flat keys; the fixed
 * texts below are checked by rust/uitest/unit/i18n.test.mjs and, from
 * W2 on, by the UI harness on the page.
 */

export const STRINGS = {
  en: {
    "answer.nodata": "No forecast data yet",
    "answer.dry": "No rain expected in the next hour",
    "answer.possible": "Rain possible in the next hour",
    "answer.likely": "Rain likely in the next hour",
    "radar.unavailable": "Radar: not available",
    "radar.none": "Radar: no rain nearby",
    "radar.now": "Radar: raining now",
    "radar.nowUntil": "Radar: raining now, until {to}",
    "radar.from": "Radar: rain from {from}",
    "radar.fromTo": "Radar: rain from {from} to {to}",
    "radar.dry": "Dry for the next 60 minutes",
    "radar.caption": "Strongest rain within {km} km, per 5 minutes",
    "cond.clear": "Clear",
    "cond.partly": "Partly cloudy",
    "cond.overcast": "Overcast",
    "cond.dry": "Dry",
    "cond.fog": "Fog",
    "cond.rain": "Rain",
    "cond.sleet": "Sleet",
    "cond.snow": "Snow",
    "cond.hail": "Hail",
    "cond.thunderstorm": "Thunderstorm",
    "now.title": "Now",
    "now.feels": "Feels like",
    "now.wind": "Wind",
    "now.gusts": "Gusts",
    "now.humidity": "Humidity",
    "now.pressure": "Pressure",
    "now.dewpoint": "Dew point",
    "now.clouds": "Clouds",
    "now.rain": "Rain last hour",
    "now.as-of": "as of",
    "now.unavailable": "No observation yet",
    "chart.dry": "No rain expected in the next 24 hours",
    "chart.unavailable": "No model forecast yet",
    "accuracy.none": "No data yet — observations are compared hourly.",
    "signals.models": "{n} of {total}",
    "age.na": "n/a",
    "location.loading": "loading location…",
    "location.unset": "No location set",
    "location.aria": "Change location",
    "theme.aria": "Toggle dark mode",
    "answer.loading": "Loading…",
    "glance.prob-label": "chance of rain in the next 60 min",
    "attribution": "Data: {dwd} via {brightsky} · {openmeteo} — non-commercial use only · Address search: © {osm} contributors.",
    "setup.title": "Set your location",
    "setup.intro": "Pick the spot this app watches for rain. It is stored in the app's database and drives the radar, the models and the accuracy tracking.",
    "setup.search-label": "Search an address or place",
    "setup.search-placeholder": "Address or place, e.g. Marienplatz 1, München",
    "setup.search-btn": "Search",
    "setup.divider": "or coordinates",
    "setup.lat": "Latitude",
    "setup.lon": "Longitude",
    "setup.tz": "Timezone",
    "setup.save": "Save location",
    "setup.cancel": "Cancel",
    "setup.note": "Address search uses OpenStreetMap Nominatim; the text is sent from this app's server. Radar covers Germany only; elsewhere the forecast uses the weather models only.",
    "setup.status.min-length": "Type at least 3 characters to search.",
    "setup.status.searching": "Searching…",
    "setup.status.search-failed": "Address search failed — try again, or enter the coordinates directly.",
    "setup.status.selected": "Selected: {label}. Check the timezone, then press \"Save location\".",
    "setup.status.no-match": "No match — try a more specific address, or enter coordinates.",
    "setup.status.click-result": "Click the matching result.",
    "setup.status.need-input": "Search for an address or enter latitude and longitude first.",
    "setup.status.need-result": "Click one of the search results first, or enter latitude and longitude.",
    "setup.status.lat-range": "Latitude must be a number between -90 and 90.",
    "setup.status.lon-range": "Longitude must be a number between -180 and 180.",
    "setup.status.tz-required": "Timezone is required (e.g. Europe/Berlin).",
    "setup.status.saving": "Saving…",
    "setup.status.rejected": "The location was rejected — check the values.",
    "setup.status.save-failed": "Could not save the location — try again.",
    "setup.confirm-change": "Changing the location deletes the cached data and the model-accuracy history. Continue?",
  },
  de: {
    "answer.nodata": "Noch keine Vorhersagedaten",
    "answer.dry": "In der nächsten Stunde kein Regen erwartet",
    "answer.possible": "In der nächsten Stunde ist Regen möglich",
    "answer.likely": "In der nächsten Stunde wird es wahrscheinlich regnen",
    "radar.unavailable": "Radar: nicht verfügbar",
    "radar.none": "Radar: kein Regen in der Nähe",
    "radar.now": "Radar: es regnet jetzt",
    "radar.nowUntil": "Radar: es regnet jetzt, bis {to}",
    "radar.from": "Radar: Regen ab {from}",
    "radar.fromTo": "Radar: Regen von {from} bis {to}",
    "radar.dry": "In den nächsten 60 Minuten trocken",
    "radar.caption": "Stärkster Regen im Umkreis von {km} km, je 5 Minuten",
    "cond.clear": "Klar",
    "cond.partly": "Teilweise bewölkt",
    "cond.overcast": "Bedeckt",
    "cond.dry": "Trocken",
    "cond.fog": "Nebel",
    "cond.rain": "Regen",
    "cond.sleet": "Schneeregen",
    "cond.snow": "Schnee",
    "cond.hail": "Hagel",
    "cond.thunderstorm": "Gewitter",
    "now.title": "Jetzt",
    "now.feels": "Gefühlt",
    "now.wind": "Wind",
    "now.gusts": "Böen",
    "now.humidity": "Luftfeuchte",
    "now.pressure": "Luftdruck",
    "now.dewpoint": "Taupunkt",
    "now.clouds": "Bewölkung",
    "now.rain": "Regen letzte Stunde",
    "now.as-of": "Stand",
    "now.unavailable": "Noch keine Messung",
    "chart.dry": "In den nächsten 24 Stunden kein Regen erwartet",
    "chart.unavailable": "Noch keine Modellvorhersage",
    "accuracy.none": "Noch keine Daten – Messungen werden stündlich verglichen.",
    "signals.models": "{n} von {total}",
    "age.na": "k. A.",
    "location.loading": "lade den Ort…",
    "location.unset": "Noch kein Ort gesetzt",
    "location.aria": "Ort ändern",
    "theme.aria": "Farbschema umschalten",
    "answer.loading": "Lade…",
    "glance.prob-label": "Regenwahrscheinlichkeit in der nächsten Stunde",
    "attribution": "Daten: {dwd} via {brightsky} · {openmeteo} — nur nicht-kommerzielle Nutzung · Adresssuche: © {osm}.",
    "setup.title": "Set your location",
    "setup.intro": "Pick the spot this app watches for rain. It is stored in the app's database and drives the radar, the models and the accuracy tracking.",
    "setup.search-label": "Search an address or place",
    "setup.search-placeholder": "Address or place, e.g. Marienplatz 1, München",
    "setup.search-btn": "Search",
    "setup.divider": "or coordinates",
    "setup.lat": "Latitude",
    "setup.lon": "Longitude",
    "setup.tz": "Timezone",
    "setup.save": "Save location",
    "setup.cancel": "Cancel",
    "setup.note": "Address search uses OpenStreetMap Nominatim; the text is sent from this app's server. Radar covers Germany only; elsewhere the forecast uses the weather models only.",
    "setup.status.min-length": "Type at least 3 characters to search.",
    "setup.status.searching": "Searching…",
    "setup.status.search-failed": "Address search failed — try again, or enter the coordinates directly.",
    "setup.status.selected": "Selected: {label}. Check the timezone, then press \"Save location\".",
    "setup.status.no-match": "No match — try a more specific address, or enter coordinates.",
    "setup.status.click-result": "Click the matching result.",
    "setup.status.need-input": "Search for an address or enter latitude and longitude first.",
    "setup.status.need-result": "Click one of the search results first, or enter latitude and longitude.",
    "setup.status.lat-range": "Latitude must be a number between -90 and 90.",
    "setup.status.lon-range": "Longitude must be a number between -180 and 180.",
    "setup.status.tz-required": "Timezone is required (e.g. Europe/Berlin).",
    "setup.status.saving": "Saving…",
    "setup.status.rejected": "The location was rejected — check the values.",
    "setup.status.save-failed": "Could not save the location — try again.",
    "setup.confirm-change": "Changing the location deletes the cached data and the model-accuracy history. Continue?",
  },
};

/* The first entry whose primary subtag (before "-", case-insensitive) is
 * de or en; "en" for an empty, missing or unsupported list. */
export function pickLang(list) {
  if (!Array.isArray(list)) return "en";
  for (const entry of list) {
    if (typeof entry !== "string" || entry === "") continue;
    const primary = entry.split("-")[0].toLowerCase();
    if (primary === "de" || primary === "en") return primary;
  }
  return "en";
}

/* Text for a flat key with {name} placeholders replaced from params.
 * An unknown language falls back to en; an unknown key returns the key. */
export function t(lang, key, params) {
  const table = STRINGS[lang] || STRINGS.en;
  let text = table[key];
  if (text == null) text = STRINGS.en[key];
  if (text == null) return key;
  if (params) {
    for (const [name, value] of Object.entries(params)) {
      text = text.split("{" + name + "}").join(String(value));
    }
  }
  return text;
}
