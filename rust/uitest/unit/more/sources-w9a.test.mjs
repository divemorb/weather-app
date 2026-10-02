// Step W9a: each source row in the Details card names the page part it
// feeds, so the two "DWD (Bright Sky)" rows (radar, observation) and the
// two "Open-Meteo" rows (models, ensemble) stay tellable apart. details.js
// renders the feed names from these i18n keys, and the UI check
// (source-rows) expects exactly these words in each language.
import { test } from "node:test";
import assert from "node:assert/strict";
import { STRINGS } from "../../../../app/static/i18n.js";

const FEEDS = {
  radar: { key: "weight.radar", en: "Radar", de: "Radar" },
  current: { key: "now.title", en: "Now", de: "Jetzt" },
  forecast: { key: "weight.models", en: "Models", de: "Modelle" },
  ensemble: { key: "weight.ensemble", en: "Ensemble", de: "Ensemble" },
};

test("W9a: the four feed keys exist in both languages, non-empty", () => {
  for (const feed of Object.values(FEEDS)) {
    for (const lang of ["en", "de"]) {
      const value = STRINGS[lang][feed.key];
      assert.ok(typeof value === "string" && value.trim() !== "", `${lang}.${feed.key} is empty`);
    }
  }
});

test("W9a: the feed names are the ones the source rows must show", () => {
  for (const feed of Object.values(FEEDS)) {
    assert.equal(STRINGS.en[feed.key], feed.en, `en.${feed.key} changed`);
    assert.equal(STRINGS.de[feed.key], feed.de, `de.${feed.key} changed`);
  }
});

test("W9a: the feed names are all distinct per language", () => {
  for (const lang of ["en", "de"]) {
    const names = Object.values(FEEDS).map((f) => STRINGS[lang][f.key]);
    assert.equal(new Set(names).size, names.length, `two ${lang} feeds share a name`);
  }
});
