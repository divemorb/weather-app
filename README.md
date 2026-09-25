# Weather App — local multi-source rain forecast

Aggregates weather for one fixed location (configured in `weather.yaml`,
defaults to Berlin) from **free, keyless sources** and answers one
question prominently:
> **What is the probability of rain in the next 60 minutes?**

Data sources (attribution shown in the UI, non-commercial use only):

- **DWD via Bright Sky** — `current_weather` (now) + `radar` (1 km grid,
  5-minute steps, ~2 h nowcast). https://api.brightsky.dev
- **Open-Meteo** — multi-model forecast (`icon_d2`, `icon_eu`, `ecmwf_ifs025`,
  `gfs_seamless`, `meteofrance`, `met_no`) and the ECMWF ensemble (50 members)
  for a real precipitation probability. https://open-meteo.com

## Quick start


