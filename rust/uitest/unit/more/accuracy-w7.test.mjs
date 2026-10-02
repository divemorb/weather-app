// Step W7: the accuracy table's pure helpers (format.js). The table
// explains itself, so the note texts must match the contract exactly;
// the "no rain measured yet" note shows only when no model has a hit
// or a miss, which rainObserved() decides.
import { test } from "node:test";
import assert from "node:assert/strict";
import { STRINGS, t } from "../../../../app/static/i18n.js";
import { rainObserved, sortAccuracy } from "../../../../app/static/format.js";

/* The recorded accuracy fixture (rust/contract/golden/accuracy.json). */
const FIXTURE = {
  arome_france: { n_samples: 72, hits: 16, misses: 4, false_alarms: 14, correct_negatives: 38, enough_data: true, mae_mm: 0.168, event_accuracy: 0.75 },
  ecmwf_ifs025: { n_samples: 72, hits: 4, misses: 16, false_alarms: 38, correct_negatives: 14, enough_data: true, mae_mm: 0.306, event_accuracy: 0.25 },
  gfs_seamless: { n_samples: 72, hits: 10, misses: 10, false_alarms: 26, correct_negatives: 26, enough_data: true, mae_mm: 0.235, event_accuracy: 0.5 },
  icon_d2: { n_samples: 72, hits: 18, misses: 2, false_alarms: 10, correct_negatives: 42, enough_data: true, mae_mm: 0.143, event_accuracy: 0.833 },
  icon_eu: { n_samples: 72, hits: 12, misses: 8, false_alarms: 22, correct_negatives: 30, enough_data: true, mae_mm: 0.214, event_accuracy: 0.583 },
  ukmo_seamless: { n_samples: 72, hits: 6, misses: 14, false_alarms: 34, correct_negatives: 18, enough_data: true, mae_mm: 0.281, event_accuracy: 0.333 },
};

test("W7: rainObserved is true only when a model has a hit or a miss", () => {
  assert.equal(rainObserved(FIXTURE), true);
  assert.equal(
    rainObserved({
      a: { hits: 0, misses: 0, false_alarms: 5 },
      b: { hits: 0, misses: 0, false_alarms: 0 },
    }),
    false,
    "false alarms alone are no measured rain"
  );
  assert.equal(rainObserved({ a: { hits: 1, misses: 0 } }), true);
  assert.equal(rainObserved({ a: { hits: 0, misses: 1 } }), true);
  assert.equal(rainObserved({ a: { false_alarms: 3 } }), false); // missing counts count as 0
  assert.equal(rainObserved({}), false);
  assert.equal(rainObserved(null), false);
  assert.equal(rainObserved(undefined), false);
});

test("W7: sortAccuracy puts the fixture in the contract's order", () => {
  assert.deepEqual(sortAccuracy(FIXTURE), [
    "icon_d2", "arome_france", "icon_eu", "gfs_seamless", "ukmo_seamless", "ecmwf_ifs025",
  ]);
});

test("W7: sortAccuracy keeps enough-data rows first, ties stay in API order", () => {
  const mixed = {
    low: { enough_data: false, event_accuracy: 0.9 },
    good: { enough_data: true, event_accuracy: 0.5 },
    tie_b: { enough_data: true, event_accuracy: 0.5 },
    tie_a: { enough_data: true, event_accuracy: 0.5 },
  };
  assert.deepEqual(sortAccuracy(mixed), ["good", "tie_b", "tie_a", "low"]);
  assert.deepEqual(sortAccuracy({}), []);
  assert.deepEqual(sortAccuracy(null), []);
});

test("W7: the table's note and no-rain texts match the contract exactly", () => {
  assert.equal(
    STRINGS.en["accuracy.note"],
    "Every hour, each model's forecast is compared with what the nearest DWD weather station measured. " +
      "Rain means more than 0.1 mm in the hour. Hit: rain forecast and measured. Miss: rain measured but " +
      "not forecast. False alarm: rain forecast, but it stayed dry. Hit rate: the share of hours a model " +
      "got right, rain or dry. Avg. error: the mean difference in mm per hour."
  );
  assert.equal(
    STRINGS.de["accuracy.note"],
    "Stündlich wird die Vorhersage jedes Modells mit der Messung der nächsten DWD-Wetterstation verglichen. " +
      "Regen heißt mehr als 0,1 mm in der Stunde. Treffer: Regen vorhergesagt und gemessen. Verpasst: Regen " +
      "gemessen, aber nicht vorhergesagt. Fehlalarm: Regen vorhergesagt, aber es blieb trocken. Trefferquote: " +
      "Anteil der Stunden, in denen ein Modell richtig lag, ob Regen oder trocken. Ø Abweichung: mittlere " +
      "Differenz in mm pro Stunde."
  );
  assert.equal(
    STRINGS.en["accuracy.no-rain"],
    "No rain measured in this window yet, so only false alarms show so far."
  );
  assert.equal(
    STRINGS.de["accuracy.no-rain"],
    "In diesem Zeitraum wurde noch kein Regen gemessen, daher sind bisher nur Fehlalarme sichtbar."
  );
});

test("W7: the header keys give the contract's column names in order", () => {
  const head = ["model", "hours", "hits", "misses", "false-alarms", "hit-rate", "mae"];
  assert.deepEqual(head.map((k) => STRINGS.en[`accuracy.head.${k}`]),
    ["Model", "Hours", "Hits", "Misses", "False alarms", "Hit rate", "Avg. error"]);
  assert.deepEqual(head.map((k) => STRINGS.de[`accuracy.head.${k}`]),
    ["Modell", "Stunden", "Treffer", "Verpasst", "Fehlalarme", "Trefferquote", "Ø Abweichung"]);
});

test("W7: the new keys exist in both languages, non-empty", () => {
  for (const key of [
    "details.title", "details.signals-weights", "details.refresh", "details.sources", "details.accuracy",
    "weight.radar", "weight.models", "weight.ensemble", "signals.radar-yes", "signals.radar-no",
    "countdown.page", "sources.stale", "accuracy.none", "accuracy.note", "accuracy.no-rain",
  ]) {
    for (const lang of ["en", "de"]) {
      const value = STRINGS[lang][key];
      assert.ok(typeof value === "string" && value.trim() !== "", `${lang}.${key} is empty`);
    }
  }
  assert.equal(t("en", "signals.models", { n: 3, total: 5 }), "3 of 5");
  assert.equal(t("de", "signals.models", { n: 3, total: 5 }), "3 von 5");
});
