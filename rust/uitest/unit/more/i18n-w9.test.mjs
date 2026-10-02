// Step W9: the wizard texts are German in German. The W2 file notes that
// the wizard texts were English in both languages "until W9"; the German
// page must show German labels, placeholders, results and messages.
// index.html no longer carries any of these texts — they are filled from
// i18n.js by setup.js — so this table is the single source of truth.
import { test } from "node:test";
import assert from "node:assert/strict";
import { STRINGS } from "../../../../app/static/i18n.js";

const W9_KEYS = [
  "setup.title", "setup.intro", "setup.search-label", "setup.search-placeholder",
  "setup.search-btn", "setup.divider", "setup.lat", "setup.lon", "setup.tz",
  "setup.lat-placeholder", "setup.lon-placeholder", "setup.tz-placeholder",
  "setup.save", "setup.cancel", "setup.note",
  "setup.status.min-length", "setup.status.searching", "setup.status.search-failed",
  "setup.status.selected", "setup.status.no-match", "setup.status.click-result",
  "setup.status.need-input", "setup.status.need-result", "setup.status.lat-range",
  "setup.status.lon-range", "setup.status.tz-required", "setup.status.saving",
  "setup.status.rejected", "setup.status.save-failed", "setup.confirm-change",
];

test("W9: the wizard keys exist in both languages, non-empty", () => {
  for (const key of W9_KEYS) {
    for (const lang of ["en", "de"]) {
      const value = STRINGS[lang][key];
      assert.ok(typeof value === "string" && value.trim() !== "", `${lang}.${key} is empty`);
    }
  }
});

test("W9: the German wizard texts are not the English ones", () => {
  for (const key of W9_KEYS) {
    assert.notEqual(STRINGS.de[key], STRINGS.en[key], `${key} is identical in en and de`);
  }
});

test("W9: the range messages still name the ranges (the UI check relies on it)", () => {
  assert.ok(STRINGS.de["setup.status.lat-range"].includes("-90") && STRINGS.de["setup.status.lat-range"].includes("90"));
  assert.ok(STRINGS.de["setup.status.lon-range"].includes("-180") && STRINGS.de["setup.status.lon-range"].includes("180"));
});

test("W9: the German latitude message is not in English", () => {
  assert.ok(!/\blatitude\b/.test(STRINGS.de["setup.status.lat-range"]), "de lat-range mentions 'latitude'");
});

test("W9: the field placeholders keep the dot decimal point (parsed with Number())", () => {
  for (const lang of ["en", "de"]) {
    assert.match(STRINGS[lang]["setup.lat-placeholder"], /\d\.\d/);
    assert.match(STRINGS[lang]["setup.lon-placeholder"], /\d\.\d/);
  }
});
