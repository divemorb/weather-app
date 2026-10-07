// Contract for app/static/reportkind.js (report steps W1, W2): the user's
// weather reports and the page's scenes. Pure functions, no DOM.
//
//   KINDS                         the eight kinds, in the picker's order
//   kindScene(kind, intensity, day)  the scene a report shows (null for an unknown kind)
//   sceneKind(scene)              what "That's right" reports for the scene the page
//                                 shows: {kind, intensity}, or null (no such kind)
//   isDay(lat, lon, date)         the sun is up: its centre above -0.833° (the
//                                 usual sunrise/sunset), for a JS Date
import { test } from "node:test";
import assert from "node:assert/strict";
import { KINDS, isDay, kindScene, sceneKind } from "../../../app/static/reportkind.js";

test("the kinds, in the picker's order", () => {
  assert.deepEqual(KINDS, ["clear", "partly-cloudy", "cloudy", "fog", "rain", "thunderstorm", "snow", "hail"]);
});

test("kindScene: day and night only for clear and partly cloudy", () => {
  for (const [day, suffix] of [[true, "day"], [false, "night"]]) {
    assert.equal(kindScene("clear", null, day), `clear-${suffix}`);
    assert.equal(kindScene("partly-cloudy", null, day), `partly-cloudy-${suffix}`);
    for (const k of ["cloudy", "fog", "thunderstorm", "snow", "hail"]) {
      assert.equal(kindScene(k, null, day), k);
    }
  }
});

test("kindScene: heavy rain is its own scene", () => {
  assert.equal(kindScene("rain", null, true), "rain");
  assert.equal(kindScene("rain", "light", true), "rain");
  assert.equal(kindScene("rain", "moderate", false), "rain");
  assert.equal(kindScene("rain", "heavy", true), "heavy-rain");
  assert.equal(kindScene("rain", undefined, true), "rain");
});

test("kindScene: unknown kinds show nothing of their own", () => {
  for (const k of ["sunny", "", null, undefined, "Rain", 3]) assert.equal(kindScene(k, null, true), null);
});

test("sceneKind: the scenes a report can name", () => {
  const want = {
    "clear-day": ["clear", null], "clear-night": ["clear", null],
    "partly-cloudy-day": ["partly-cloudy", null], "partly-cloudy-night": ["partly-cloudy", null],
    cloudy: ["cloudy", null], fog: ["fog", null], rain: ["rain", null], "heavy-rain": ["rain", "heavy"],
    thunderstorm: ["thunderstorm", null], snow: ["snow", null], hail: ["hail", null],
  };
  for (const [scene, [kind, intensity]] of Object.entries(want)) {
    assert.deepEqual(sceneKind(scene), { kind, intensity }, scene);
  }
});

test("sceneKind: scenes without a kind can't be confirmed", () => {
  for (const s of ["wind", "sleet", "none", "", null, undefined, "storm"]) assert.equal(sceneKind(s), null, String(s));
});

test("kindScene and sceneKind agree", () => {
  for (const kind of KINDS) {
    for (const intensity of kind === "rain" ? [null, "heavy"] : [null]) {
      for (const day of [true, false]) {
        assert.deepEqual(sceneKind(kindScene(kind, intensity, day)), { kind, intensity });
      }
    }
  }
});

// [lat, lon, UTC time, sun up]: at least 15 min from sunrise/sunset (NOAA
// times, checked against published ones for Berlin and Sydney).
const SUN = [
  [52.52, 13.405, "2026-06-21T02:20:00Z", false], [52.52, 13.405, "2026-06-21T03:10:00Z", true],
  [52.52, 13.405, "2026-06-21T19:10:00Z", true], [52.52, 13.405, "2026-06-21T19:55:00Z", false],
  [52.52, 13.405, "2026-12-21T06:50:00Z", false], [52.52, 13.405, "2026-12-21T07:40:00Z", true],
  [52.52, 13.405, "2026-12-21T14:30:00Z", true], [52.52, 13.405, "2026-12-21T15:20:00Z", false],
  [52.52, 13.405, "2026-09-30T10:50:00Z", true], [52.52, 13.405, "2026-09-30T20:50:00Z", false],
  [69.65, 18.96, "2026-06-21T00:00:00Z", true], [69.65, 18.96, "2026-06-21T12:00:00Z", true],   // midnight sun
  [69.65, 18.96, "2026-12-21T11:00:00Z", false],                                                  // polar night
  [-33.87, 151.21, "2026-06-21T02:00:00Z", true], [-33.87, 151.21, "2026-06-21T12:00:00Z", false],
  [-0.18, -78.47, "2026-03-20T11:00:00Z", false], [-0.18, -78.47, "2026-03-20T11:40:00Z", true],
  [-0.18, -78.47, "2026-03-20T23:00:00Z", true], [-0.18, -78.47, "2026-03-20T23:50:00Z", false],
  [61.22, -149.9, "2026-01-15T00:30:00Z", true], [61.22, -149.9, "2026-01-15T02:00:00Z", false],
  [61.22, -149.9, "2026-01-15T18:30:00Z", false], [61.22, -149.9, "2026-01-15T19:30:00Z", true],
  [21.31, -157.86, "2026-10-07T04:00:00Z", true], [21.31, -157.86, "2026-10-07T04:40:00Z", false],
];

test("isDay: sunrise and sunset around the world", () => {
  for (const [lat, lon, iso, up] of SUN) {
    assert.equal(isDay(lat, lon, new Date(iso)), up, `${lat},${lon} ${iso}`);
  }
});
