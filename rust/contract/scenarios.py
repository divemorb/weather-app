"""Contract scenarios: fixed "now", environment, upstream data, requests.

Each scenario starts a fresh backend (empty database unless ``seed`` says
otherwise) against a fake upstream (``fakeup.py``) and sends its cases in
order. Case names are ``area/what``; a watchdog step can require a subset
by pattern (``run.py --require 'static/*'``).

Case fields: ``path``; optional ``method`` (GET), ``headers`` (merged over
the defaults below), ``body`` (JSON-encoded unless it is a str),
``settle`` (wait for the refresh a location change starts), ``etag_from``
(send If-None-Match with that earlier case's ETag), ``compare``
(``json`` / ``text`` / ``bytes`` / ``status``; default by content type).
"""
from __future__ import annotations

NOW_LIVE = "2026-09-30T10:27:10Z"  # 2 min after the live recording
NOW_RAIN = "2026-09-30T10:50:00Z"  # ensemble picks the 12:00 stamp
BERLIN = {"LATITUDE": "52.52", "LONGITUDE": "13.405"}

DEFAULT_HEADERS = {"Host": "127.0.0.1:8000"}
SAME_ORIGIN = {"Content-Type": "application/json", "Origin": "http://127.0.0.1:8000"}

LIVE = {
    "/bs/current_weather": {"file": "live/current_weather.json"},
    "/bs/radar": {"file": "live/radar.json"},
    "/bs/weather": {"file": "live/weather.json"},
    "/om/v1/forecast": {"file": "live/forecast.json"},
    "/ens/v1/ensemble": {"file": "live/ensemble.json"},
    "/nom/search": {"file": "live/nominatim_search.json"},
}
# the live recording with two shown values taken elsewhere (station steps):
# cloud cover from Potsdam (listed source), dew point from an unlisted source
FALLBACK = {**LIVE, "/bs/current_weather": {"file": "live/current_weather_fallback.json"}}
RAIN = {**LIVE,
        "/bs/radar": {"file": "rain/radar.json"},
        "/om/v1/forecast": {"file": "rain/forecast.json"},
        "/ens/v1/ensemble": {"file": "rain/ensemble.json"}}
ERRORS = {
    "/bs/current_weather": {"raw": "{\"weather\": "},
    "/bs/radar": {"status": 500},
    "/bs/weather": {"status": 500},
    "/om/v1/forecast": {"oversize": 6_000_000},
    "/ens/v1/ensemble": {"oversize": 6_000_000, "declare": True},
    "/nom/search": {"status": 500},
}

API = ["/healthz", "/api/config", "/api/now", "/api/rain-probability", "/api/radar/next-hour",
       "/api/models/24h", "/api/model-accuracy", "/api/sources", "/api/schedule"]
STATIC = ["index.html", "api.js", "app.js", "chart.css", "chart.js", "details.css", "details.js", "format.js", "glance.js",
          "i18n.js", "kiosk.css", "now.js", "setup.js", "stationmap.js", "style.css"]


def get(path, name=None, **kw):
    return {"name": name or path.strip("/").replace("api/", "api/", 1) or "root", "path": path, **kw}


def api_cases():
    return [get(p) for p in API]


def post_location(name, body, headers=None, **kw):
    return {"name": f"location/{name}", "method": "POST", "path": "/api/location",
            "headers": {**SAME_ORIGIN, **(headers or {})}, "body": body, **kw}


VALID = {"latitude": 52.52, "longitude": 13.405, "timezone": "Europe/Berlin", "label": "Berlin"}

SECURITY_CASES = [
    get("/", "static/root", compare="bytes"),
    *[get(f"/{f}", f"static/{f}", compare="bytes") for f in STATIC],
    get("/app.js", "static/app.js-revalidate", etag_from="static/app.js"),
    get("/nope.js", "static/missing"),
    get("/../weather.yaml", "static/traversal"),
    get("/%2e%2e/weather.yaml", "static/traversal-encoded"),
    get("/api/nope", "static/api-unknown"),
    {"name": "static/post-file", "method": "POST", "path": "/app.js", "headers": SAME_ORIGIN, "body": {}},
    {"name": "static/post-unknown", "method": "POST", "path": "/nope", "headers": SAME_ORIGIN, "body": {}},
    get("/docs", "security/docs"),
    get("/redoc", "security/redoc"),
    get("/openapi.json", "security/openapi"),
    get("/healthz", "security/host-evil", headers={"Host": "evil.example"}),
    get("/healthz", "security/host-evil-port", headers={"Host": "evil.example:8000"}),
    get("/healthz", "security/host-empty", headers={"Host": ""}),
    get("/healthz", "security/host-suffix", headers={"Host": "localhost.evil.com"}),
    get("/healthz", "security/host-ipv6", headers={"Host": "[::1]:8000"}),
    get("/healthz", "security/host-mdns", headers={"Host": "raspberrypi.local:8000"}),
    get("/healthz", "security/host-localhost", headers={"Host": "localhost"}),
    get("/healthz", "security/host-extra", headers={"Host": "PI.FRITZ.BOX:8000"}),
    get("/api/config", "security/cors", headers={"Origin": "https://evil.example"}),
    {"name": "security/method", "method": "POST", "path": "/api/now", "headers": SAME_ORIGIN, "body": {}},
]

VALIDATION_CASES = [
    post_location("422-latitude", {**VALID, "latitude": 91}),
    post_location("422-longitude", {**VALID, "longitude": -180.5}),
    post_location("422-missing-timezone", {k: v for k, v in VALID.items() if k != "timezone"}),
    post_location("422-empty-timezone", {**VALID, "timezone": ""}),
    post_location("422-unknown-timezone", {**VALID, "timezone": "Mars/Olympus_Mons"}),
    post_location("422-traversal-timezone", {**VALID, "timezone": "../../etc/passwd"}),
    post_location("422-long-label", {**VALID, "label": "x" * 201}),
    post_location("422-not-json", "abc"),
    post_location("422-json-list", [1, 2]),
    post_location("422-nan", '{"latitude": NaN, "longitude": 13.4, "timezone": "Europe/Berlin"}',
                  compare="status"),
    post_location("422-before-403", {**VALID, "latitude": 91}, {"Origin": "http://evil.example"}),
    post_location("403-foreign-origin", VALID, {"Origin": "http://evil.example"}),
    post_location("403-fetch-site", VALID, {"Origin": None, "Sec-Fetch-Site": "cross-site"}),
]

def report_case(name, method, path, body=None, headers=None, **kw):
    case = {"name": f"reports/{name}", "method": method, "path": path,
            "headers": {**SAME_ORIGIN, **(headers or {})}, **kw}
    if body is not None:
        case["body"] = body
    return case


def post_report(name, body, headers=None, **kw):
    return report_case(name, "POST", "/api/reports", body, headers, **kw)


FOREIGN = {"Origin": "http://evil.example"}

# The user reports (report steps). The seed adds reports 1-7 (run.py
# SEEDED_REPORTS); the first new one gets id 8 and drops id 1 (older than
# the 30-day window).
REPORT_CASES = [
    get("/api/reports/current", "reports/current-none"),
    get("/api/model-accuracy", "reports/accuracy-seeded"),
    get("/api/rain-probability", "reports/rain-probability"),  # the weights ignore reports
    post_report("post-rain-heavy", {"kind": "rain", "intensity": "heavy"}),
    get("/api/reports/current", "reports/current-rain"),
    post_report("post-fog-15", {"kind": "fog", "minutes_ago": 15}),
    get("/api/reports/current", "reports/current-still-rain"),
    post_report("post-confirm-30", {"kind": "cloudy", "confirms": True, "minutes_ago": 30}),
    post_report("post-every-field", {"kind": "rain", "intensity": None, "minutes_ago": 0, "confirms": False}),
    report_case("delete-11", "DELETE", "/api/reports/11"),
    report_case("delete-rain", "DELETE", "/api/reports/8"),
    report_case("delete-again", "DELETE", "/api/reports/8"),
    report_case("delete-pruned", "DELETE", "/api/reports/1"),
    report_case("delete-unknown-large", "DELETE", "/api/reports/123456789012345678"),
    get("/api/reports/current", "reports/current-after-undo"),
    get("/api/model-accuracy", "reports/accuracy-after-posts"),
    post_report("422-kind", {"kind": "sunny"}),
    post_report("422-kind-case", {"kind": "Rain"}),
    post_report("422-kind-missing", {}),
    post_report("422-intensity", {"kind": "rain", "intensity": "huge"}),
    post_report("422-intensity-not-rain", {"kind": "fog", "intensity": "light"}),
    post_report("422-minutes", {"kind": "rain", "minutes_ago": 10}),
    post_report("422-minutes-float", {"kind": "rain", "minutes_ago": 15.0}),
    post_report("422-minutes-string", {"kind": "rain", "minutes_ago": "15"}),
    post_report("422-minutes-bool", {"kind": "rain", "minutes_ago": False}),
    post_report("422-confirms-int", {"kind": "rain", "confirms": 1}),
    post_report("422-observed-at", {"kind": "rain", "observed_at": "2026-09-30T08:00:00Z"}),
    post_report("422-json-list", [1]),
    post_report("422-not-json", "abc"),
    post_report("422-nan", '{"kind": "rain", "minutes_ago": NaN}', compare="status"),
    post_report("422-before-403", {"kind": "sunny"}, FOREIGN),
    post_report("403-foreign-origin", {"kind": "rain"}, FOREIGN),
    post_report("403-fetch-site", {"kind": "rain"}, {"Origin": None, "Sec-Fetch-Site": "cross-site"}),
    report_case("delete-422-letters", "DELETE", "/api/reports/abc"),
    report_case("delete-422-zero", "DELETE", "/api/reports/0"),
    report_case("delete-422-plus", "DELETE", "/api/reports/+9"),
    report_case("delete-422-decimal", "DELETE", "/api/reports/9.0"),
    report_case("delete-422-leading-zero", "DELETE", "/api/reports/09"),
    report_case("delete-422-space", "DELETE", "/api/reports/%209"),
    report_case("delete-422-too-long", "DELETE", "/api/reports/1234567890123456789"),
    report_case("delete-422-before-403", "DELETE", "/api/reports/abc", headers=FOREIGN),
    report_case("delete-403", "DELETE", "/api/reports/9", headers=FOREIGN),
    report_case("put-405", "PUT", "/api/reports", {"kind": "rain"}),
    report_case("post-current-405", "POST", "/api/reports/current", {}),
    report_case("put-id-405", "PUT", "/api/reports/9", {}),
    get("/api/reports", "reports/get-collection"),
    get("/api/reports/9", "reports/get-one"),
    get("/api/reports/current", "reports/current-final"),
    post_location("move-munich", {**VALID, "latitude": 48.13743, "longitude": 11.57549, "label": "München"},
                  settle=True),
    get("/api/reports/current", "reports/current-after-move"),
    get("/api/model-accuracy", "reports/accuracy-after-move"),
    report_case("delete-after-move", "DELETE", "/api/reports/9"),
]

SCENARIOS = [
    {"name": "unconfigured", "now": NOW_LIVE, "env": {"ALLOWED_HOSTS": "pi.fritz.box"}, "routes": {},
     "cases": api_cases() + SECURITY_CASES + VALIDATION_CASES + [
         post_report("409-unconfigured", {"kind": "rain"}),
         post_report("422-before-409", {"kind": "sunny"}),
         post_report("403-before-409", {"kind": "rain"}, FOREIGN),
         get("/api/reports/current", "reports/current-unconfigured"),
     ]},
    {"name": "live", "now": NOW_LIVE, "env": BERLIN, "routes": LIVE, "cases": api_cases()},
    {"name": "rain", "now": NOW_RAIN, "env": BERLIN, "routes": RAIN, "cases": api_cases()},
    {"name": "fallback", "now": NOW_LIVE, "env": BERLIN, "routes": FALLBACK, "cases": [get("/api/now")]},
    {"name": "errors", "now": NOW_LIVE, "env": BERLIN, "routes": ERRORS,
     "cases": api_cases() + [get("/api/geocode?q=Alexanderplatz%20Berlin", "geocode/upstream-error")]},
    {"name": "accuracy", "now": NOW_RAIN, "env": {"USE_ACCURACY_WEIGHTS": "true"}, "routes": RAIN,
     "seed": {"location": True, "history": "full"},
     "cases": [get("/api/config"), get("/api/model-accuracy"), get("/api/rain-probability")]},
    {"name": "accuracy-gate", "now": NOW_RAIN, "env": {"USE_ACCURACY_WEIGHTS": "true"}, "routes": RAIN,
     "seed": {"location": True, "history": "gate"},
     "cases": [get("/api/model-accuracy"), get("/api/rain-probability")]},
    {"name": "report", "now": NOW_RAIN, "env": {"USE_ACCURACY_WEIGHTS": "true"}, "routes": RAIN,
     "seed": {"location": True, "history": "full", "reports": True}, "cases": REPORT_CASES},
    {"name": "wizard", "now": NOW_LIVE, "env": {}, "routes": LIVE, "cases": [
        get("/api/config", "wizard/config-before"),
        post_location("set-berlin", VALID, settle=True),
        get("/api/config", "wizard/config-berlin"),
        get("/api/sources", "wizard/sources-berlin"),
        get("/api/now", "wizard/now-berlin"),
        post_location("move-munich", {**VALID, "latitude": 48.13743, "longitude": 11.57549,
                                      "label": "München"}, settle=True),
        get("/api/config", "wizard/config-munich"),
        get("/api/model-accuracy", "wizard/accuracy-after-move"),
        post_location("same-place", {**VALID, "latitude": 48.1401, "longitude": 11.5801,
                                     "label": ""}, settle=True),
        get("/api/config", "wizard/config-same-place"),
        post_location("lax-string-latitude", {**VALID, "latitude": "52.5"}, settle=True),
        post_location("lax-int-latitude", {**VALID, "latitude": 52}, settle=True),
        post_location("lax-bool-latitude", {**VALID, "latitude": True}, settle=True),
        post_location("extra-field", {**VALID, "extra": 1}, settle=True),
        get("/api/geocode?q=Alexanderplatz%20Berlin", "geocode/ok"),
        get("/api/geocode?q=ab", "geocode/too-short"),
        get("/api/geocode", "geocode/missing"),
        get("/api/geocode?q=" + "x" * 201, "geocode/too-long"),
    ]},
]
