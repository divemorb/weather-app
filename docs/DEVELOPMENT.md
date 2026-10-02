# Development

Running the app and the test suite without Docker, and the full configuration reference (settings table and environment variables).

## Configuration

All runtime settings live in **`weather.yaml`** (repo root). Key sections:

| Key | Meaning | Default |
| --- | --- | --- |
| `location.*` | latitude / longitude / display timezone | — (set in the browser, see below) |
| `radar.radius_km` | "local rain" radius around you | `1.0` |
| `probability.weights.{radar,models,ensemble}` | combination weights | `0.5 / 0.3 / 0.2` |
| `probability.model_rain_threshold_mm` | model rain threshold | `0.1` |
| `models.forecast` | Open-Meteo models to compare | 6 models |
| `models.ensemble_model` | ensemble for probability | `ecmwf_ifs025` (50 members) |
| `scheduling.*` | refresh cadence + stale thresholds | radar 5 min, models 60 min |
| `accuracy.window_days` | accuracy window (compared hours) | `30` |
| `accuracy.min_samples` | min compared hours before a model counts as "enough data" | `48` |

**Location.** The home location is *runtime state*: it is stored in the app's database (`/data` volume), not in the repo. On first run the page shows a setup wizard — search an address (OpenStreetMap Nominatim) or type latitude/longitude — and the app starts fetching. From then on the map-pin button in the header changes the location (cached data and the accuracy history of the old location are deleted). `LATITUDE`/`LONGITUDE` env vars or a `location:` block in `weather.yaml` only *seed* the location on first start (adopted into the database); afterwards the stored value wins. `weather.yaml` ships without one, with a commented-out Berlin example under `location:` for exactly this purpose. The display timezone defaults to `Europe/Berlin` and can be set via `TIMEZONE` / `location.timezone`.

Environment variables override the YAML for the most common knobs: `LATITUDE`, `LONGITUDE`, `TIMEZONE`, `RADAR_RADIUS_KM`, `WEIGHT_RADAR`, `WEIGHT_MODELS`, `WEIGHT_ENSEMBLE`, `DATABASE_PATH`, `USE_ACCURACY_WEIGHTS` (boolean, default `false` — see [ARCHITECTURE.md](ARCHITECTURE.md) — "Optional accuracy weighting"). The refresh intervals are set in `weather.yaml` only (`scheduling.*`). Other environment variables: `ALLOWED_HOSTS` (see [SECURITY.md](SECURITY.md)), `ENABLE_API_DOCS` (see [API.md](API.md)) and `WEATHER_CONFIG` (path to an alternative `weather.yaml`).

Change `weather.yaml` and rebuild: `docker compose up -d --build`.

## Without Docker (development)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DATABASE_PATH=./data/weather.db uvicorn app.main:app --reload
```

## Running the tests

```bash
pip install -r requirements.txt   # includes pytest + pytest-asyncio
pytest
```

## Development history

The history is in `git log --oneline` (one `Step Nx:` commit per sub-step).

## Working with an AI coding agent

This project is developed with a local model through the Continue extension. The project rules the agent follows (container and test commands, what it must not touch, backend and frontend conventions, and one sub-step per chat with `Step Nx:` commits) are in [`.continue/rules/weather-projectrules.md`](../.continue/rules/weather-projectrules.md). Continue loads that file automatically in this workspace; contributors using a different agent should give it the same rules.
