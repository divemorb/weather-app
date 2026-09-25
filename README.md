# Weather App — local multi-source rain forecast

Aggregates weather for one fixed location (configured in `weather.yaml`,
defaults to Berlin) from **free, keyless sources** and answers one
question prominently:
> **What is the probability of rain in the next 60 minutes?**

Data sources (attribution shown in the UI, non-commercial use only):

- **DWD via Bright Sky** — `current_weather` (now) + `radar` (1 km grid,
  5-minute steps, ~2 h nowcast). https://api.brightsky.dev
- **Open-Meteo** — multi-model forecast (`icon_d2`, `icon_eu`,
  `ecmwf_ifs025`, `gfs_seamless`, `meteofrance`, `met_no`) and the ECMWF ensemble (50 members)
  for a real precipitation probability. https://open-meteo.com

## Quick start

## Roadmap

- [x] **Step 1** — project structure, Docker Compose, config, skeleton,
      SQLite schema, REST contract
- [x] **Step 2** — API clients for Bright Sky + Open-Meteo with pure,
      unit-tested parsers (37 tests). Radar grid decode (base64+zlib uint16,
      0.01 mm/5min), multi-model forecast, and 50-member ensemble verified
      against the live APIs.
- [ ] **Step 3** — aggregation + rain-probability logic, with unit tests
- [ ] **Step 4** — REST endpoints implemented (currently stubs returning 501)
- [ ] **Step 5** — frontend: now tile, big rain-% display, 60-minute radar
      bar, 24 h model comparison chart, dark mode, mobile
- [ ] **Step 6 (optional)** — forecast history vs.

