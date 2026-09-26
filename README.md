# Weather App — local multi-source rain forecast

Aggregates weather for one fixed location (configured in `weather.yaml`,
defaults to Berlin) from **free, keyless sources** and answers one
question prominently:

> **What is the probability of rain in the next 60 minutes?**

Data sources (attribution shown in the UI, non-commercial use only):

- **DWD via Bright Sky** — `current_weather` (now) + `radar` (1 km grid,
  5-minute steps, ~2 h nowcast). https://api.brightsky.dev
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

Environment variables override the YAML for the most common knobs:
`LATITUDE`, `LONGITUDE`, `TIMEZONE`, `RADAR_RADIUS_KM`, `WEIGHT_RADAR`,
`WEIGHT_MODELS`, `WEIGHT_ENSEMBLE`, `RADAR_INTERVAL_MINUTES`,
`MODELS_INTERVAL_MINUTES`, `DATABASE_PATH`.

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
   (50) whose precipitation for the next hour exceeds the threshold.

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

A failing source never blocks the app: the last good cache is served with its
age shown in the UI, and sources older than the configured threshold are
flagged stale.

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
  brightsky_client.py     # DWD client (current_weather, radar)
  openmeteo_client.py     # Open-Meteo forecast + ensemble client
  aggregator.py           # probability logic (step 3)
  scheduler.py            # APScheduler refresh jobs
  models.py               # normalized dataclasses / API contract
  static/index.html       # frontend (step 5)
tests/
  conftest.py
  helpers.py              # synthetic payload builders for tests
  test_config.py
  test_times.py
  test_brightsky_client.py
  test_openmeteo_client.py
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
| `GET /api/sources` | per-source age / staleness |

All timestamps are **UTC** in the API; the frontend converts to
`Europe/Berlin`. Interactive docs: `http://localhost:8000/docs`.

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
- [ ] **Step 4** — REST endpoints implemented (currently stubs returning 501)
- [ ] **Step 5** — frontend: now tile, big rain-% display, 60-minute radar
      bar, 24 h model comparison chart, dark mode, mobile
- [ ] **Step 6 (optional)** — forecast history vs. observations, per-model
      accuracy, automatic weighting
