/* Refresh countdown state + renderers (split out of app.js in step 8a).
 *
 * Loaded before app.js via a <script> tag; exposes the countdown state
 * (schedule, loadTimer, nextLoadAt, loadDelayMs), the constants REFRESH_MS /
 * RELOAD_AFTER_REFRESH_MS, and the functions applySchedule(), serverNow(),
 * scheduleNextLoad(), fmtCountdown(), fmtEvery(), setCountdown(),
 * renderJobCountdown(), renderCountdowns().
 *
 * Only its own names may be used at load time (this script runs before
 * app.js); the shared helpers from app.js (load, fmtClock, els) are used
 * at call time.
 */
"use strict";

const REFRESH_MS = 60_000; // reload at least this often
// Reload this long after a scheduled backend refresh, so new data shows up
// right away (a refresh normally finishes within a few seconds).
const RELOAD_AFTER_REFRESH_MS = 10_000;

/* ------------------------------------------------------------------ *
 * Refresh countdown: next backend refresh per job + next page reload
 * ------------------------------------------------------------------ */
let schedule = null; // { offsetMs, jobs } from /api/schedule
let loadTimer = null;
let nextLoadAt = 0; // Date.now() ms of the next page reload
let loadDelayMs = REFRESH_MS;

function applySchedule(s) {
  if (!s || !s.jobs) {
    schedule = null;
    return;
  }
  // server clock minus browser clock, so the countdown matches the server
  const offsetMs = Date.parse(s.server_time_utc) - Date.now();
  schedule = { offsetMs: isNaN(offsetMs) ? 0 : offsetMs, jobs: s.jobs };
}

function serverNow() {
  return Date.now() + (schedule ? schedule.offsetMs : 0);
}

/* Next page reload: every REFRESH_MS, or sooner right after a backend refresh. */
function scheduleNextLoad() {
  clearTimeout(loadTimer);
  let delay = REFRESH_MS;
  if (schedule) {
    for (const job of Object.values(schedule.jobs)) {
      if (!job.next_run_utc) continue;
      const until = Date.parse(job.next_run_utc) - serverNow() + RELOAD_AFTER_REFRESH_MS;
      if (until > 0 && until < delay) delay = until;
    }
  }
  loadDelayMs = delay;
  nextLoadAt = Date.now() + delay;
  loadTimer = setTimeout(async () => {
    await load();
    scheduleNextLoad();
  }, delay);
}

function fmtCountdown(ms) {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

function fmtEvery(minutes) {
  if (minutes >= 60 && minutes % 60 === 0) {
    return minutes === 60 ? "hourly" : `every ${minutes / 60} h`;
  }
  return `every ${minutes} min`;
}

/* One countdown tile: big "m:ss", a note line, and an elapsed-time bar. */
function setCountdown(el, { count, note, title, fraction, due }) {
  if (!el) return;
  el.querySelector(".refresh-count").textContent = count;
  el.querySelector(".refresh-note").textContent = note;
  el.querySelector(".refresh-bar i").style.width = `${Math.round(Math.min(1, Math.max(0, fraction)) * 100)}%`;
  el.classList.toggle("due", !!due);
  el.title = title;
}

function renderJobCountdown(el, job, upstream) {
  if (!job || !job.next_run_utc) {
    setCountdown(el, { count: "—", note: `${upstream} · not scheduled`, title: "", fraction: 0 });
    return;
  }
  const nextRun = Date.parse(job.next_run_utc);
  const ms = nextRun - serverNow();
  const due = ms <= 0;
  setCountdown(el, {
    count: due ? "updating…" : fmtCountdown(ms),
    note: `${upstream} · ${fmtEvery(job.interval_minutes)}`,
    title: `Next refresh at ${fmtClock(job.next_run_utc)} local (${fmtEvery(job.interval_minutes)})`,
    fraction: 1 - ms / (job.interval_minutes * 60_000),
    due,
  });
}

function renderCountdowns() {
  if (!schedule) {
    els.refreshStrip.hidden = true;
    return;
  }
  els.refreshStrip.hidden = false;
  renderJobCountdown(els.refreshRadar, schedule.jobs.radar, "DWD via Bright Sky");
  renderJobCountdown(els.refreshModels, schedule.jobs.models, "Open-Meteo");
  const ms = nextLoadAt - Date.now();
  setCountdown(els.refreshPage, {
    count: ms <= 0 ? "reloading…" : fmtCountdown(ms),
    note: loadDelayMs < REFRESH_MS ? "reloads right after the next update" : "reloads from the app's cache every minute",
    title: "The page reads the app's cache; the app itself polls the weather services on the schedule shown.",
    fraction: 1 - ms / loadDelayMs,
    due: ms <= 0,
  });
}
