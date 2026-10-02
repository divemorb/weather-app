// Step W3b: the place line and the muted detail under it (format.js).
// The detail is the time zone; when the place shows a label, the
// coordinates come before it: "52.522, 13.414 · Europe/Berlin".
import { test } from "node:test";
import assert from "node:assert/strict";
import { locationText, locationDetail } from "../../../../app/static/format.js";

test("W3b: the place shows the label, else the coordinates to three decimals", () => {
  assert.equal(locationText(null), "");
  assert.equal(locationText({ label: "Berlin" }), "Berlin");
  assert.equal(
    locationText({ label: "Alexanderplatz, Spandauer Vorstadt, Mitte, Berlin, Deutschland" }),
    "Alexanderplatz, Spandauer Vorstadt, Mitte, Berlin, Deutschland"
  );
  // an empty label means "no label": coordinates, as in the live scenarios
  assert.equal(locationText({ label: "", latitude: 52.52, longitude: 13.405 }), "52.520, 13.405");
  assert.equal(locationText({ label: "", latitude: -33.8688, longitude: 151.219 }), "-33.869, 151.219");
  // no coordinates at all: nothing to show
  assert.equal(locationText({ label: "" }), "");
});

test("W3b: the detail is the time zone, coordinates first with a label", () => {
  assert.equal(locationDetail(null), "");
  assert.equal(
    locationDetail({ label: "", latitude: 52.52, longitude: 13.405, timezone: "Europe/Berlin" }),
    "Europe/Berlin"
  );
  assert.equal(
    locationDetail({ label: "Berlin", latitude: 52.52, longitude: 13.405, timezone: "Europe/Berlin" }),
    "52.520, 13.405 · Europe/Berlin"
  );
  assert.equal(
    locationDetail({
      label: "Alexanderplatz, Spandauer Vorstadt, Mitte, Berlin, Deutschland",
      latitude: 52.522, longitude: 13.414, timezone: "Europe/Berlin",
    }),
    "52.522, 13.414 · Europe/Berlin"
  );
});

test("W3b: the parts are independent — no time zone, coordinates only", () => {
  assert.equal(locationDetail({ label: "Berlin", latitude: 52.52, longitude: 13.405 }), "52.520, 13.405");
  // no label and no time zone: nothing to show
  assert.equal(locationDetail({ label: "", latitude: 52.52, longitude: 13.405 }), "");
});
