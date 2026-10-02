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
    "now.unavailable": "No observation yet",
    "chart.dry": "No rain expected in the next 24 hours",
    "chart.unavailable": "No model forecast yet",
    "accuracy.none": "No data yet — observations are compared hourly.",
    "signals.models": "{n} of {total}",
    "age.na": "n/a",
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
    "now.unavailable": "Noch keine Messung",
    "chart.dry": "In den nächsten 24 Stunden kein Regen erwartet",
    "chart.unavailable": "Noch keine Modellvorhersage",
    "accuracy.none": "Noch keine Daten – Messungen werden stündlich verglichen.",
    "signals.models": "{n} von {total}",
    "age.na": "k. A.",
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
