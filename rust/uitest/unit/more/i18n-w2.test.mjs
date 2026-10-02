// Step W2: the keys the new page skeleton uses (app.js, glance.js,
// setup.js). The wizard texts are English in both languages until W9.
import { test } from "node:test";
import assert from "node:assert/strict";
import { STRINGS, t } from "../../../../app/static/i18n.js";

const W2_KEYS = [
  "location.loading", "location.unset", "location.aria", "theme.aria",
  "answer.loading", "glance.prob-label", "attribution",
  "setup.title", "setup.intro", "setup.search-label", "setup.search-placeholder",
  "setup.search-btn", "setup.divider", "setup.lat", "setup.lon", "setup.tz",
  "setup.save", "setup.cancel", "setup.note",
  "setup.status.min-length", "setup.status.searching", "setup.status.search-failed",
  "setup.status.selected", "setup.status.no-match", "setup.status.click-result",
  "setup.status.need-input", "setup.status.need-result", "setup.status.lat-range",
  "setup.status.lon-range", "setup.status.tz-required", "setup.status.saving",
  "setup.status.rejected", "setup.status.save-failed", "setup.confirm-change",
];

test("W2: the new keys exist in both languages, non-empty", () => {
  for (const key of W2_KEYS) {
    for (const lang of ["en", "de"]) {
      const value = STRINGS[lang][key];
      assert.ok(typeof value === "string" && value.trim() !== "", `${lang}.${key} is empty`);
    }
  }
});

test("W2: the attribution carries the four link placeholders", () => {
  for (const lang of ["en", "de"]) {
    for (const ph of ["{dwd}", "{brightsky}", "{openmeteo}", "{osm}"]) {
      assert.ok(STRINGS[lang]["attribution"].includes(ph), `${lang}.attribution lacks ${ph}`);
    }
  }
});

test("W2: the lat/lon range messages name the ranges", () => {
  assert.ok(STRINGS.en["setup.status.lat-range"].includes("-90") && STRINGS.en["setup.status.lat-range"].includes("90"));
  assert.ok(STRINGS.en["setup.status.lon-range"].includes("-180") && STRINGS.en["setup.status.lon-range"].includes("180"));
});

test("W2: the selected message inserts the label", () => {
  assert.equal(t("en", "setup.status.selected", { label: "X" }),
    STRINGS.en["setup.status.selected"].replace("{label}", "X"));
});
