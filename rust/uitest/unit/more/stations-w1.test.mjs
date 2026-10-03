// Step W1 (the stations): the map geometry's pure helpers (format.js).
// The marks are drawn at their bearing from the location (north is up) and
// at a distance proportional to the real distance, one mark per DWD station
// id (Now's station and an observation station with the same id merge).
import { test } from "node:test";
import assert from "node:assert/strict";
import { STRINGS, t } from "../../../../app/static/i18n.js";
import { stationOffsetKm, stationMarks } from "../../../../app/static/format.js";

// The recorded Berlin data (rust/contract/golden/live.json): the location,
// Now's station and the two observation stations, nearest first.
const BERLIN = { lat: 52.52, lon: 13.405 };
const NOW_STATION = {
  name: "Berlin-Tempelhof", distance_m: 5837, lat: 52.4676, lon: 13.402,
  height_m: 47.7, dwd_station_id: "00433",
};
const OBS_STATIONS = [
  { name: "Berlin-Friedrichshain/Spree", distance_m: 1860, lat: 52.51, lon: 13.427, dwd_station_id: "17473", hours: 37 },
  { name: "BERLIN-TEMPELHOF", distance_m: 5576, lat: 52.47, lon: 13.4, dwd_station_id: "00433", hours: 10 },
];

test("W1: stationOffsetKm gives the contract's bearings (north is up)", () => {
  const tempelhof = stationOffsetKm(BERLIN, NOW_STATION);
  assert.ok(Math.abs(tempelhof.bearing - 182) <= 1, `Tempelhof's bearing ${tempelhof.bearing}, expected about 182 (south)`);
  const fries = stationOffsetKm(BERLIN, OBS_STATIONS[0]);
  assert.ok(Math.abs(fries.bearing - 127) <= 1, `Friedrichshain's bearing ${fries.bearing}, expected about 127 (south-east)`);
  // the cardinal points: 0 north, 90 east, 180 south, 270 west
  assert.equal(stationOffsetKm({ lat: 52, lon: 13 }, { lat: 52.01, lon: 13 }).bearing, 0);
  assert.equal(stationOffsetKm({ lat: 52, lon: 13 }, { lat: 52, lon: 13.01 }).bearing, 90);
  assert.equal(stationOffsetKm({ lat: 52, lon: 13 }, { lat: 51.99, lon: 13 }).bearing, 180);
  assert.equal(stationOffsetKm({ lat: 52, lon: 13 }, { lat: 52, lon: 12.99 }).bearing, 270);
  // a bearing stays in 0..360 and the same point is 0 km away
  const same = stationOffsetKm(BERLIN, { lat: 52.52, lon: 13.405 });
  assert.equal(same.km, 0);
});

test("W1: stationOffsetKm's distances match the API's within the flat approximation", () => {
  // the API's distances (5837 m and 1860 m) against the flat dx/dy
  for (const [station, apiKm] of [[NOW_STATION, 5.837], [OBS_STATIONS[0], 1.86]]) {
    const { km } = stationOffsetKm(BERLIN, station);
    assert.ok(Math.abs(km - apiKm) / apiKm <= 0.02, `${station.name}: ${km} km, expected about ${apiKm} km`);
  }
});

test("W1: stationOffsetKm is null without usable coordinates", () => {
  assert.equal(stationOffsetKm(null, { lat: 52, lon: 13 }), null);
  assert.equal(stationOffsetKm(BERLIN, null), null);
  assert.equal(stationOffsetKm(BERLIN, {}), null);
  assert.equal(stationOffsetKm(BERLIN, { lat: "no", lon: 13 }), null);
  assert.equal(stationOffsetKm({ lat: 52 }, { lat: 52, lon: 13 }), null);
  // the config's location keys (latitude/longitude) work too
  const { km } = stationOffsetKm({ latitude: 52.52, longitude: 13.405 }, NOW_STATION);
  assert.ok(Math.abs(km - 5.8) / 5.8 <= 0.02, `km ${km}`);
});

test("W1: stationMarks merges Now's and the observation stations by DWD id", () => {
  const marks = stationMarks(NOW_STATION, OBS_STATIONS);
  assert.deepEqual(
    marks.map((m) => m.id),
    ["00433", "17473"],
    "BERLIN-TEMPELHOF is Now's station: one mark per DWD id, Now's first"
  );
  assert.deepEqual(marks[0], {
    id: "00433", name: "Berlin-Tempelhof", lat: 52.4676, lon: 13.402, distance_m: 5837, isNow: true,
  }, "the Now's station's coordinates and name win the merged mark");
  assert.equal(marks[1].name, "Berlin-Friedrichshain/Spree");
  assert.equal(marks[1].isNow, false);
});

test("W1: stationMarks keeps the observation order and skips id-less entries", () => {
  assert.deepEqual(stationMarks(null, OBS_STATIONS).map((m) => m.id), ["17473", "00433"]);
  assert.deepEqual(stationMarks(NOW_STATION, []).map((m) => m.id), ["00433"]);
  assert.deepEqual(stationMarks(null, null), []);
  assert.deepEqual(stationMarks(null, []), []);
  assert.deepEqual(stationMarks({ name: "no id" }, [{ name: "also none" }]), []);
  // a numeric station id is a mark too, and duplicate ids collapse
  // (the API sends the ids as strings, "00433"; 433 is a different id)
  const both = stationMarks({ dwd_station_id: 433, name: "A" }, [{ dwd_station_id: "433", name: "B" }]);
  assert.equal(both.length, 1);
  assert.equal(both[0].id, "433");
  assert.equal(
    stationMarks({ dwd_station_id: "00433", name: "A" }, [{ dwd_station_id: 433, name: "B" }]).length,
    2
  );
});

test("W1: the new texts exist in both languages and fill their placeholders", () => {
  for (const key of [
    "now.station", "now.fallback", "details.stations", "station.hours", "map.aria", "map.north", "map.scale",
  ]) {
    for (const lang of ["en", "de"]) {
      const value = STRINGS[lang][key];
      assert.ok(typeof value === "string" && value.trim() !== "", `${lang}.${key} is empty`);
    }
  }
  assert.equal(t("en", "now.station", { name: "Berlin-Tempelhof", km: "5.8" }), "Station Berlin-Tempelhof · 5.8 km");
  assert.equal(t("de", "now.station", { name: "Berlin-Tempelhof", km: "5,8" }), "Station Berlin-Tempelhof · 5,8 km");
  assert.equal(t("en", "now.fallback", { name: "Potsdam" }), "from Potsdam");
  assert.equal(t("de", "now.fallback", { name: "Potsdam" }), "von Potsdam");
  assert.equal(t("en", "station.hours", { n: "37" }), "37 h");
  assert.equal(t("de", "station.hours", { n: "37" }), "37 h");
  assert.equal(t("en", "map.scale", { km: "2" }), "2 km");
  assert.equal(t("de", "map.scale", { km: "2" }), "2 km");
});
