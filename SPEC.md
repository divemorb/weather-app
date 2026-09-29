Build a local web app that aggregates weather data from multiple sources and displays it in a clear, clean way.

## Goal

- Show the current weather at my location (set in the setup wizard)

- Calculate and display the probability of rain in the next 60 minutes

- Compare several weather models

## Data sources (free, no API key)

1. Bright Sky (https://api.brightsky.dev), data from DWD (German Weather Service)

   - /current_weather: current observations

   - /radar: radar, 1 km² grid, 5-minute steps, incl. 2h nowcast

2. Open-Meteo (https://api.open-meteo.com)

   - Forecast API with multiple models in one call (ICON-D2, ICON-EU, ECMWF IFS, GFS, Météo-France, MET Norway)

   - minutely_15 for the next hour

   - Ensemble API for real probabilities

## Rain probability (next 60 min)

- Radar nowcast: rain within a 1 km radius around the location (highest weight)

- Models: share of models predicting > 0.1 mm

- Ensemble: share of members predicting rain

- Weighted overall value in %; weights configurable

- Explain in the UI how the value is derived (e.g. "Radar: yes, 3 of 5 models")

- Fallback without radar (outside Germany): models + ensemble only

## Tech stack

- Backend: Python, FastAPI, httpx (async), APScheduler

- Storage: SQLite (cache + forecast history)

- Frontend: Svelte or plain HTML + uPlot/Chart.js

- Deployment: Docker Compose, running locally on my home network

- Configuration (location, radius, weights, models) via .env or YAML

## Requirements

- Caching: fetch radar every 5 min, models hourly; never fetch per page load

- Use UTC internally, convert only in the frontend (Europe/Berlin)

- A failing source must not block the app; show data age

- Show source attribution in the UI (DWD, Open-Meteo); non-commercial use only

## UI

- "Now" tile: temperature, feels-like, wind, cloud cover, precipitation

- Prominent display: rain probability for the next hour in %

- 60-minute bar in 5-minute steps (radar nowcast)

- Model comparison chart for the next 24 h

- Responsive, dark mode, readable on mobile

## Optional extension

- Store forecasts and compare them with later observations

- Compute per-model accuracy at my location and use it as automatic weighting

## Approach

1. Set up project structure and docker-compose

2. API clients for Bright Sky and Open-Meteo, with tests

3. Aggregation and probability logic, with unit tests

4. REST endpoints for the frontend

5. Frontend

6. README with setup instructions and an explanation of the calculation