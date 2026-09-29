# Weather App — local multi-source rain forecast

Aggregates weather for one fixed location (set in the browser on first run,
stored in the app's database — see
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)) from **free, keyless
sources** and answers one question prominently:

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

**Existing installs:** the container now runs as a non-root user (step 7d),
so the old root-owned volume must be handed over once before the first start
of the updated app — see the one-time command in
[docs/SECURITY.md](docs/SECURITY.md). Fresh installs don't need it.

**First run:** the app ships without a location. The first page load opens a
setup wizard — search an address (OpenStreetMap Nominatim) or type
latitude/longitude, pick a display timezone, and save. The location is
stored in the database and the app starts fetching right away (the first
data appears within seconds). From then on the 📍 button in the header
reopens the wizard to change the location (changing it deletes the cached
data and the accuracy history of the old location).

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how the rain probability
  is calculated, data conventions, project layout
- [docs/API.md](docs/API.md) — the REST API and response contract
- [docs/SECURITY.md](docs/SECURITY.md) — security design and hardening
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — running and testing without
  Docker, configuration reference
- [docs/SCOPE.md](docs/SCOPE.md) — purpose, features and requirements

