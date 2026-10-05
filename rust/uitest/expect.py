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
    # W4 (the user's review, 2026-10-02): the strip says when it is dry
    "radar.dry": {"en": "Dry for the next 60 minutes", "de": "In den nächsten 60 Minuten trocken"},
    # W7: the accuracy table explains itself
    "accuracy.note": {
        "en": "Every hour, each model's forecast is compared with what the nearest DWD weather station measured. "
              "Rain means more than 0.1 mm in the hour. Hit: rain forecast and measured. Miss: rain measured but "
              "not forecast. False alarm: rain forecast, but it stayed dry. Hit rate: the share of hours a model "
              "got right, rain or dry. Avg. error: the mean difference in mm per hour.",
        "de": "Stündlich wird die Vorhersage jedes Modells mit der Messung der nächsten DWD-Wetterstation "
              "verglichen. Regen heißt mehr als 0,1 mm in der Stunde. Treffer: Regen vorhergesagt und gemessen. "
              "Verpasst: Regen gemessen, aber nicht vorhergesagt. Fehlalarm: Regen vorhergesagt, aber es blieb "
              "trocken. Trefferquote: Anteil der Stunden, in denen ein Modell richtig lag, ob Regen oder trocken. "
              "Ø Abweichung: mittlere Differenz in mm pro Stunde.",
    },
    "accuracy.no-rain": {"en": "No rain measured in this window yet, so only false alarms show so far.",
                         "de": "In diesem Zeitraum wurde noch kein Regen gemessen, daher sind bisher nur "
                               "Fehlalarme sichtbar."},
    # shown in Details only while the accuracy weights are applied (accuracy_weighted)
    "signals.accuracy-weighted": {"en": "Models weighted by their hit rate",
                                  "de": "Modelle nach ihrer Trefferquote gewichtet"},
}

# The radar strip's caption with the radius from /api/config (the test config: radar_radius_km 1.0).
RADAR_CAPTION = {"en": "Strongest rain within 1 km, per 5 minutes",
                 "de": "Stärkster Regen im Umkreis von 1 km, je 5 Minuten"}
# The accuracy table's column headers, in order.
ACCURACY_HEAD = {"en": ["Model", "Hours", "Hits", "Misses", "False alarms", "Hit rate", "Avg. error"],
                 "de": ["Modell", "Stunden", "Treffer", "Verpasst", "Fehlalarme", "Trefferquote", "Ø Abweichung"]}

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
        "accuracy_weighted": True,
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
# Which feed a source row is: the names of the page parts it feeds (two rows share each upstream).
SOURCE_KIND = {"radar": {"en": "Radar", "de": "Radar"}, "current": {"en": "Now", "de": "Jetzt"},
               "forecast": {"en": "Models", "de": "Modelle"}, "ensemble": {"en": "Ensemble", "de": "Ensemble"}}
ATTRIBUTION_LINKS = ["dwd.de", "brightsky.dev", "open-meteo.com", "openstreetmap.org/copyright"]

# The wizard saves the first search result: a long Nominatim label, shown in full at 360 px.
WIZARD_LABEL = ["Alexanderplatz", "Spandauer Vorstadt", "Mitte", "Berlin", "Deutschland"]
WIZARD_DETAIL = ["52.522", "13.414", TZ]

# The stations behind the data (live and rain: the same Bright Sky recordings). Now: the
# current_weather source; the observation stations: the backfill's /weather sources, nearest
# first (hours = observations in the recording before "now"). On the map one mark per DWD
# station id (BERLIN-TEMPELHOF is both): bearing from the location in degrees, distance in km.
NOW_STATION = {"en": ["Berlin-Tempelhof", "5.8 km"], "de": ["Berlin-Tempelhof", "5,8 km"]}
OBS_STATIONS = [  # (name, distance en / de, hours)
    ("Berlin-Friedrichshain/Spree", "1.9 km", "1,9 km", "37"),
    ("BERLIN-TEMPELHOF", "5.6 km", "5,6 km", "10"),
]
MAP_MARKS = {"00433": (182, 5.837), "17473": (127, 1.86)}
MAP_RADIUS_KM = 1.0  # the test config's radar radius
MAP_BEARING_TOLERANCE = 20  # degrees

KIOSK_SIZES = [(1280, 800), (1920, 1080)]
KIOSK_MIN_FONT = {"rain-answer": 28, "now-temp": 40}
KIOSK_CHART_MIN = 0.22  # the chart's height as a share of the kiosk screen (1280x800: 176 px)
KIOSK_CHART_MIN_W = 0.44  # and its width (about the right column's: 1280 -> 563 px)
KIOSK_CHART_LABEL_PX = 11  # the drawn height of an x-axis label (12 px text at scale 1 is about 14 px)
# W9d, the wall tablet read from across the room: what a kiosk card shows spans this share of
# the card's inner height (no large empty bands), sizes scale with the screen height ...
KIOSK_FILL = {"glance": 0.6, "now": 0.55}
KIOSK_FONT_SHARE = {"rain-answer": 0.06, "rain-probability": 0.12, "now-temp": 0.08}  # 1280x800: 48, 96, 64 px
KIOSK_RADAR_SHARE = 0.08  # the radar strip's height (1280x800: 64 px)
KIOSK_DRY_CHART_MAX = 0.2  # ... and on a dry day the chart card is just its line (1280x800: at most 160 px high)
CONFIG_RETRY_S = 20  # a failed /api/config at startup: the page has retried and shows the forecast by then
BUDGET_BYTES = 300 * 1024  # the user, 2026-10-04 (was 150 KB); up to 512 KB if the glass effect needs it

# --- sky steps A2/A3 (qwen/sky/00_plan.md) ---
# The tiles per page width (live scenario): CSS grid columns of main#dashboard. From
# LAYOUT_WIDE px on, the tiles use at least LAYOUT_SPACE of the width, each column at
# least LAYOUT_MIN_TRACK px.
LAYOUT_COLUMNS = {360: 1, 768: 1, 1280: 2, 1920: 3}
LAYOUT_WIDE = 1280
LAYOUT_SPACE = 0.7
LAYOUT_MIN_TRACK = 280

# The scenes: Bright Sky's twelve icons, heavy-rain, and none (no data).
ICONS = ["clear-day", "clear-night", "partly-cloudy-day", "partly-cloudy-night", "cloudy", "fog",
         "wind", "rain", "sleet", "snow", "hail", "thunderstorm"]
SCENES = ICONS + ["heavy-rain", "none"]
HEAVY_MM = 0.2  # radar mm in the first 5-minute step from which rain is heavy-rain (about 2.4 mm/h)
# Faked /api/now icon and radar (None: dry; {step: mm}; "unavailable") -> the expected
# data-scene. The radar at the location decides about precipitation right now (its first
# 5-minute step): rain there overrides a dry icon; a dry radar turns the station's rain,
# sleet, snow or hail into cloudy (rule B, the user's decision 2026-10-04); a thunderstorm
# stays, and so does every icon while the radar is unavailable.
WET_ICONS = ["rain", "sleet", "snow", "hail"]
SCENE_CASES = {
    **{icon: (icon, None, "cloudy" if icon in WET_ICONS else icon) for icon in ICONS},
    "radar-rain": ("clear-day", {0: 0.1}, "rain"),
    "radar-heavy": ("cloudy", {0: 0.3}, "heavy-rain"),
    "radar-rain-on-rain": ("rain", {0: 0.5}, "heavy-rain"),
    "radar-later": ("cloudy", {3: 0.5}, "cloudy"),
    "radar-snow": ("snow", {0: 0.5}, "snow"),
    "radar-sleet": ("sleet", {0: 0.1}, "sleet"),
    "radar-hail": ("hail", {0: 0.1}, "hail"),
    "radar-thunderstorm": ("thunderstorm", {0: 0.1}, "thunderstorm"),
    "radar-unavailable": ("fog", "unavailable", "fog"),
    "rain-radar-unavailable": ("rain", "unavailable", "rain"),
    "no-icon": (None, None, "none"),
    "no-icon-radar-rain": (None, {0: 0.1}, "rain"),
    "no-observation": ("no-observation", None, "none"),
}
# How each scene is shown for the motion and contrast checks: a SCENE_CASES entry.
SCENE_SOURCE = {**{icon: icon for icon in ICONS if icon not in WET_ICONS}, "rain": "radar-rain-light",
                "sleet": "radar-sleet", "snow": "radar-snow", "hail": "radar-hail", "heavy-rain": "radar-heavy",
                "none": "no-icon"}
SCENE_CASES["radar-rain-light"] = ("rain", {0: 0.1}, "rain")
MOTION_MIN = 0.002  # share of the sky's pixels that change within MOTION_GAP_S (1280x900: 2300 px)
MOTION_GAP_S = 0.6
# Pixel contrast: each text against what is drawn behind it, at CONTRAST_MOMENTS moments
# CONTRAST_GAP_S apart; the CONTRAST_PCT worst pixels behind a text may be below WCAG AA
# (a raindrop crossing a word), the rest must not.
CONTRAST_MOMENTS = 3
CONTRAST_GAP_S = 0.7
CONTRAST_PCT = 0.05
# The views the per-scene contrast runs on: (width, height, query).
# "" is the default (big) view, "?detailed" the detailed one; the kiosk is the big view locked.
CONTRAST_VIEWS = [(1280, 900, ""), (390, 844, ""), (1280, 900, "?detailed")]

# --- why the sky looks the way it does (step B1): [data-test=sky-reason] ---
SCENE_LABEL = {  # mid-sentence, (en, de)
    "clear-day": ("clear", "klar"), "clear-night": ("clear", "klar"),
    "partly-cloudy-day": ("partly cloudy", "teilweise bewölkt"),
    "partly-cloudy-night": ("partly cloudy", "teilweise bewölkt"),
    "cloudy": ("cloudy", "bewölkt"), "fog": ("fog", "Nebel"), "wind": ("windy", "windig"),
    "rain": ("rain", "Regen"), "heavy-rain": ("heavy rain", "starker Regen"), "sleet": ("sleet", "Schneeregen"),
    "snow": ("snow", "Schnee"), "hail": ("hail", "Hagel"), "thunderstorm": ("thunderstorm", "Gewitter"),
}
REASON_TEXT = {
    "station": {"en": "Sky: {scene}, reported by station {name} ({km} away)",
                "de": "Himmel: {scene}, gemeldet von Station {name} ({km} entfernt)"},
    "nearest": {"en": "Sky: {scene}, reported by the nearest weather station",
                "de": "Himmel: {scene}, gemeldet von der nächsten Wetterstation"},
    "radar": {"en": "Sky: {scene} here, seen by the radar",
              "de": "Himmel: {scene} hier, laut Radar"},
    "radar-dry": {"en": "Sky: cloudy — dry here according to the radar; station {name} ({km} away) reports {station}",
                  "de": "Himmel: bewölkt – hier laut Radar trocken; Station {name} ({km} entfernt) meldet {station}"},
    "station-radar-dry": {"en": "Sky: {scene}, reported by station {name} ({km} away) — dry here according to the radar",
                          "de": "Himmel: {scene}, gemeldet von Station {name} ({km} entfernt) – hier laut Radar trocken"},
}
REASON_STATION = ("Berlin-Tempelhof", {"en": "5.8 km", "de": "5,8 km"})  # the live recording's station
# case -> (SCENE_CASES entry, text form or None (no line), station listed in /api/now)
REASON_CASES = {
    "station": ("cloudy", "station", True),
    "station-unlisted": ("cloudy", "nearest", False),
    "radar": ("radar-rain", "radar", True),
    "radar-heavy": ("radar-heavy", "radar", True),
    "radar-dry": ("rain", "radar-dry", True),
    "radar-dry-snow": ("snow", "radar-dry", True),
    "thunderstorm-radar-dry": ("thunderstorm", "station-radar-dry", True),
    "snow-radar-wet": ("radar-snow", "station", True),
    "radar-unavailable": ("rain-radar-unavailable", "station", True),
    "radar-only": ("no-observation-radar-rain", "radar", False),
    "none": ("no-icon", None, True),
}
SCENE_CASES["no-observation-radar-rain"] = ("no-observation", {0: 0.1}, "rain")

# --- views (step V1): the big view (the former kiosk look) is the default ---
VIEW_DESKTOP = (1280, 800)
VIEW_PHONE = (390, 844)

# --- glass (step V2): the moving sky shows through the tiles ---
GLASS_VIEW = (1280, 800)
GLASS_MIN_RATIO = 0.25  # changed share of pixels inside the tiles, relative to outside them
GLASS_GAP_S = 2.0  # time between the two screenshots
# fog is a soft, low-contrast haze: behind any glass that keeps text readable its drift
# stays below a visible change, so it is left out (its motion and contrast are checked)
GLASS_SCENES = [s for s in SCENES if s not in ("none", "fog")]
GLASS_DELTA = 12  # a visible change: at least this much (of 255) in one colour channel

# --- the review of V2 (2026-10-04/05): the big view, step by step (F1-F3) ---
BIG_PHONE = (390, 844)
BIG_LABEL_GAP = 4  # px between two radar time labels: they must not touch (V2: "12:25 PM2:45 PM" on a phone)
# The headline in the big view on a phone (the user, 2026-10-05: "max two lines"; V2 had 4-6 lines
# at 52 px, F1's fixed 24 px left short texts small): at most 2 lines and as large as fits, i.e. at
# least BIG_HEADLINE_FILL of the largest size up to BIG_HEADLINE_MAX that keeps it to 2 lines, and
# never below BIG_PHONE_MIN_FONT. Measured at 308 px text width: 2 lines up to 36 px (English
# "No rain expected ..."), 44 px (English "Rain likely ..."), 24 px (German "In der nächsten Stunde
# kein Regen erwartet"), 22 px (German "... wird es wahrscheinlich regnen"): one fixed size can't do it.
BIG_HEADLINE_LINES = 2
BIG_HEADLINE_MAX = 40
BIG_HEADLINE_FILL = 0.9
BIG_PHONE_MIN_FONT = 20
BIG_HEADLINE_SIZES = [(390, 844), (360, 740)]
# The user: the content starts at the top of the glance and Now cards (V2: about 12 % empty above),
# and the room goes to the content; Now's text keeps the glance's distance from the left border.
KIOSK_ROOM_TOP = 0.05  # the empty band above a card's content, as a share of its inner height
KIOSK_ROOM_FILL = {"glance": 0.8, "now": 0.7}  # the content's span, as in KIOSK_FILL but more
KIOSK_REASON_SHARE = 0.025  # the "why" line, read from across the room (1280x800: 20 px; V2: 13 px)
TRACK_CONTRAST = 1.5  # an empty radar track against the glass right above it (V2 light: 1.17, #e9ecf1 on #fdfefe)
VIEW_LABEL = {"big": {"en": "Details", "de": "Details"},  # the view button's visible text: where a click goes
              "detailed": {"en": "Big view", "de": "Große Ansicht"}}
