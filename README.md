# Weather App — local multi-source rain forecast

Aggregates weather for one fixed location (configured in `weather.yaml`,
defaults to Berlin) from **free, keyless sources** and answers one
question prominently:

> **What is the probability of rain in the next 60 minutes?**

Data sources (attribution shown in the UI, non-commercial use only):

- **DWD via Bright Sky** — `current_weather` (now) + `radar` (1 km grid,
  5-minute steps, ~2 h nowcast) + `/weather` (hourly observations for the
  forecast-history backfill). https://api.brightsky.dev
- **Open-Meteo** — multi-model forecast (`icon_d2`, `icon_eu`, `ecmwf_ifs025`,
  `gfs_seamless`, `arome_france`, `ukmo_seamless`) and the ECMWF ensemble
  (50 members) for a real precipitation probability. https://open-meteo.com

## Quick start

```bash
docker compose up -d --build
# open http://localhost:8000
```

To serve on another port: `PORT=9000 docker compose up -d --build`

The SQLite cache lives in the `weather-data` volume — page loads never touch
the upstream APIs.

### Without Docker (development)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DATABASE_PATH=./data/weather.db uvicorn app.main:app --reload
```

### Running the tests

```bash
pip install -r requirements.txt   # includes pytest + pytest-asyncio
pytest
```

## Configuration

All runtime settings live in **`weather.yaml`** (repo root). Key sections:

| Key | Meaning | Default |
| --- | --- | --- |
| `location.*` | latitude / longitude / display timezone | your location, `Europe/Berlin` |
| `radar.radius_km` | "local rain" radius around you | `1.0` |
| `probability.weights.{radar,models,ensemble}` | combination weights | `0.5 / 0.3 / 0.2` |
| `probability.model_rain_threshold_mm` | model rain threshold | `0.1` |
| `models.forecast` | Open-Meteo models to compare | 6 models |
| `models.ensemble_model` | ensemble for probability | `ecmwf_ifs025` (50 members) |
| `scheduling.*` | refresh cadence + stale thresholds | radar 5 min, models 60 min |
| `accuracy.window_days` | accuracy window (compared hours) | `30` |
| `accuracy.min_samples` | min compared hours before a model counts as "enough data" | `48` |

Environment variables override the YAML for the most common knobs:
`LATITUDE`, `LONGITUDE`, `TIMEZONE`, `RADAR_RADIUS_KM`, `WEIGHT_RADAR`,
`WEIGHT_MODELS`, `WEIGHT_ENSEMBLE`, `RADAR_INTERVAL_MINUTES`,
`MODELS_INTERVAL_MINUTES`, `DATABASE_PATH`, `USE_ACCURACY_WEIGHTS` (boolean,
default `false` — see "Optional accuracy weighting" below).

Change `weather.yaml` and rebuild: `docker compose up -d --build`.

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

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /healthz` | liveness |
| `GET /api/config` | location, timezone, weights (for UI labels) |
| `GET /api/now` | current conditions tile |
| `GET /api/rain-probability` | combined % + per-source breakdown |
| `GET /api/radar/next-hour` | 12 x 5-minute radar bar |
| `GET /api/models/24h` | hourly precipitation per model |
| `GET /api/model-accuracy` | per-model forecast accuracy (window) |
| `GET /api/sources` | per-source age / staleness |

All timestamps are **UTC** in the API; the frontend converts to
`Europe/Berlin`. Interactive docs: `http://localhost:8000/docs`.

### Response contract

The serializers live in `app/api_serializers.py` (pure functions, unit-tested
in `tests/test_api_serializers.py`); the endpoints in `app/main.py` are thin
(aggregate → serialize). Every data payload carries freshness so the UI can show
an age badge / stale flag without a round-trip to `/api/sources`.

**`GET /api/now`**

```json
{
  "available": true, "age_seconds": 12, "stale": false,
  "conditions": {
    "timestamp_utc": "2025-01-01T12:00:00Z", "source_id": 11702,
    "temperature_c": 5.0, "feels_like_c": 3.5,
    "wind_speed_ms": 3.0, "wind_direction_deg": 180.0, "wind_gust_ms": 6.0,
    "cloud_cover_pct": 75.0, "humidity_pct": 80.0, "pressure_hpa": 1015.0,
    "dew_point_c": 3.0,
    "precipitation_10mm": 0.0, "precipitation_30mm": 0.1, "precipitation_60mm": 0.2,
    "condition": "Rain"
  }
}
```

`conditions` is `null` (and `available: false`) until the first observation is
cached.

**`GET /api/rain-probability`**

```json
{
  "probability_pct": 75.0,
  "explanation": "Radar: yes; 1 of 2 models predict > 0.1 mm in the next hour; ensemble 50 %",
  "radar_available": true, "radar_raining": true,
  "models_rain_count": 1, "models_total": 2, "ensemble_pct": 50.0,
  "weights_used": {"radar": 0.5, "models": 0.3, "ensemble": 0.2},
  "radar_age_seconds": 12, "models_age_seconds": 12
}
```

`weights_used` is `{}` and `probability_pct` is `0.0` when no signal is
available yet (see "How the rain probability is calculated").

**`GET /api/radar/next-hour`** — the 60-minute local-rain bar (12 x 5-min).

```json
{
  "available": true, "age_seconds": 12, "stale": false,
  "steps": [
    {"start_utc": "2025-01-01T12:00:00Z", "precip_mm": 0.2},
    {"start_utc": "2025-01-01T12:05:00Z", "precip_mm": 0.0},
    "… 12 buckets total (oldest first) …"
  ]
}
```

Each bucket is the *strongest* rain cell within `radar.radius_km` for that
5-minute step (0.0 for dry). `available` is `false` when radar is missing or
does not cover the location — the UI then falls back to a models-only display.
A bucket with no radar frame yet (nowcast does not reach that far) is `0.0`.

**`GET /api/models/24h`**

```json
{
  "available": true, "age_seconds": 60, "stale": false,
  "hours": ["2025-01-01T12:00:00Z", "… 24 points …"],
  "models": [
    {"name": "icon_d2", "precipitation_mm": [0.4, 0.0, "…"]}
  ],
  "n_models": 6
}
```

`hours[i]` is the UTC **start** of the hour whose precipitation is
`precipitation_mm[i]` (an hourly value at stamp `t` covers `[t-1h, t)`).
The window is relative to *now*, not the UTC calendar day: the first entry
is always the current hour, so `hours` spans from now to now + 23 h
(e.g. 10:20 UTC → 10:00, 11:00, …, next day 09:00).

**`GET /api/model-accuracy`** — per-model forecast accuracy over the
configured window (see "How the rain probability is calculated" →
"Scoring the models").

```json
{
  "window_days": 30,
  "min_samples": 48,
  "models": {
    "icon_d2": {
      "n_samples": 100,
      "hits": 20, "misses": 10, "false_alarms": 15, "correct_negatives": 55,
      "event_accuracy": 0.75,
      "mae_mm": 0.205,
      "enough_data": true
    },
    "gfs_seamless": {
      "n_samples": 10,
      "hits": 2, "misses": 3, "false_alarms": 2, "correct_negatives": 3,
      "event_accuracy": 0.5,
      "mae_mm": 0.4,
      "enough_data": false
    }
  }
}
```

`models` is `{}` while no forecast has an observation yet (fresh install —
it fills up hourly via the observation backfill). `event_accuracy` and
`mae_mm` are `null`-safe (never `null` with `n_samples > 0`). `enough_data`
is `n_samples >= min_samples`; the UI should grey out rows below that.

**`GET /api/sources`** — one entry per source (`radar`, `current`, `forecast`,
`ensemble`):

```json
{
  "radar": {
    "upstream": "DWD (Bright Sky)", "available": true,
    "age_seconds": 10, "stale": false, "last_error": null
  }
}
```

## Roadmap

- [x] **Step 1** — project structure, Docker Compose, config, skeleton,
      SQLite schema, REST contract
- [x] **Step 2** — API clients for Bright Sky + Open-Meteo with pure,
      unit-tested parsers (37 tests). Radar grid decode (base64+zlib uint16,
      0.01 mm / 5 min), multi-model forecast, and 50-member ensemble verified
      against the live APIs.
- [x] **Step 3** — aggregation + rain-probability logic, with unit tests
      (radar nowcast window + ensemble hour selection verified against the
      live APIs; graceful degradation when a source fails or coverage is missing)
- [x] **Step 4** — REST endpoints implemented, with a pure serializer layer
      (`app/api_serializers.py`) and unit tests for every endpoint (including
      the 60-minute local-rain bar, `GET /api/radar/next-hour`). Live smoke
      test against Bright Sky + Open-Meteo passes.
- [x] **Step 5** — frontend (`app/static/`, no build step, no external
      CDN): prominent next-60-min rain-% headline with per-source
      derivation, "Now" tile, 60-minute radar bar, 24 h multi-model SVG
      chart, data-source status with age/stale badges, dark mode (default)
      with a light toggle, mobile-responsive. Reads the REST API (UTC) and
      converts to the configured display timezone; auto-refreshes every
      60 s.
- [x] **Step 6** — forecast history vs. observations, per-model accuracy,
      optional accuracy weighting: 6a/6b next-hour window boundary and
      hour-labeling fixes, 6c idempotent forecast history (unique
      `model`/hour, upsert), 6d observation backfill from Bright Sky
      `/weather`, 6e per-model accuracy read-model +
      `GET /api/model-accuracy`, 6f "Model accuracy" card
      (`app/static/accuracy.js` — samples / hit / miss / false-alarm /
      event-accuracy / MAE table, greyed-out rows below
      `accuracy.min_samples`, "no data yet" and "Collecting data — N of M
      hours" states), 6g optional accuracy-weighted model signal behind
      `USE_ACCURACY_WEIGHTS` (gated on `accuracy.min_samples`, falls back to
      equal weights until every voting model has enough compared hours).
