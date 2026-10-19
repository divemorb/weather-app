# Requirements

What the app must do and why. Each requirement has an ID (`REQ_<AREA>_<n>`), one or two sentences, and its source: the user's decision with its date, the upstream's terms, or the original scope (`SCOPE.md`, 2026-09-30). Numbers that are settings name their `weather.yaml` key; the value given is the default.

Each requirement's `*Proof:*` line names the tests that prove it: `cargo:`, `contract:` and `ui:` items are cargo tests, contract cases and UI checks, `gate:` items are the gates (fmt, clippy, sizes, comment_rules, doc_check, contract, faults, trace), and the marks `manual:`, `review:`, `scope:` and `todo:` stand in where no test can exist or is still missing; `refined` defers to the requirements that refine it. `*Refines:*` names the requirement a child makes concrete. `python3 rust/contract/trace.py` checks the links (`--report` for the overview).

## Purpose and users (GEN)

- **REQ_GEN_1** The app answers one question for one place: will it rain here in the next 60 minutes. *Source: scope.*
- **REQ_GEN_2** One household, one location; the person running it can paste terminal commands but needn't be a developer. *Source: scope.*
- **REQ_GEN_3** It uses only free data sources that need no account or key, for non-commercial use. *Source: scope; Open-Meteo's and Bright Sky's terms.*
- **REQ_GEN_4** **The page explains itself**: every value shown says what it is and where it comes from (which source decided, how a number was derived). *Source: the user, 2026-10-04.*

## The rain probability (PROB)

- **REQ_PROB_1** The chance of rain in the next 60 minutes is shown in percent, with a one-line explanation of how it was derived. *Source: scope.*
  *Proof:* `cargo:aggregator::rain_tests::get_rain_probability_all_signals`; `ui:*/*/rain-probability`
  *Refines:* REQ_GEN_1, REQ_GEN_4
- **REQ_PROB_2** Three signals, combined with weights (`probability.weights`: radar 0.5, models 0.3, ensemble 0.2): the radar nowcast, the share of the forecast models, the share of the ensemble members. *Source: scope.*
  *Proof:* `cargo:probability::combine::tests::combine_all_signals_weighted`; `ui:*/*/details-weights`
- **REQ_PROB_3** Radar signal: any rain cell (≥ `radar_cell_rain_threshold_mm`, 0.05 mm) within `radar.radius_km` (1 km) of the location in the next hour. *Source: scope.*
  *Proof:* `cargo:probability::tests::radar_has_local_rain_scans_all_frames`; `ui:*/*/details-signals`
- **REQ_PROB_4** Models signal: the share of the configured models (`models.forecast`: ICON-D2, ICON-EU, ECMWF IFS, GFS, AROME, UKMO) forecasting more than `model_rain_threshold_mm` (0.1 mm) in the next hour. *Source: scope.*
  *Proof:* `cargo:probability::tests::model_rain_signal_share`; `ui:*/*/details-signals`
- **REQ_PROB_5** Ensemble signal: the share of the 50 ECMWF ensemble members forecasting rain. *Source: scope.*
  *Proof:* `cargo:probability::combine::tests::ensemble_vote_share`; `ui:*/*/details-signals`
- **REQ_PROB_6** Outside the DWD radar's coverage (Germany) the radar weight is dropped and the others are renormalized; the app works anywhere. *Source: scope.*
  *Proof:* `cargo:aggregator::rain_tests::get_rain_probability_without_radar`; `ui:errors/*/radar-unavailable`
- **REQ_PROB_7** Optional accuracy weighting (off by default): each model's vote counts by its hit rate at this location, but only once every voting model has `accuracy.min_samples` (48) compared hours; until then the plain vote. *Source: scope.*
  *Proof:* `cargo:aggregator::rain_tests::get_rain_probability_accuracy_weights_applied`; `cargo:probability::combine::tests::weighted_signal_gate_falls_back_below_min_samples`; `ui:*/*/details-weighting`

## Data handling (DATA)

- **REQ_DATA_1** The upstream services are never called per page load: a scheduler refreshes a local cache (radar every 5 min, models every 60 min), the page reads the cache. A refresh also runs at startup and after a location change. *Source: scope.*
  *Proof:* `cargo:scheduler::tests::scheduled_jobs_run_refreshes_on_event_loop`; `cargo:aggregator::tests::refresh_radar_caches_payloads`; `contract:*:api/schedule`
- **REQ_DATA_2** A failing source never blocks the app: the last good data is shown with its age; a source is stale after 10 min (radar) or 120 min (models). *Source: scope.*
  *Proof:* refined; `cargo:aggregator::tests::refresh_radar_tolerates_one_failing_source`; `cargo:aggregator::tests::source_status_marks_stale`
- **REQ_DATA_3** Upstream data is untrusted: malformed, oversized or deeply nested responses are a source error, never a crash. *Source: scope.*
  *Proof:* `cargo:upstream::tests::fetch_deeply_nested_json_is_source_error`; `cargo:upstream::tests::fetch_streamed_oversize_is_source_error`; `cargo:upstream::tests::fetch_broken_json_is_source_error`
- **REQ_DATA_4** Forecasts are stored per model and hour and compared with the observations as they arrive; hours missed while the app was down are caught up (last 48 h). *Source: scope.*
  *Proof:* `cargo:aggregator::tests::refresh_models_writes_forecast_history`; `cargo:aggregator::backfill_tests::refresh_models_triggers_backfill`; `contract:*:api/model-accuracy`
- **REQ_DATA_5** UTC everywhere in the backend; only the page converts to the display time zone. *Source: scope.*
  *Proof:* `cargo:times::tests::parse_iso_offset_normalized_to_utc`; `contract:*:api/sources`
- **REQ_DATA_6** Address search follows the Nominatim usage policy: at most one request per second, results cached, a search only on explicit request (no search-as-you-type). *Source: Nominatim's policy.*
  *Proof:* `cargo:geocode::tests::search_throttles_two_different_queries`; `cargo:geocode::tests::search_caches_identical_query_including_case`; `ui:wizard/*/search`

## Model accuracy (ACC)

- **REQ_ACC_1** Per model, over the last `accuracy.window_days` (30): compared hours, hits, misses, false alarms, hit rate, mean error; rain means more than 0.1 mm in the hour. *Source: scope.*
  *Proof:* `cargo:aggregator::read_tests::get_model_accuracy_scores_window_only`; `contract:*:api/model-accuracy`
- **REQ_ACC_2** Models with fewer than 48 compared hours are marked as not having enough data yet. *Source: scope.*
  *Proof:* `contract:accuracy-gate:api/model-accuracy`; `ui:accuracy/*/accuracy-table`
- **REQ_ACC_3** The table explains its columns in plain words under it; the column names are plain ("Hits", "Misses", "False alarms", "Hit rate", "Avg. error"). *Source: the user, 2026-10-02.*
  *Proof:* `ui:accuracy/*/accuracy-head`; `ui:accuracy/*/accuracy-note`
  *Refines:* REQ_GEN_4
- **REQ_ACC_4** It names the stations its observations came from (name, distance, hours). *Source: the user, 2026-10-03.*
  *Proof:* `ui:live/*/observation-stations`
  *Refines:* REQ_GEN_4

## Location (LOC)

- **REQ_LOC_1** On the first start a setup wizard asks for the place: an address search, or latitude and longitude, plus the time zone. The place can be changed later from the page. *Source: scope.*
  *Proof:* `ui:unconfigured/*/setup-visible`; `ui:wizard/*/save`; `ui:wizard/*/change`
  *Refines:* REQ_GEN_2
- **REQ_LOC_2** The place is runtime state in the app's database, not in the code or the repository; environment variables or `weather.yaml` may seed it on the first start. *Source: scope.*
  *Proof:* `cargo:location::tests::startup_adopts_cfg_location_into_db`; `cargo:config::tests::env_location_without_yaml`; `cargo:config::tests::yaml_location_defaults_timezone`
- **REQ_LOC_3** Coordinates are rounded to 3 decimals (about 100 m) before they are stored. *Source: scope.*
  *Proof:* `cargo:location::tests::validate::into_location_rounds_to_three_decimals`; `contract:wizard:location/set-berlin`
- **REQ_LOC_4** A move of more than about 1 km (0.01° in latitude or longitude) deletes the cached data, the accuracy history and the user's reports of the old place: they would describe another place. *Source: scope; reports: the user, 2026-10-07.*
  *Proof:* `cargo:location::tests::moved_beyond_epsilon_is_a_move`; `cargo:aggregator::tests::set_location_moved_clears_location_data`; `cargo:store::reports::tests::clear_location_data_removes_every_report`
- **REQ_LOC_5** The place is shown as two short lines in German order, without quarter, state or country: `Street number` / `Postcode City` (from Nominatim's address details; fallbacks: the result's name, then its full name). Same order for every country. *Source: the user, 2026-10-12 (phone test P1).*
  *Proof:* `cargo:geocode::tests::short_label_matches_the_shared_table`; `ui:wizard/*/search-lines`; `ui:wizard/*/location-long`
- **REQ_LOC_6** A label stored before REQ_LOC_5 stays as it is until the user picks the place again; no automatic shortening (it would need the address details again). *Source: the user, 2026-10-12.*
  *Proof:* `cargo:location::tests::location_json_round_trip`; `ui:unit/location-w3b.test.mjs`

## The page (PAGE)

- **REQ_PAGE_1** The big view shows, top to bottom: the glance (the answer, the chance, the radar strip), Now, the next 24 hours. The technical parts are only in the detailed view (REQ_PAGE_4). *Source: the user, 2026-10-02.*
- **REQ_PAGE_2** **The big view is the default on every screen** (large type, one screen on desktop and tablet; on a phone one column that may scroll vertically). The detailed view is one button away. *Source: the user, 2026-10-04.*
- **REQ_PAGE_3** The view button is text that says where a click goes: "Details" in the big view, "Big view" in the detailed view (German "Details" / "Große Ansicht"); the choice is remembered per device. *Source: the user, 2026-10-05.*
- **REQ_PAGE_4** The detailed view shows only the details (signals, countdowns, sources, accuracy, stations), not the glance, Now or the chart again. *Source: the user, 2026-10-12 (phone test P2).*
- **REQ_PAGE_5** `?detailed` forces the detailed view; `?kiosk` forces the big view and locks it for a wall display (no view button, no place button, no report button). *Source: the user, 2026-10-02 and 2026-10-04.*
- **REQ_PAGE_6** English and German, following the browser's language; times in the place's time zone and the browser's time format, also on the days the clock changes; wind in km/h. *Source: the user, 2026-10-02; the clock change: 2026-10-13.*
- **REQ_PAGE_7** Light and dark theme: follows the system, a toggle in the top bar overrides it and is remembered. *Source: the user, 2026-10-02.*
- **REQ_PAGE_8** Every text keeps WCAG AA contrast (4.5:1, large text 3:1) against what is actually drawn behind it, in both themes, in every view and scene. *Source: the user, 2026-10-03 (glass tiles).*
- **REQ_PAGE_9** Works from 360 px wide without horizontal scrolling; buttons at least 24×24 px (the report's picture buttons 44×44). *Source: scope; the user, 2026-10-07.*
- **REQ_PAGE_10** No build step, no framework, no CDN, no images or fonts from outside: plain HTML, CSS and JavaScript; all of `app/static` at most 300 KB. *Source: scope; budget: the user, 2026-10-04.*
  *Refines:* REQ_PRIV_1
- **REQ_PAGE_11** Credits for every data source (DWD via Bright Sky, Open-Meteo, OpenStreetMap). *Source: the sources' terms.*
- **REQ_PAGE_12** Calm and minimal: lots of whitespace, one accent colour for rain, system fonts. *Source: the user, 2026-10-02.*
- **REQ_PAGE_13** A refresh that fails keeps the tile's last good values and says so: the tile shows that the update failed and the time of the data it still shows (English "Update failed – showing data from 14:05", German "Aktualisierung fehlgeschlagen – Daten von 14:05"); the next good refresh removes the note. Only a part that never loaded shows "not available". *Source: the user, 2026-10-18.*
  *Refines:* REQ_GEN_4, REQ_DATA_2

## The glance (GLANCE)

- **REQ_GLANCE_1** The answer in plain words ("No rain expected in the next hour", "Rain possible …", "Rain likely …"). *Source: the user, 2026-10-02.*
  *Refines:* REQ_GEN_1
- **REQ_GLANCE_2** The radar strip: 12 steps of 5 minutes, the strongest rain within the radius per step, time labels that don't overlap; its caption names the radius; a dry hour says so in a sentence. *Source: the user, 2026-10-02.*
  *Refines:* REQ_GEN_1, REQ_GEN_4
- **REQ_GLANCE_3** On a phone in the big view the headline takes at most two lines, as large as fits. *Source: the user, 2026-10-05.*
- **REQ_GLANCE_4** The "why" line under the answer says what the sky shows and who decided it (REQ_SKY_6). *Source: the user, 2026-10-04.*
  *Refines:* REQ_GEN_4

## Now (NOW)

- **REQ_NOW_1** Temperature, feels-like, wind and gusts, cloud cover, humidity, pressure, dew point, rain of the last hour, condition. *Source: scope.*
- **REQ_NOW_2** The station the values come from, with its distance ("Station Berlin-Tempelhof · 5.8 km"). *Source: the user, 2026-10-02/03.*
  *Refines:* REQ_GEN_4
- **REQ_NOW_3** A value that comes from another station (Bright Sky's fallback) is marked with that station's name. *Source: the user, 2026-10-03.*
  *Refines:* REQ_GEN_4

## The next 24 hours (CHART)

- **REQ_CHART_1** Hourly precipitation per model as a chart with a labelled y axis; a dry day says so instead of an empty chart. *Source: scope; the user, 2026-10-02.*

## Details (DETAILS)

- **REQ_DETAILS_1** The signals and the weights in use. *Source: scope.*
  *Refines:* REQ_GEN_4
- **REQ_DETAILS_2** Countdowns to the next radar and model refresh and the next page reload. *Source: scope.*
- **REQ_DETAILS_3** Each data source with its age, a stale mark and its last error. *Source: scope.*
  *Refines:* REQ_GEN_4
- **REQ_DETAILS_4** The model accuracy (REQ_ACC_1-4) and, in its own block, the accuracy against the user's reports (REQ_REPORT_8). *Source: scope; the user, 2026-10-07.*
- **REQ_DETAILS_5** A schematic map (no map tiles: privacy and CSP): the place in the middle, the stations by bearing and distance, the radar radius, a north arrow and a scale bar. *Source: the user, 2026-10-03.*
- **REQ_DETAILS_6** One failing part never empties the others. *Source: the user, 2026-10-02 (W9 review).*
  *Refines:* REQ_DATA_2

## The sky (SKY)

- **REQ_SKY_1** The background shows the current weather as an animation, behind the tiles, on every screen: clear (day, night), partly cloudy (day, night), cloudy, fog, wind, rain, heavy rain, sleet, snow, hail, thunderstorm. *Source: the user, 2026-10-03.*
- **REQ_SKY_2** The scene comes from the station's icon (Bright Sky), and from the radar at the place right now: rain on the radar shows rain (heavy rain from 0.2 mm per 5 minutes) even when the station reports dry. *Source: the user, 2026-10-03.*
- **REQ_SKY_3** **Rule B (the radar beats the station when it's dry)**: the weather station can be several kilometres away, the radar measures at the place itself. So when the station reports rain, sleet, snow or hail but the radar shows no rain at the place right now (its current 5-minute step is 0 mm), the sky shows cloudy instead. A thunderstorm from the station is always shown, as a warning: it can reach the place quickly, even while the radar is still dry there. Without radar data the station's report is shown as it is. *Source: the user, 2026-10-04.*
  *Refines:* REQ_SKY_2
- **REQ_SKY_4** The tiles are glass: the sky can be seen through them (no blur), every text keeps REQ_PAGE_8. *Source: the user, 2026-10-03/04.*
- **REQ_SKY_5** With "reduce motion" the sky is a still picture; lightning flashes at most once per 3 seconds (WCAG 2.3.1). *Source: the user, 2026-10-03; WCAG.*
- **REQ_SKY_6** The "why" line names the source: the station and its distance, the nearest station, the radar (with rule B: what the station reports), or the user's report and its time. *Source: the user, 2026-10-04 and 2026-10-07.*
  *Refines:* REQ_GLANCE_4
- **REQ_SKY_7** A fresh user report (REQ_REPORT_6) decides the sky. *Source: the user, 2026-10-07.*
  *Refines:* REQ_SKY_2

## The user's reports, "Stimmt nicht?" (REPORT)

- **REQ_REPORT_1** When reality and forecast differ, the user can record the real weather, phone-first: the Now tile turns over, its back holds 8 picture buttons (clear, partly cloudy, cloudy, fog, rain, thunderstorm, snow, hail) in the page's own scene words. *Source: the user, 2026-10-07.*
- **REQ_REPORT_2** The button on the front is a pencil with the word "Report" ("Melden"), so it's clear that it opens the report. *Source: the user, 2026-10-12 (phone test P3: the earlier arrow icon looked like reload).*
- **REQ_REPORT_3** One tap saves; rain first asks for the intensity (light, moderate, heavy, or skip); "now", "15 min ago" or "30 min ago". *Source: the user, 2026-10-07.*
- **REQ_REPORT_4** A "That's right" button confirms what the page shows. *Source: the user, 2026-10-07.*
- **REQ_REPORT_5** After saving, the front shows the report and its time with an undo, while it is fresh; a failed save says so and keeps the back open. *Source: the user, 2026-10-07.*
- **REQ_REPORT_6** A report is fresh for 30 minutes (the newest observed at or before now). *Source: the user, 2026-10-07.*
- **REQ_REPORT_7** The host tile is one attribute in the page, so another tile can host it later. *Source: the user, 2026-10-07.*
- **REQ_REPORT_8** Reports count in the accuracy only in their own block ("Against your reports"), scored on the same forecast hours as the station; the station's table, the weights and the vote stay station-only. Per hour the newest report decides; rain, thunderstorm, snow and hail count as rain. *Source: the user, 2026-10-07 (option A).*
- **REQ_REPORT_9** Reports are kept for the accuracy window, at most 500. *Source: the user, 2026-10-07.*
- **REQ_REPORT_10** No report button on the locked wall display (`?kiosk`). *Source: the user, 2026-10-07.*

## Security (SEC)

- **REQ_SEC_1** Meant for a trusted home network: no login, no accounts; it must not be reachable from the internet. *Source: scope.*
  *Proof:* scope: home-network-only is a deployment assumption; review: no login, account or password code in the app
- **REQ_SEC_2** A foreign website can neither read data from the app nor change it: no CORS; changes (location, reports) only as same-origin JSON. *Source: scope.*
  *Proof:* `cargo:routes::api_tests::no_cors_for_foreign_origin`; `contract:unconfigured:security/cors`; `cargo:routes::location_tests::post_location_foreign_origin_is_403`
- **REQ_SEC_3** DNS-rebinding protection: the app answers only to IP addresses, `localhost`, `*.local` names and explicitly allowed host names. *Source: scope.*
  *Proof:* `cargo:security::tests::host_allowed_accepted`; `cargo:security::tests::host_allowed_rejected`; `contract:*:security/host-evil`
- **REQ_SEC_4** Security headers on every response, errors included: a strict Content Security Policy, no framing, no referrer, no MIME sniffing. *Source: scope.*
  *Proof:* `contract:*:security/docs`; `cargo:routes::api_tests::unhandled_error_500_still_carries_security_headers`
  *Refines:* REQ_PRIV_1
- **REQ_SEC_5** Upstream data and the user's input are never rendered as HTML. *Source: scope.*
  *Proof:* review: every value the page fills is set via textContent, innerHTML only with constants
- **REQ_SEC_6** The interactive API documentation is off unless enabled. *Source: scope.*
  *Proof:* `contract:*:security/docs`; `contract:*:security/redoc`; `contract:*:security/openapi`
- **REQ_SEC_7** The container runs as a non-root user on a read-only file system, without capabilities, with a process limit. *Source: scope.*
  *Proof:* review: docker-compose.yml and rust/Dockerfile set read_only, cap_drop ALL, pids_limit and a non-root user

## Privacy (PRIV)

- **REQ_PRIV_1** No tracking, no analytics, no account. *Source: scope.*
  *Proof:* refined; `ui:*/*/requests`; review: no analytics, tracking or account code in app/static or the backend
- **REQ_PRIV_2** The coordinates go only to the weather services (needed for the forecast); search text goes to Nominatim from the app's server; coordinates typed in directly go nowhere else (so no reverse geocoding). *Source: scope.*
  *Proof:* `ui:*/*/requests`; `cargo:geocode::tests::search_request_carries_user_agent_and_jsonv2_params`
- **REQ_PRIV_3** No information about the user's home location in the repository (code, fixtures, goldens, commits). *Source: the user, 2026-10-03.*
  *Proof:* review: the fixtures, goldens and examples use only test places such as Berlin

## Operation (OPS)

- **REQ_OPS_1** One container, run with Docker Compose or Podman Compose, on Linux PCs and a Raspberry Pi with a 64-bit OS (down to a Pi Zero 2 W with 512 MB); Docker Desktop on macOS or Windows. *Source: scope; Pi Zero: the user.*
  *Refines:* REQ_GEN_2
- **REQ_OPS_2** All data in one volume that can be backed up and restored. *Source: scope.*
- **REQ_OPS_3** Settings in `weather.yaml` plus a few environment variables (port, allowed host names, accuracy weighting, API docs, the first-start place). *Source: scope.*
  *Refines:* REQ_GEN_2
- **REQ_OPS_4** An update keeps the data: the new version reads the old database as it is; a way back to the previous version exists and is tested. *Source: the user, 2026-10-03.*

## Code and checks (CODE)

- **REQ_CODE_1** The backend is Rust, idiomatic and safe by lint (no `unsafe`, no panicking calls, no unchecked indexing or lossy casts outside tests). *Source: the user (the Rust port).*
- **REQ_CODE_2** Decisions live in small pure functions with tests; the aggregator and the store only move data. No source file over 400 lines. *Source: scope.*
- **REQ_CODE_3** Tests never touch the network and run in the project's container images. *Source: scope.*
- **REQ_CODE_4** The API's answers stay byte for byte the same unless a change is intended (the contract suite). *Source: the Rust port.*
- **REQ_CODE_5** The UI checks may not get weaker unnoticed: planted faults must keep failing them. *Source: the user, 2026-10-13.*
