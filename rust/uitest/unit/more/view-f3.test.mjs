// Step F3: the view button shows short text that says where a click goes.
// view.js makes the text the button's accessible name, so WCAG 2.5.3
// (label in name) holds by construction; the texts themselves are fixed.
import { test } from "node:test";
import assert from "node:assert/strict";
import { STRINGS, t } from "../../../../app/static/i18n.js";

// The visible texts per current view: in the big view a click goes to the
// detailed view ("Details"), in the detailed view back to the big view.
const EXPECTED = {
  en: { "view.to-detailed": "Details", "view.to-big": "Big view" },
  de: { "view.to-detailed": "Details", "view.to-big": "Große Ansicht" },
};

test("F3: the view button texts are the expected words in both languages", () => {
  for (const [lang, want] of Object.entries(EXPECTED)) {
    for (const [key, text] of Object.entries(want)) {
      assert.equal(STRINGS[lang][key], text, `${lang}.${key}`);
      // Short enough to stay on one line in the top bar on a 390 px phone.
      assert.ok(text.length <= 16, `${lang}.${key} is ${text.length} chars`);
    }
  }
});

test("F3: t() resolves both keys without placeholders in either language", () => {
  for (const lang of ["en", "de"]) {
    for (const key of Object.keys(EXPECTED[lang])) {
      const visible = t(lang, key);
      assert.equal(visible, EXPECTED[lang][key], `${lang}.${key} via t()`);
      assert.ok(!visible.includes("{"), `${lang}.${key} has an unresolved placeholder`);
    }
  }
});
