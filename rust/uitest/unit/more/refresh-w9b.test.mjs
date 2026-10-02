// Step W9b: the page keeps refreshing. The reload delay is a pure
// function (format.js nextLoadDelay): at the latest every 60 s, sooner
// 10 s after a scheduled backend refresh, bad jobs skipped. The timing
// constants and the place line's "unreachable" text (shown while a failed
// /api/config is retried every 10 s) are pinned here.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  CONFIG_RETRY_MS, PAGE_RELOAD_AFTER_REFRESH_MS, PAGE_REFRESH_MS, nextLoadDelay,
} from "../../../../app/static/format.js";
import { STRINGS } from "../../../../app/static/i18n.js";

const REFRESH = 60_000;
const AFTER = 10_000;
const T0 = Date.parse("2026-09-30T10:50:00Z");
const iso = (seconds) => new Date(T0 + seconds * 1000).toISOString();

test("W9b: the timing constants (60 s at the latest, 10 s after a refresh, 10 s config retry)", () => {
  assert.equal(PAGE_REFRESH_MS, 60_000);
  assert.equal(PAGE_RELOAD_AFTER_REFRESH_MS, 10_000);
  assert.equal(CONFIG_RETRY_MS, 10_000);
});

test("W9b: without jobs the reload waits the full 60 s", () => {
  assert.equal(nextLoadDelay(null, T0, REFRESH, AFTER), REFRESH);
  assert.equal(nextLoadDelay(undefined, T0, REFRESH, AFTER), REFRESH);
  assert.equal(nextLoadDelay({}, T0, REFRESH, AFTER), REFRESH);
});

test("W9b: a refresh 30 s ahead reloads 10 s after it", () => {
  const jobs = { radar: { next_run_utc: iso(30) } };
  assert.equal(nextLoadDelay(jobs, T0, REFRESH, AFTER), 40_000);
});

test("W9b: the reload is 10 s after the refresh, capped at 60 s from now", () => {
  assert.equal(nextLoadDelay({ radar: { next_run_utc: iso(55) } }, T0, REFRESH, AFTER), REFRESH); // 65 s -> 60 s
  assert.equal(nextLoadDelay({ radar: { next_run_utc: iso(50) } }, T0, REFRESH, AFTER), REFRESH); // 60 s exactly
  assert.equal(nextLoadDelay({ radar: { next_run_utc: iso(49) } }, T0, REFRESH, AFTER), 59_000);
  // a refresh that finished 5 s ago: 10 s after it, i.e. 5 s from now
  assert.equal(nextLoadDelay({ radar: { next_run_utc: iso(-5) } }, T0, REFRESH, AFTER), 5_000);
  // a refresh more than 10 s in the past: wait the full 60 s
  assert.equal(nextLoadDelay({ radar: { next_run_utc: iso(-20) } }, T0, REFRESH, AFTER), REFRESH);
});

test("W9b: the soonest of several jobs wins", () => {
  const jobs = { radar: { next_run_utc: iso(55) }, models: { next_run_utc: iso(20) } };
  assert.equal(nextLoadDelay(jobs, T0, REFRESH, AFTER), 30_000);
});

test("W9b: bad jobs are skipped, not thrown on", () => {
  const jobs = {
    radar: null,
    models: {},
    forecast: { next_run_utc: "not a date" },
    ensemble: { next_run_utc: null },
    now: 42,
  };
  assert.equal(nextLoadDelay(jobs, T0, REFRESH, AFTER), REFRESH);
  assert.equal(nextLoadDelay("nope", T0, REFRESH, AFTER), REFRESH);
  assert.equal(nextLoadDelay([iso(30)], T0, REFRESH, AFTER), REFRESH); // array: no next_run_utc inside
  // one good job among the bad ones still counts
  const mixed = { ...jobs, models: { next_run_utc: iso(30) } };
  assert.equal(nextLoadDelay(mixed, T0, REFRESH, AFTER), 40_000);
});

test("W9b: the place line's unreachable texts (while /api/config is retried)", () => {
  assert.equal(STRINGS.en["location.unreachable"], "Can't reach the app, retrying…");
  assert.equal(STRINGS.de["location.unreachable"], "App nicht erreichbar, neuer Versuch …");
  // and it is its own text: not the "no location set" one
  assert.notEqual(STRINGS.en["location.unreachable"], STRINGS.en["location.unset"]);
  assert.notEqual(STRINGS.de["location.unreachable"], STRINGS.de["location.unset"]);
});
