// The clock change (test-suite analysis 3.3, before 2026-10-25): Europe/Berlin goes
// back from 03:00 CEST to 02:00 CET on 2026-10-25 and forward on 2027-03-28. The
// backend is UTC-only; the page formats every time with Intl in the location's zone
// (fmtTime) and decides day/night from the UTC instant (isDay), so both must stay
// right across the change. Run: node --test rust/uitest/unit/
import { test } from "node:test";
import assert from "node:assert/strict";
import { fmtTime } from "../../../app/static/format.js";
import { isDay } from "../../../app/static/reportkind.js";

const norm = (s) => s.replace(/[   ]/g, " ");
const TZ = "Europe/Berlin";
const BERLIN = [52.52, 13.405];

test("fmtTime: autumn, 02:00-03:00 happens twice", () => {
  const de = (iso) => norm(fmtTime(iso, "de-DE", TZ));
  assert.equal(de("2026-10-24T23:30:00Z"), "1:30");
  assert.equal(de("2026-10-25T00:30:00Z"), "2:30"); // CEST
  assert.equal(de("2026-10-25T01:30:00Z"), "2:30"); // CET: the same wall time again
  assert.equal(de("2026-10-25T02:30:00Z"), "3:30");
  assert.equal(norm(fmtTime("2026-10-25T01:30:00Z", "en-US", TZ)), "2:30 AM");
});

test("fmtTime: spring, 02:00-03:00 is skipped", () => {
  const de = (iso) => norm(fmtTime(iso, "de-DE", TZ));
  assert.equal(de("2027-03-28T00:30:00Z"), "1:30"); // CET
  assert.equal(de("2027-03-28T01:30:00Z"), "3:30"); // CEST
});

test("isDay: Berlin around sunrise and sunset on both sides of the change", () => {
  // sunrise about 05:50 UTC, sunset about 15:40-15:45 UTC on 24-26 Oct 2026
  for (const day of ["2026-10-24", "2026-10-25", "2026-10-26"]) {
    assert.equal(isDay(...BERLIN, new Date(`${day}T05:10:00Z`)), false, `${day} 05:10Z`);
    assert.equal(isDay(...BERLIN, new Date(`${day}T06:30:00Z`)), true, `${day} 06:30Z`);
    assert.equal(isDay(...BERLIN, new Date(`${day}T15:00:00Z`)), true, `${day} 15:00Z`);
    assert.equal(isDay(...BERLIN, new Date(`${day}T16:25:00Z`)), false, `${day} 16:25Z`);
  }
});
