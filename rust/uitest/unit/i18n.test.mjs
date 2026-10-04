// Contract for app/static/i18n.js (step W1). Run: node --test rust/uitest/unit/
// The texts below are decided (qwen/web/00_brief.md, "Fixed texts"); the UI
// harness checks the same texts on the page.
import { test } from "node:test";
import assert from "node:assert/strict";
import { STRINGS, pickLang, t } from "../../../app/static/i18n.js";

test("pickLang: first supported language from navigator.languages", () => {
  assert.equal(pickLang(["de-DE", "en"]), "de");
  assert.equal(pickLang(["en-GB", "de"]), "en");
  assert.equal(pickLang(["fr-FR", "de-AT"]), "de");
  assert.equal(pickLang(["DE-ch"]), "de");
  assert.equal(pickLang(["fr"]), "en");
  assert.equal(pickLang([]), "en");
  assert.equal(pickLang(undefined), "en");
});

test("STRINGS: de and en have the same keys, no empty texts", () => {
  assert.deepEqual(Object.keys(STRINGS.de).sort(), Object.keys(STRINGS.en).sort());
  for (const lang of ["de", "en"]) {
    for (const [key, text] of Object.entries(STRINGS[lang])) {
      assert.ok(typeof text === "string" && text.trim() !== "", `${lang}.${key} is empty`);
    }
  }
});

test("t: placeholders, unknown keys", () => {
  assert.equal(t("de", "radar.fromTo", { from: "12:55", to: "13:05" }), "Radar: Regen von 12:55 bis 13:05");
  assert.equal(t("en", "signals.models", { n: 3, total: 5 }), "3 of 5");
  assert.equal(t("de", "signals.models", { n: 3, total: 5 }), "3 von 5");
  assert.equal(t("en", "no.such.key"), "no.such.key");
  assert.equal(t("fr", "answer.dry"), "No rain expected in the next hour"); // unknown language -> en
});

const FIXED = {
  "answer.nodata": ["No forecast data yet", "Noch keine Vorhersagedaten"],
  "answer.dry": ["No rain expected in the next hour", "In der nächsten Stunde kein Regen erwartet"],
  "answer.possible": ["Rain possible in the next hour", "In der nächsten Stunde ist Regen möglich"],
  "answer.likely": ["Rain likely in the next hour", "In der nächsten Stunde wird es wahrscheinlich regnen"],
  "radar.unavailable": ["Radar: not available", "Radar: nicht verfügbar"],
  "radar.none": ["Radar: no rain nearby", "Radar: kein Regen in der Nähe"],
  "radar.now": ["Radar: raining now", "Radar: es regnet jetzt"],
  "radar.nowUntil": ["Radar: raining now, until {to}", "Radar: es regnet jetzt, bis {to}"],
  "radar.from": ["Radar: rain from {from}", "Radar: Regen ab {from}"],
  "radar.fromTo": ["Radar: rain from {from} to {to}", "Radar: Regen von {from} bis {to}"],
  "cond.clear": ["Clear", "Klar"],
  "cond.partly": ["Partly cloudy", "Teilweise bewölkt"],
  "cond.overcast": ["Overcast", "Bedeckt"],
  "cond.dry": ["Dry", "Trocken"],
  "cond.fog": ["Fog", "Nebel"],
  "cond.rain": ["Rain", "Regen"],
  "cond.sleet": ["Sleet", "Schneeregen"],
  "cond.snow": ["Snow", "Schnee"],
  "cond.hail": ["Hail", "Hagel"],
  "cond.thunderstorm": ["Thunderstorm", "Gewitter"],
  "now.unavailable": ["No observation yet", "Noch keine Messung"],
  "chart.dry": ["No rain expected in the next 24 hours", "In den nächsten 24 Stunden kein Regen erwartet"],
  "chart.unavailable": ["No model forecast yet", "Noch keine Modellvorhersage"],
  "accuracy.none": ["No data yet — observations are compared hourly.",
                    "Noch keine Daten – Messungen werden stündlich verglichen."],
  "signals.models": ["{n} of {total}", "{n} von {total}"],
  "signals.accuracy-weighted": ["Models weighted by their hit rate", "Modelle nach ihrer Trefferquote gewichtet"],
  "age.na": ["n/a", "k. A."],
};

test("fixed texts (the UI contract checks them on the page)", () => {
  for (const [key, [en, de]] of Object.entries(FIXED)) {
    assert.equal(STRINGS.en[key], en, `en.${key}`);
    assert.equal(STRINGS.de[key], de, `de.${key}`);
  }
});
