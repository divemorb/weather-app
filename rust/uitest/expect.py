"""Expected page content per scenario and language (the UI contract's data).

The values come from the contract suite's recorded Berlin data (see
``rust/contract/golden/*.json``) and the fixed texts in
``qwen/web/00_brief.md``. Times are shown in the location's time zone
(Europe/Berlin, UTC+2 on 2026-09-30) in the browser's time format
(en-US: "12:50 PM", de-DE: "12:50"). Text comparisons ignore the kind of
space (Intl uses no-break spaces) and collapse whitespace.
"""
from __future__ import annotations

LOCALES = {"en": "en-US", "de": "de-DE"}
TZ = "Europe/Berlin"

ANSWER = {
    "nodata": {"en": "No forecast data yet", "de": "Noch keine Vorhersagedaten"},
    "dry": {"en": "No rain expected in the next hour", "de": "In der nächsten Stunde kein Regen erwartet"},
    "likely": {"en": "Rain likely in the next hour", "de": "In der nächsten Stunde wird es wahrscheinlich regnen"},
}
WHEN = {
    "rain": {"en": "Radar: rain from 12:55 PM to 1:05 PM", "de": "Radar: Regen von 12:55 bis 13:05"},
    "none": {"en": "Radar: no rain nearby", "de": "Radar: kein Regen in der Nähe"},
}
FIXED = {
    "now.unavailable": {"en": "No observation yet", "de": "Noch keine Messung"},
    "chart.dry": {"en": "No rain expected in the next 24 hours", "de": "In den nächsten 24 Stunden kein Regen erwartet"},
    "chart.unavailable": {"en": "No model forecast yet", "de": "Noch keine Modellvorhersage"},
    "accuracy.none": {"en": "No data yet — observations are compared hourly.",
                      "de": "Noch keine Daten – Messungen werden stündlich verglichen."},
}

# Same current_weather fixture in live, rain and accuracy (Bright Sky sends km/h).
NOW = {
    "now-temp": {"en": ["21°"], "de": ["21°"]},
    "now-condition": {"en": ["Overcast"], "de": ["Bedeckt"]},
    "now-feels": {"en": ["17°"], "de": ["17°"]},
    "now-wind": {"en": ["18 km/h", "SE"], "de": ["18 km/h", "SO"]},
    "now-gust": {"en": ["37 km/h"], "de": ["37 km/h"]},
    "now-humidity": {"en": ["43%"], "de": ["43 %"]},
    "now-pressure": {"en": ["1025 hPa"], "de": ["1025 hPa"]},
    "now-dewpoint": {"en": ["8°"], "de": ["8°"]},
    "now-clouds": {"en": ["100%"], "de": ["100 %"]},
    "now-rain": {"en": ["0.0 mm"], "de": ["0,0 mm"]},
    "now-time": {"en": ["12:00 PM"], "de": ["12:00"]},
}

MODEL_LABELS = {
    "icon_d2": "ICON-D2 (DWD)", "icon_eu": "ICON-EU (DWD)", "ecmwf_ifs025": "ECMWF IFS",
    "gfs_seamless": "GFS (NOAA)", "arome_france": "AROME (Météo-France)", "ukmo_seamless": "UKMO (Met Office)",
}
RAIN_MODELS = ["icon_d2", "icon_eu", "ecmwf_ifs025", "arome_france", "ukmo_seamless"]  # gfs missing in rain/
LIVE_MODELS = ["icon_d2", "icon_eu", "ecmwf_ifs025", "gfs_seamless", "arome_france", "ukmo_seamless"]

RADAR_RAIN = [0.0, 0.2, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
RADAR_DRY = [0.0] * 12

# Per scenario: what the page shows. "radar_start": first 5-minute step (UTC),
# "hours_start": first hour of /api/models/24h (UTC).
SCENARIO = {
    "live": {
        "location": ["52.520", "13.405"], "location_detail": [TZ], "answer": "dry", "when": "none", "probability": {"en": "0%", "de": "0 %"},
        "radar": RADAR_DRY, "radar_start": "2026-09-30T10:25:00Z", "now": True,
        "chart": "dry", "models": LIVE_MODELS, "hours_start": "2026-09-30T10:00:00Z",
        "signals": {"en": ["0 of 6", "0%"], "de": ["0 von 6", "0 %"]}, "source_errors": 0, "accuracy": None,
    },
    "rain": {
        "location": ["52.520", "13.405"], "location_detail": [TZ], "answer": "likely", "when": "rain", "probability": {"en": "75%", "de": "75 %"},
        "radar": RADAR_RAIN, "radar_start": "2026-09-30T10:50:00Z", "now": True,
        "chart": "lines", "models": RAIN_MODELS, "hours_start": "2026-09-30T10:00:00Z",
        "y_labels": ["0", "1", "2", "3"],  # niceScale(2.5): AROME's 2.5 mm is the maximum
        "signals": {"en": ["3 of 5", "35%"], "de": ["3 von 5", "35 %"]}, "source_errors": 0, "accuracy": None,
    },
    "errors": {
        "location": ["52.520", "13.405"], "location_detail": [TZ], "answer": "nodata", "when": None, "probability": None,
        "radar": None, "now": False, "chart": "unavailable", "signals": None, "source_errors": 4, "accuracy": None,
    },
    "accuracy": {
        "location": ["Berlin"], "location_detail": ["52.520", "13.405", TZ], "probability": {"en": "78%", "de": "78 %"},
        # sorted by event accuracy, best first; (model, percent en, percent de, MAE en, MAE de)
        "accuracy": [
            ("icon_d2", "83%", "83 %", "0.14 mm", "0,14 mm"),
            ("arome_france", "75%", "75 %", "0.17 mm", "0,17 mm"),
            ("icon_eu", "58%", "58 %", "0.21 mm", "0,21 mm"),
            ("gfs_seamless", "50%", "50 %", None, None),  # MAE 0.235: rounding differs by method, not checked
            ("ukmo_seamless", "33%", "33 %", "0.28 mm", "0,28 mm"),
            ("ecmwf_ifs025", "25%", "25 %", "0.31 mm", "0,31 mm"),
        ],
    },
}

WEIGHTS = {"en": ["50%", "30%", "20%"], "de": ["50 %", "30 %", "20 %"]}
SOURCES = {"radar": "DWD (Bright Sky)", "current": "DWD (Bright Sky)", "forecast": "Open-Meteo", "ensemble": "Open-Meteo"}
ATTRIBUTION_LINKS = ["dwd.de", "brightsky.dev", "open-meteo.com", "openstreetmap.org/copyright"]

# The wizard saves the first search result: a long Nominatim label, shown in full at 360 px.
WIZARD_LABEL = ["Alexanderplatz", "Spandauer Vorstadt", "Mitte", "Berlin", "Deutschland"]
WIZARD_DETAIL = ["52.522", "13.414", TZ]

KIOSK_SIZES = [(1280, 800), (1920, 1080)]
KIOSK_MIN_FONT = {"rain-answer": 28, "now-temp": 40}
BUDGET_BYTES = 150 * 1024
