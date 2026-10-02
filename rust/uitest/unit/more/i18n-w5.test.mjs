// Step W5: the Now section's texts (i18n.js). The labels and the fixed
// "no observation" line exist in both languages; the fixed line matches
// the contract's expected values.
import { test } from "node:test";
import assert from "node:assert/strict";
import { STRINGS } from "../../../../app/static/i18n.js";

test("W5: the Now section's keys exist in both languages, non-empty", () => {
  for (const key of [
    "now.title", "now.feels", "now.wind", "now.gusts", "now.humidity",
    "now.pressure", "now.dewpoint", "now.clouds", "now.rain", "now.as-of",
    "now.unavailable",
  ]) {
    for (const lang of ["en", "de"]) {
      const value = STRINGS[lang][key];
      assert.ok(typeof value === "string" && value.trim() !== "", `${lang}.${key} is empty`);
    }
  }
});

test("W5: the labels match the brief", () => {
  const en = {
    "now.title": "Now", "now.feels": "Feels like", "now.wind": "Wind",
    "now.gusts": "Gusts", "now.humidity": "Humidity", "now.pressure": "Pressure",
    "now.dewpoint": "Dew point", "now.clouds": "Clouds",
    "now.rain": "Rain last hour", "now.as-of": "as of",
  };
  const de = {
    "now.title": "Jetzt", "now.feels": "Gefühlt", "now.wind": "Wind",
    "now.gusts": "Böen", "now.humidity": "Luftfeuchte", "now.pressure": "Luftdruck",
    "now.dewpoint": "Taupunkt", "now.clouds": "Bewölkung",
    "now.rain": "Regen letzte Stunde", "now.as-of": "Stand",
  };
  for (const [key, want] of Object.entries(en)) assert.equal(STRINGS.en[key], want, `en.${key}`);
  for (const [key, want] of Object.entries(de)) assert.equal(STRINGS.de[key], want, `de.${key}`);
});

test("W5: the no-observation line matches the contract's fixed texts", () => {
  assert.equal(STRINGS.en["now.unavailable"], "No observation yet");
  assert.equal(STRINGS.de["now.unavailable"], "Noch keine Messung");
});
