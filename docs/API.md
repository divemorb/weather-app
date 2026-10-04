# API

The REST contract of the app: the endpoint table, the interactive-docs note, and the response contract with examples.

| Endpoint | Purpose |
| --- | --- |
| `GET /healthz` | liveness |
| `GET /api/config` | `configured` flag, location, timezone, weights (for UI labels) |
| `GET /api/now` | current conditions tile |
| `GET /api/rain-probability` | combined % + per-source breakdown |
| `GET /api/radar/next-hour` | 12 x 5-minute radar bar |
| `GET /api/models/24h` | hourly precipitation per model |
| `GET /api/model-accuracy` | per-model forecast accuracy (window) |
| `GET /api/sources` | per-source age / staleness |
| `GET /api/schedule` | next backend refresh per job (UI countdown) |
| `GET /api/geocode` | address search for the setup wizard (Nominatim; `q` min 3 chars) |
| `POST /api/location` | set the home location (same-origin JSON only; 403 for foreign origins) |

All timestamps are **UTC** in the API; the frontend converts to `Europe/Berlin`.

**Interactive docs** (`/docs`, `/redoc`, `/openapi.json`) are **off by default** (the app has no login, so the API contract should not be browsable by every device on the LAN). To enable them, start the app with `ENABLE_API_DOCS=true`:

```bash
ENABLE_API_DOCS=true docker compose up -d --build
```

### Response contract

The serializers live in `app/api_serializers.py` (pure functions, unit-tested in `tests/test_api_serializers.py`); the endpoints in `app/main.py` are thin (aggregate → serialize). Every data payload carries freshness so the UI can show an age badge / stale flag without a round-trip to `/api/sources`.

**`GET /api/now`**

```json
{
  "available": true, "age_seconds": 12, "stale": false,
  "conditions": {
    "timestamp_utc": "2025-01-01T12:00:00Z", "source_id": 96160,
    "temperature_c": 5.0, "feels_like_c": 3.5,
    "wind_speed_ms": 3.0, "wind_direction_deg": 180.0, "wind_gust_ms": 6.0,
    "cloud_cover_pct": 75.0, "humidity_pct": 80.0, "pressure_hpa": 1015.0,
    "dew_point_c": 3.0,
    "precipitation_10mm": 0.0, "precipitation_30mm": 0.1, "precipitation_60mm": 0.2,
    "condition": "Rain",
    "icon": "cloudy",
    "station": {"name": "Berlin-Tempelhof", "distance_m": 5837.0, "lat": 52.4676,
                "lon": 13.402, "height_m": 47.7, "dwd_station_id": "00433"},
    "fallback": {"cloud_cover_pct": {"name": "Potsdam", "distance_m": 27915.0}}
  }
}
```

`conditions` is `null` (and `available: false`) until the first observation is cached.

`icon` is Bright Sky's `weather.icon` for this observation, passed through for the page's animated sky: one of `clear-day`, `clear-night`, `partly-cloudy-day`, `partly-cloudy-night`, `cloudy`, `fog`, `wind`, `rain`, `sleet`, `snow`, `hail`, `thunderstorm` (day/night and wind are already folded into the value), or `null` when the payload has no icon or an unknown value (missing, empty, wrong case, or not a string).

`station` names the observation station the values come from (the listed Bright Sky source whose `id` equals `source_id`): `name` (`station_name`), `distance_m`, `lat`, `lon`, `height_m` and `dwd_station_id`; a missing key is `null`. It is `null` when the payload lists no such source (older payloads may have no `sources` key at all).

`fallback` says where the individual values came from instead: for each value Bright Sky took from a different listed station (`fallback_source_ids`), the **API's own field name** (`cloud_cover` → `cloud_cover_pct`, …) maps to that station's `name` and `distance_m`. Fields the API doesn't carry (`solar_60`, …) and ids of unlisted sources are left out; `{}` when nothing fell back.

**`GET /api/rain-probability`**

```json
{
  "probability_pct": 75.0,
  "explanation": "Radar: yes; 1 of 2 models predict > 0.1 mm in the next hour; ensemble 50 %",
  "radar_available": true, "radar_raining": true,
  "models_rain_count": 1, "models_total": 2, "ensemble_pct": 50.0,
  "weights_used": {"radar": 0.5, "models": 0.3, "ensemble": 0.2},
  "accuracy_weighted": false,
  "radar_age_seconds": 12, "models_age_seconds": 12
}
```

`weights_used` is `{}` and `probability_pct` is `0.0` when no signal is available yet (see [ARCHITECTURE.md](ARCHITECTURE.md) — "How the rain probability is calculated").

`accuracy_weighted` is `true` only when the model signal was weighted by each model's accuracy: `USE_ACCURACY_WEIGHTS` is on and every voting model has enough compared hours (see [ARCHITECTURE.md](ARCHITECTURE.md) — "Optional accuracy weighting"). The explanation then ends its model part with ", accuracy-weighted".

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

Each bucket is the *strongest* rain cell within `radar.radius_km` for that 5-minute step (0.0 for dry). `available` is `false` when radar is missing or does not cover the location — the UI then falls back to a models-only display. A bucket with no radar frame yet (nowcast does not reach that far) is `0.0`.

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

`hours[i]` is the UTC **start** of the hour whose precipitation is `precipitation_mm[i]` (an hourly value at stamp `t` covers `[t-1h, t)`). The window is relative to *now*, not the UTC calendar day: the first entry is always the current hour, so `hours` spans from now to now + 23 h (e.g. 10:20 UTC → 10:00, 11:00, …, next day 09:00).

**`GET /api/model-accuracy`** — per-model forecast accuracy over the configured window (see [ARCHITECTURE.md](ARCHITECTURE.md) — "How the rain probability is calculated" → "Scoring the models").

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
  },
  "stations": [
    {"name": "Berlin-Friedrichshain", "distance_m": 1860.0, "lat": 52.5277,
     "lon": 13.4548, "dwd_station_id": "10050", "hours": 2},
    {"name": "Berlin-TEMPELHOF", "distance_m": 5576.0, "lat": 52.475,
     "lon": 13.407, "dwd_station_id": "00433", "hours": 3},
    {"name": "Berlin-Müggelsee", "distance_m": 17000.0, "lat": 52.44,
     "lon": 13.65, "dwd_station_id": "00410", "hours": 1}
  ]
}
```

`models` is `{}` while no forecast has an observation yet (fresh install — it fills up hourly via the observation backfill). `event_accuracy` and `mae_mm` are `null`-safe (never `null` with `n_samples > 0`). `enough_data` is `n_samples >= min_samples`; the UI should grey out rows below that.

`stations` remembers which DWD stations the observations of the last backfill came from, nearest first: `name`, `distance_m`, `lat`, `lon`, `dwd_station_id`, and `hours` — how many observation hours that backfill wrote from the station. It is `[]` until the first backfill has written observations, and it is cleared when the home location actually moves (a sub-ε nudge keeps it); a failed or observation-less backfill leaves it unchanged. Missing keys are `null`.

**`GET /api/sources`** — one entry per source (`radar`, `current`, `forecast`, `ensemble`):

```json
{
  "radar": {
    "upstream": "DWD (Bright Sky)", "available": true,
    "age_seconds": 10, "stale": false, "last_error": null
  }
}
```

**`GET /api/schedule`** — when the app next polls the upstream services, per scheduler job. `next_run_utc` is `null` while the scheduler isn't running; `server_time_utc` lets the browser correct for its own clock offset:

```json
{
  "server_time_utc": "2026-09-29T14:05:56Z",
  "jobs": {
    "radar":  {"interval_minutes": 5,  "next_run_utc": "2026-09-29T14:06:50Z", "sources": ["radar", "current"]},
    "models": {"interval_minutes": 60, "next_run_utc": "2026-09-29T15:05:50Z", "sources": ["forecast", "ensemble"]}
  }
}
```

The frontend shows this as three countdowns in its Details section (radar, models, next page reload) and reloads its data 10 s after each scheduled refresh, or every 60 s at the latest.
