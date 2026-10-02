// Step W4: the radar strip's texts (glance.js). The caption carries the
// radius from /api/config as {km}; the dry line is a fixed sentence.
import { test } from "node:test";
import assert from "node:assert/strict";
import { STRINGS, t } from "../../../../app/static/i18n.js";

test("W4: the radar strip keys exist in both languages, non-empty", () => {
  for (const key of ["radar.dry", "radar.caption", "radar.unavailable"]) {
    for (const lang of ["en", "de"]) {
      const value = STRINGS[lang][key];
      assert.ok(typeof value === "string" && value.trim() !== "", `${lang}.${key} is empty`);
    }
  }
});

test("W4: the caption carries the {km} placeholder", () => {
  for (const lang of ["en", "de"]) {
    assert.ok(STRINGS[lang]["radar.caption"].includes("{km}"), `${lang}.radar.caption lacks {km}`);
  }
});

test("W4: the caption inserts the radius, whole and fractional", () => {
  assert.equal(t("en", "radar.caption", { km: "1" }), "Strongest rain within 1 km, per 5 minutes");
  assert.equal(t("de", "radar.caption", { km: "1" }), "Stärkster Regen im Umkreis von 1 km, je 5 Minuten");
  assert.equal(t("en", "radar.caption", { km: "2.5" }), "Strongest rain within 2.5 km, per 5 minutes");
});

test("W4: the dry line matches the contract's fixed texts", () => {
  assert.equal(STRINGS.en["radar.dry"], "Dry for the next 60 minutes");
  assert.equal(STRINGS.de["radar.dry"], "In den nächsten 60 Minuten trocken");
});
