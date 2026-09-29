# Architecture

How the app works, for developers: how the rain probability is calculated,
the data conventions of the upstream sources, and the project layout.

## How the rain probability is calculated

Three independent signals for the **next 60 minutes**, combined linearly:

1. **Radar nowcast** (highest weight, default 0.5) — the DWD radar grid is
   scanned for cells within `radar.radius_km` of your location. If any cell in
   the relevant 5-minute steps exceeds the rain threshold, radar "votes
   rain" (binary 0/1).
2. **Model agreement** (default 0.3) — each configured Open-Meteo model sums
   its 15-minute precipitation for the next hour; the signal is the *share*
   of models forecasting more than `model_rain_threshold_mm` (0–100 %).
3. **Ensemble probability** (default 0.2) — share of ECMWF ensemble members
   (50) whose precipitation for the next hour exceeds the threshold. The
   ensemble has hourly data only, so it uses the hour that overlaps the next
   60 minutes the most (the first hourly step stamped `>= now + 30 min`).

```
P = w_r * R + w_m * M + w_e * E          (weights renormalized to sum 1)
```

- `R` = 1 if radar sees rain nearby, else 0
- `M` = (models with rain) / (models available)
- `E` = (members with rain) / (members available)

**Fallback (no radar coverage, e.g. outside Germany):** `w_r` is dropped and
the remaining weights are re-normalized automatically (0.3/0.2 becomes
0.6/0.4). The UI always shows the derivation, e.g.
"Radar: yes, 3 of 5 models, 42 % ensemble".

**Scoring the models (`GET /api/model-accuracy`):** MAE alone is misleading —
during a dry spell a model that always says 0 mm has a near-zero MAE without
ever being right about rain. So each model is scored on the *same yes/no
event* the vote uses (``> model_rain_threshold_mm``), over the last
`accuracy.window_days` days: `hits` (rain forecast, rain observed),
`misses`, `false_alarms`, `correct_negatives`, and
`event_accuracy = (hits + correct_negatives) / n_samples`. `mae_mm` is
reported for context. A model is flagged `enough_data` once it has at least
`accuracy.min_samples` compared hours; the response's `models` dict is empty
while nothing has been compared yet (fresh install — observations accumulate
hourly via the backfill).

**Optional accuracy weighting (`USE_ACCURACY_WEIGHTS`):** with this switch
on, the model signal `M` is no longer the equal-weight share of models with
rain. Each voting model's vote (100 if it forecasts
`> model_rain_threshold_mm`, else 0) is weighted by its `event_accuracy`
from the scoring above, and
`M = 100 * sum(w_i * rain_i) / sum(w_i)` with `w_i = max(event_accuracy, 0.1)`
— the 0.1 floor keeps a poor model from being silenced entirely, and a model
with no accuracy data yet gets the floor. **Gate:** if *any* voting model has
fewer than `accuracy.min_samples` compared hours (or no accuracy row at
all), the scores are not trustworthy yet and the signal falls back to the
plain equal-weight share. The radar and ensemble weights are never changed.
The explanation string gets ", accuracy-weighted" appended only when the
weighting was actually applied (i.e. the gate passed), and models without
next-hour data still do not vote — they also don't trip the gate.

A failing source never blocks the app: the last good cache is served with its
age shown in the UI, and sources older than the configured threshold are
flagged stale.

## Data conventions

The upstreams timestamp precipitation differently; the backend normalizes
everything to UTC and follows these rules (verified against the live APIs):

- **Open-Meteo hourly precipitation** at timestamp `t` is the rain of the
  *preceding hour* `[t-1h, t)` — a sum, not an instantaneous value.
- **Open-Meteo minutely_15 precipitation** at timestamp `t` is the rain of
  the preceding 15 minutes `[t-15min, t)`. The hourly value at 11:00 equals
  the sum of the 15-min values at 10:15, 10:30, 10:45 and 11:00.
- **Open-Meteo apparent_temperature** (hourly) is an *instantaneous* value at
  `t`, not a sum.
- **Bright Sky `/weather`** hourly records: `precipitation` at timestamp `T`
  is the rain of the preceding hour `[T-1h, T)`; `observation_type`
  `"current"`/`"historical"` marks real observations, `"forecast"` marks
  MOSMIX forecasts.
- **Next-hour window rule:** a step with end-stamp `t` belongs to
  `[now, now+1h)` when `now < t <= now + 1h`. A step stamped exactly `now`
  is already in the past.
- **Single-hour pick (ensemble vote):** when *one* whole hour must
  represent the next 60 minutes, pick the hourly step with the largest
  overlap with `[now, now+1h)` — i.e. the first stamp `t` with
  `t >= now + 30 min`. Example: at `now = 10:50` the step stamped 11:00
  (covering 10:00–11:00) would be 50 minutes in the past, so the step
  stamped 12:00 (covering 11:00–12:00, 50 min ahead) is used instead.
- **Observation backfill:** every hourly refresh fetches the last 48 h of
  Bright Sky `/weather` records and writes each real observation
  (station source, `observation_type != "forecast"`) into
  `forecast_history.observed_mm` for its hour start (`timestamp - 1h`).
  This catches up hours missed while the app was down.

### Forecast history (accuracy extension)

`forecast_history` stores one row per `(model, valid_from)` (unique index).
Every hourly refresh *upserts* the rows for the next 24 hours: the latest
forecast issued before the hour started (shortest lead time) wins, and a row
that already has an observation is never overwritten. A one-time migration
(tracked in `app_meta`, key `forecast_history_version`) empties the table and
adds the unique index on the first startup after this change (schema v2),
then a later startup (schema v3) drops the unused `model_accuracy` table —
accuracy is now computed on demand from `forecast_history` — and is a no-op
afterwards.
Observations are filled by the hourly backfill described above; `observed_mm`
stays `NULL` until the hour's observation exists.

## Project layout

```
weather.yaml              # all runtime configuration
docker-compose.yml        # local deployment
Dockerfile
requirements.txt
app/
  main.py                 # FastAPI app + REST contract
  config.py               # YAML + env configuration
  store.py                # SQLite: source cache + forecast history
  times.py                # UTC time helpers
  brightsky_client.py     # DWD client (current_weather, radar, /weather)
  openmeteo_client.py     # Open-Meteo forecast + ensemble client
  aggregator.py           # cache refresh + read-model (step 3)
  probability.py          # pure rain-probability logic (step 3)
  accuracy.py             # pure per-model accuracy scoring (step 6e)
  series.py               # pure API-series helpers (24 h + radar bar)
  api_serializers.py      # pure dataclass -> JSON serializers (step 4)
  scheduler.py            # APScheduler refresh jobs
  models.py               # normalized dataclasses / API contract
  static/index.html       # frontend markup (step 5)
  static/style.css        # frontend styling + dark mode (step 5)
  static/app.js           # frontend logic: fetch + render (step 5)
  static/chart.js         # 24 h model comparison SVG chart (step 5)
  static/accuracy.js      # "Model accuracy" card (step 6f)
tests/
  conftest.py
  helpers.py              # synthetic payload builders for tests
  test_accuracy.py        # pure accuracy scorer (step 6e)
  test_config.py
  test_times.py
  test_brightsky_client.py
  test_openmeteo_client.py
  test_backfill.py        # observation backfill (step 6d)
```
