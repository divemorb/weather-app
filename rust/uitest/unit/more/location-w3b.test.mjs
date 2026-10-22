// Step W3b: the top bar shows the city, the details page the full place:
// the label's lines, then "52.522, 13.414 · Europe/Berlin".
import { test } from "node:test";
import assert from "node:assert/strict";
import { locationText, locationDetail } from "../../../../app/static/format.js";

test("W3b: the bar shows the city: the label's last line without the postcode", () => {
  assert.equal(locationText(null), "");
  assert.equal(locationText({ label: "Berlin" }), "Berlin");
  assert.equal(locationText({ label: "Dircksenstraße 2\n10179 Berlin" }), "Berlin");
  assert.equal(locationText({ label: "Alexanderplatz\nBerlin" }), "Berlin");
  assert.equal(locationText({ label: "Downing Street 10\nSW1A 2AA London" }), "London");
  // a label before REQ_LOC_5 (one line) stays as it is (REQ_LOC_6)
  assert.equal(
    locationText({ label: "Alexanderplatz, Spandauer Vorstadt, Mitte, Berlin, Deutschland" }),
    "Alexanderplatz, Spandauer Vorstadt, Mitte, Berlin, Deutschland"
  );
  // a last line that is only a postcode keeps it
  assert.equal(locationText({ label: "Hauptstraße 1\n12345" }), "12345");
  // an empty label means "no label": coordinates, as in the live scenarios
  assert.equal(locationText({ label: "", latitude: 52.52, longitude: 13.405 }), "52.520, 13.405");
  assert.equal(locationText({ label: "", latitude: -33.8688, longitude: 151.219 }), "-33.869, 151.219");
  // no coordinates at all: nothing to show
  assert.equal(locationText({ label: "" }), "");
});

test("W3b: the details' place line is the coordinates and the time zone, with or without a label", () => {
  assert.equal(locationDetail(null), "");
  assert.equal(
    locationDetail({ label: "", latitude: 52.52, longitude: 13.405, timezone: "Europe/Berlin" }),
    "52.520, 13.405 · Europe/Berlin"
  );
  assert.equal(
    locationDetail({ label: "Dircksenstraße 2\n10179 Berlin", latitude: 52.522, longitude: 13.414, timezone: "Europe/Berlin" }),
    "52.522, 13.414 · Europe/Berlin"
  );
});

test("W3b: the parts are independent — no time zone, coordinates only; no coordinates, the zone only", () => {
  assert.equal(locationDetail({ label: "Berlin", latitude: 52.52, longitude: 13.405 }), "52.520, 13.405");
  assert.equal(locationDetail({ label: "", timezone: "Europe/Berlin" }), "Europe/Berlin");
  assert.equal(locationDetail({ label: "" }), "");
});
