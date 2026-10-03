# Project scope

What this app is for, what it does, the requirements it must meet, and what it deliberately doesn't do. Formulas, data conventions, the API contract and security internals are described in the technical documentation:

- [ARCHITECTURE.md](ARCHITECTURE.md) — how the rain probability is calculated, data conventions, project layout
- [API.md](API.md) — the REST API and response contract
- [SECURITY.md](SECURITY.md) — security design and hardening

## Purpose

A self-hosted web app that answers one question for one place:

> **Will it rain here in the next 60 minutes?**

It combines DWD rain radar with several weather models and a 50-member ensemble, explains how it got its number, and also shows the current weather and a 24-hour model comparison. It uses only free data sources without an account or API key, and runs on the user's own computer or a Raspberry Pi in the home network.

**Users:** one household with one location. The person who runs it can copy commands into a terminal but is not necessarily a developer.

**Development approach:** the project also serves as a testbed for a local AI coding agent (Qwen). Its rules are in `.continue/rules/weather-projectrules.md`. This shapes how the code is organized (small pure functions, many tests), not what the app does.

## Features

### Rain probability for the next 60 minutes

- Shown prominently in percent, with a one-line explanation of how it was derived (e.g. "Radar: yes; 3 of 6 models predict > 0.1 mm in the next hour; ensemble 42 %").
- Three signals, combined with configurable weights (default radar 0.5, models 0.3, ensemble 0.2):
  - **Radar nowcast:** any rain cell within a configurable radius of the location (default 1 km).
  - **Models:** share of the configured models forecasting more than 0.1 mm.
  - **Ensemble:** share of the 50 ECMWF ensemble members forecasting rain.
- **Outside radar coverage** (DWD radar covers Germany only), the radar weight is dropped and the remaining weights are renormalized. The app works anywhere; outside Germany it uses the models only.
- **Optional accuracy weighting** (off by default): each model's vote is weighted by how well that model has predicted rain at this location, once every voting model has enough compared hours.

### Display

- **Now:** temperature, feels-like, wind and gusts, cloud cover, humidity, pressure, dew point, recent precipitation, condition.
- **60-minute radar bar** in 5-minute steps (strongest rain cell within the radius per step).
- **24-hour model comparison chart:** hourly precipitation per model.
- **Model accuracy:** per model, forecasts compared with later observations over the last 30 days: hits, misses, false alarms, event accuracy, mean error. Models with fewer than 48 compared hours are marked as not having enough data yet.
- **Data sources:** age of each source, a "stale" flag, and the last error.
- **Refresh countdown:** when the radar and the models are refreshed next, and when the page reloads.
- The rain answer first (a sentence, the chance, the 60-minute radar strip); the technical parts (signals and weights, countdowns, data sources, model accuracy) in a Details section that starts closed.
- English and German, following the browser's language.
- Responsive layout that works on a phone. Dark and light theme (follows the system setting on first load, toggle in the header).
- A kiosk view for a wall tablet or TV (`/?kiosk`): one screen, no scrolling, large type, no Details.
- Credits for every data source (DWD/Bright Sky, Open-Meteo, OpenStreetMap).

### Location

- **Setup wizard on first run:** search an address or place, or enter latitude and longitude; choose the display timezone. The location can be changed later from the page.
- The location is **runtime state stored in the app's database**, not part of the code or the repository. Environment variables or `weather.yaml` can seed it on the first start.
- Coordinates are rounded to 3 decimals (about 100 m) before they are stored.
- Changing the location deletes the cached data and the accuracy history of the old location.

## Data sources

| Source | Data | Refresh |
| --- | --- | --- |
| DWD via Bright Sky | current observations, radar (1 km grid, 5-min steps, ~2 h nowcast) | every 5 min |
| Open-Meteo forecast | 6 models: `icon_d2`, `icon_eu`, `ecmwf_ifs025`, `gfs_seamless`, `arome_france`, `ukmo_seamless` | every 60 min |
| Open-Meteo ensemble | `ecmwf_ifs025`, 50 members | every 60 min |
| Bright Sky `/weather` | hourly observations of the last 48 h (for model accuracy) | every 60 min |
| OpenStreetMap Nominatim | address search in the setup wizard | on request only |

All sources are free and need no account or key. Open-Meteo and Bright Sky are free for non-commercial use; this app is non-commercial.

## Requirements

### Data handling

- The upstream services are **never called per page load.** A scheduler refreshes a local cache; the page reads only the cache. A refresh also runs at startup and right after a location change.
- **A failing source never blocks the app.** The last good data is shown with its age; sources count as stale after 10 min (radar) or 120 min (models).
- **Upstream data is untrusted.** Malformed, oversized or deeply nested responses are rejected as a source error, never a crash.
- Forecasts are stored per model and hour and compared with observations as they arrive. Hours missed while the app was down are caught up (last 48 h).
- **UTC everywhere in the backend;** only the frontend converts to the display timezone.
- Address search respects the Nominatim usage policy: at most one request per second, results cached, a search only on explicit request (no search-as-you-type).

### Security

The app is meant for a **trusted home network**.

- No login and no user accounts. The app must not be reachable from the internet.
- A foreign website must not be able to read data from the app or change its location: no CORS, location changes accepted only as same-origin JSON.
- Protection against DNS rebinding: the app answers only to IP addresses, `localhost`, `*.local` names and explicitly allowed host names.
- Security headers on every response, including errors: a strict Content Security Policy, no framing, no referrer, no MIME sniffing.
- Data from upstream services is never rendered as HTML.
- The interactive API documentation is off unless explicitly enabled.
- The container runs as a non-root user on a read-only filesystem, without capabilities, with a limit on processes (200).

### Privacy

- No tracking, no analytics, no account.
- The coordinates are sent to the weather services, because that's needed to get the forecast.
- Address search text is sent to OpenStreetMap Nominatim, from the app's server. Coordinates typed in directly are not sent anywhere else.

### Operation

- Runs with Docker Compose or Podman Compose as a single container.
- Runs on Linux PCs and on a Raspberry Pi with a 64-bit OS; also with Docker Desktop on macOS or Windows.
- All data is in one volume, which can be backed up and restored.
- Settings are in `weather.yaml` (radar radius, weights, thresholds, models, refresh intervals, accuracy window, service URLs), plus a few environment variables (port, allowed host names, accuracy weighting, API docs, first-start location).

### Code

- Decisions live in small pure functions with unit tests; the aggregator and the storage layer only move data.
- Tests never touch the network and run inside the app's container image.
- No source file over 400 lines.
- The frontend needs no build step and no CDN: plain HTML, CSS and JavaScript, with a hand-written SVG chart.

## Technology

- **Backend:** Python 3.12, FastAPI, uvicorn, httpx2 (async), APScheduler, SQLite (aiosqlite), PyYAML.
- **Storage:** one SQLite file: cached upstream responses, forecast history with observations, app settings (including the location).
- **Frontend:** plain HTML, CSS and JavaScript, served by the backend.
- **Tests:** pytest with pytest-asyncio.

## Out of scope

- More than one location, or per-user settings.
- Login, user accounts, access from the internet.
- Paid data sources, or anything that needs an API key or an account.
- Notifications, alerts or push messages.
- Radar outside Germany.
- A frontend framework, a build step or a CDN.
- Long-term charts or a weather archive beyond the accuracy window.
- Commercial use.
