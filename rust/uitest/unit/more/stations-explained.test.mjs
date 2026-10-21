// The stations section's pure helpers (format.js): the compass point of a
// bearing (a row's direction from the place) and one row per DWD station
// (Bright Sky can list one station under several sources).
import { test } from "node:test";
import assert from "node:assert/strict";
import { compassPoint, mergeStations } from "../../../../app/static/format.js";

test("compassPoint: the nearest of the eight points, clockwise from north", () => {
  assert.deepEqual([0, 22, 23, 45, 90, 127, 182, 225, 270, 315, 337, 338, 360].map(compassPoint),
    [0, 0, 1, 1, 2, 3, 4, 5, 6, 7, 7, 0, 0]);
  assert.equal(compassPoint(-45), 7); // negative bearings wrap
  assert.equal(compassPoint("90"), 2); // a numeric string counts
});

test("mergeStations: one entry per DWD station id, the first one's name and place, the most hours", () => {
  const merged = mergeStations([
    { dwd_station_id: "00403", name: "Berlin-Dahlem", distance_m: 4507, lat: 52.4537, lon: 13.3017, hours: 28 },
    { dwd_station_id: "00403", name: "BERLIN-DAHLEM", distance_m: 5345, lat: 52.45, lon: 13.3, hours: 19 },
    { dwd_station_id: "00433", name: "Tempelhof", distance_m: 5800, hours: 10 },
    { dwd_station_id: "00433", name: "TEMPELHOF", distance_m: 6000, hours: 37 },
  ]);
  assert.deepEqual(merged, [
    { dwd_station_id: "00403", name: "Berlin-Dahlem", distance_m: 4507, lat: 52.4537, lon: 13.3017, hours: 28 },
    { dwd_station_id: "00433", name: "Tempelhof", distance_m: 5800, hours: 37 },
  ]);
});

test("mergeStations: entries without an id stay, junk is skipped, the input is not changed", () => {
  const input = [{ name: "A", hours: 1 }, null, "x", { name: "B", hours: 2 }, { dwd_station_id: 7, hours: null },
    { dwd_station_id: "7", hours: 3 }];
  const before = JSON.stringify(input);
  assert.deepEqual(mergeStations(input),
    [{ name: "A", hours: 1 }, { name: "B", hours: 2 }, { dwd_station_id: 7, hours: 3 }]);
  assert.equal(JSON.stringify(input), before);
  assert.deepEqual(mergeStations(null), []);
});
