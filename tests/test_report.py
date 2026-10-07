"""The user reports the real weather ("Stimmt nicht?", report steps P1 and P2).

P1: ``POST /api/reports`` stores a report (a closed set of values; the
server's clock sets the time), ``DELETE /api/reports/{id}`` undoes it,
``GET /api/reports/current`` answers the fresh one (30 min). Reports are
kept for the accuracy window, at most 500, and go with the location's data
on a move.
P2: ``/api/model-accuracy`` scores the models against the reports too
(``user_reports``), beside the station's table and without changing it.

The API runs on a real Aggregator with an in-memory Store; the routes find
the Store at ``app.state.store``. The clock is ``app.reports.utcnow`` (the
contract launcher patches the same name).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.aggregator_support import make_aggregator, make_cfg, make_payloads

T0 = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
SAME_ORIGIN = {"Origin": "http://127.0.0.1:8000"}
FOREIGN = {"Origin": "http://evil.example"}
KINDS = ["clear", "partly-cloudy", "cloudy", "fog", "rain", "thunderstorm", "snow", "hail"]


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock(monkeypatch) -> Clock:
    c = Clock(T0)
    monkeypatch.setattr("app.reports.utcnow", c)
    monkeypatch.setattr("app.aggregator.utcnow", c)
    return c


@pytest.fixture
def setup(store, clock):
    """(TestClient, Aggregator) with cfg, aggregator and store on app.state."""
    payloads = make_payloads()
    agg = make_aggregator(make_cfg(), store, payloads, payloads)
    app.state.cfg = agg.cfg
    app.state.aggregator = agg
    app.state.store = store
    yield TestClient(app, base_url="http://127.0.0.1:8000"), agg
    app.state.store = None


@pytest.fixture
def c(setup) -> TestClient:
    return setup[0]


def post(c: TestClient, body, headers=None):
    return c.post("/api/reports", json=body, headers={**SAME_ORIGIN, **(headers or {})})


def current(c: TestClient):
    r = c.get("/api/reports/current")
    assert r.status_code == 200
    return r.json()["report"]


def at(clock: Clock, hh: int, mm: int = 0, day: int = 1) -> None:
    clock.now = datetime(2025, 1, day, hh, mm, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# P1: saving a report
# ---------------------------------------------------------------------------
async def test_post_saves_and_answers_the_report(c):
    r = post(c, {"kind": "rain", "intensity": "heavy"})
    assert r.status_code == 201
    report = r.json()["report"]
    assert isinstance(report["id"], int) and report["id"] >= 1
    assert report == {"id": report["id"], "kind": "rain", "intensity": "heavy", "confirms": False,
                      "observed_at": "2025-01-01T12:00:00Z"}


async def test_defaults(c):
    report = post(c, {"kind": "fog"}).json()["report"]
    assert report["intensity"] is None
    assert report["confirms"] is False
    assert report["observed_at"] == "2025-01-01T12:00:00Z"
    assert post(c, {"kind": "rain", "intensity": None}).status_code == 201


@pytest.mark.parametrize("kind", KINDS)
async def test_every_kind(c, kind):
    r = post(c, {"kind": kind})
    assert r.status_code == 201
    assert r.json()["report"]["kind"] == kind


@pytest.mark.parametrize("minutes, stamp", [(0, "12:00:00"), (15, "11:45:00"), (30, "11:30:00")])
async def test_minutes_ago_moves_the_time_back(c, minutes, stamp):
    report = post(c, {"kind": "snow", "minutes_ago": minutes}).json()["report"]
    assert report["observed_at"] == f"2025-01-01T{stamp}Z"


async def test_time_is_the_servers_in_whole_seconds(c, clock):
    clock.now = T0 + timedelta(seconds=7, microseconds=900_000)
    report = post(c, {"kind": "hail", "minutes_ago": 15}).json()["report"]
    assert report["observed_at"] == "2025-01-01T11:45:07Z"  # truncated, not rounded


async def test_confirmation(c):
    report = post(c, {"kind": "cloudy", "confirms": True}).json()["report"]
    assert report["confirms"] is True


async def test_ids_count_up(c):
    a = post(c, {"kind": "fog"}).json()["report"]["id"]
    b = post(c, {"kind": "fog"}).json()["report"]["id"]
    assert b > a


async def test_stored_rows(c, store):
    """The table the Rust backend writes the same way (the lockstep compares
    the databases): ``confirms`` as 0/1, ``intensity`` NULL when not given."""
    post(c, {"kind": "rain", "intensity": "light", "minutes_ago": 15})
    post(c, {"kind": "clear", "confirms": True})
    async with store._db.execute(
        "SELECT kind, intensity, confirms, observed_at FROM user_reports ORDER BY id"
    ) as cur:
        rows = [tuple(r) for r in await cur.fetchall()]
    assert rows == [("rain", "light", 0, "2025-01-01T11:45:00Z"),
                    ("clear", None, 1, "2025-01-01T12:00:00Z")]


# ---------------------------------------------------------------------------
# P1: what is refused
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("body, loc", [
    ({"kind": "sunny"}, ["body", "kind"]),
    ({"kind": "Rain"}, ["body", "kind"]),
    ({"kind": 1}, ["body", "kind"]),
    ({}, ["body", "kind"]),
    ({"kind": "rain", "intensity": "huge"}, ["body", "intensity"]),
    ({"kind": "fog", "intensity": "light"}, ["body", "intensity"]),   # intensity only with rain
    ({"kind": "snow", "intensity": "heavy"}, ["body", "intensity"]),
    ({"kind": "rain", "minutes_ago": 10}, ["body", "minutes_ago"]),
    ({"kind": "rain", "minutes_ago": -15}, ["body", "minutes_ago"]),
    ({"kind": "rain", "minutes_ago": "15"}, ["body", "minutes_ago"]),
    ({"kind": "rain", "minutes_ago": 15.0}, ["body", "minutes_ago"]),  # integers only
    ({"kind": "rain", "minutes_ago": False}, ["body", "minutes_ago"]),
    ({"kind": "rain", "minutes_ago": None}, ["body", "minutes_ago"]),
    ({"kind": "rain", "confirms": "yes"}, ["body", "confirms"]),
    ({"kind": "rain", "confirms": 1}, ["body", "confirms"]),
    ({"kind": "rain", "observed_at": "2025-01-01T08:00:00Z"}, ["body", "observed_at"]),  # no client times
    ({"kind": "rain", "extra": 1}, ["body", "extra"]),
    ([1], ["body"]),
])
async def test_invalid_body_is_422_without_echo(c, body, loc):
    r = post(c, body)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert [d["loc"] for d in detail] == [loc]
    assert all(set(d) == {"loc", "msg"} for d in detail)  # the input is never echoed
    assert current(c) is None


async def test_not_json_is_422(c):
    r = c.post("/api/reports", content="abc",
               headers={**SAME_ORIGIN, "Content-Type": "application/json"})
    assert r.status_code == 422
    assert [d["loc"] for d in r.json()["detail"]] == [["body", 0]]


@pytest.mark.parametrize("headers", [FOREIGN, {"Sec-Fetch-Site": "cross-site"}])
async def test_cross_site_post_is_refused(c, headers):
    r = c.post("/api/reports", json={"kind": "rain"}, headers=headers)
    assert r.status_code == 403
    assert r.json() == {"detail": "cross-site request refused"}
    assert current(c) is None


async def test_validation_comes_before_the_origin_check(c):
    """As for /api/location: the body is validated first."""
    assert post(c, {"kind": "sunny"}, FOREIGN).status_code == 422


async def test_unconfigured_is_409(setup, store):
    payloads = make_payloads()
    agg = make_aggregator(make_cfg(location=None), store, payloads, payloads)
    app.state.cfg = agg.cfg
    app.state.aggregator = agg
    c = setup[0]
    r = post(c, {"kind": "rain"})
    assert r.status_code == 409
    assert r.json() == {"detail": "no location configured"}
    assert post(c, {"kind": "sunny"}).status_code == 422  # validation first
    assert post(c, {"kind": "rain"}, FOREIGN).status_code == 403  # then the origin


# ---------------------------------------------------------------------------
# P1: the current report
# ---------------------------------------------------------------------------
async def test_current_is_null_without_reports(c):
    assert current(c) is None


async def test_current_is_the_newest_observation(c, clock):
    first = post(c, {"kind": "rain", "minutes_ago": 30}).json()["report"]
    newest = post(c, {"kind": "fog"}).json()["report"]
    post(c, {"kind": "snow", "minutes_ago": 15})  # saved last, observed earlier
    assert current(c) == newest
    assert first != newest


async def test_current_tie_goes_to_the_higher_id(c):
    post(c, {"kind": "rain"})
    second = post(c, {"kind": "hail"}).json()["report"]
    assert current(c) == second


async def test_current_is_fresh_for_30_minutes(c, clock):
    report = post(c, {"kind": "thunderstorm"}).json()["report"]
    clock.now = T0 + timedelta(minutes=30)
    assert current(c) == report          # exactly 30 min old: still fresh
    clock.now = T0 + timedelta(minutes=30, seconds=1)
    assert current(c) is None


async def test_late_report_is_fresh_for_less(c, clock):
    post(c, {"kind": "rain", "minutes_ago": 30})
    clock.now = T0 + timedelta(seconds=1)
    assert current(c) is None


# ---------------------------------------------------------------------------
# P1: undo
# ---------------------------------------------------------------------------
async def test_delete_undoes_a_report(c):
    rid = post(c, {"kind": "rain"}).json()["report"]["id"]
    r = c.delete(f"/api/reports/{rid}", headers=SAME_ORIGIN)
    assert r.status_code == 200
    assert r.json() == {"deleted": rid}
    assert current(c) is None
    r = c.delete(f"/api/reports/{rid}", headers=SAME_ORIGIN)
    assert r.status_code == 404
    assert r.json() == {"detail": "report not found"}


async def test_delete_shows_the_previous_report_again(c):
    older = post(c, {"kind": "cloudy", "minutes_ago": 15}).json()["report"]
    rid = post(c, {"kind": "rain"}).json()["report"]["id"]
    c.delete(f"/api/reports/{rid}", headers=SAME_ORIGIN)
    assert current(c) == older


@pytest.mark.parametrize("raw", ["abc", "0", "-1", "+5", "5.0", "05", "%205", "1234567890123456789"])
async def test_delete_id_must_be_plain_digits(c, raw):
    """``^[1-9][0-9]{0,17}$``: no sign, no leading zero, no spaces, below 10^18."""
    post(c, {"kind": "rain"})
    r = c.delete(f"/api/reports/{raw}", headers=SAME_ORIGIN)
    assert r.status_code == 422
    assert [d["loc"] for d in r.json()["detail"]] == [["path", "report_id"]]


async def test_delete_large_unknown_id_is_404(c):
    r = c.delete("/api/reports/123456789012345678", headers=SAME_ORIGIN)
    assert r.status_code == 404


async def test_cross_site_delete_is_refused(c):
    rid = post(c, {"kind": "rain"}).json()["report"]["id"]
    r = c.delete(f"/api/reports/{rid}", headers=FOREIGN)
    assert r.status_code == 403
    assert current(c)["id"] == rid
    assert c.delete("/api/reports/abc", headers=FOREIGN).status_code == 422  # validation first


@pytest.mark.parametrize("method, path", [
    ("PUT", "/api/reports"), ("POST", "/api/reports/current"), ("PUT", "/api/reports/1"),
])
async def test_other_methods_are_405(c, method, path):
    """(A GET on a path without GET falls through to the static files, as
    everywhere in the app: 404.)"""
    assert c.request(method, path, headers=SAME_ORIGIN).status_code == 405


# ---------------------------------------------------------------------------
# P1: how long reports are kept
# ---------------------------------------------------------------------------
async def test_reports_older_than_the_window_are_dropped(c, clock):
    old = post(c, {"kind": "rain"}).json()["report"]["id"]
    kept = post(c, {"kind": "fog"}).json()["report"]["id"]
    clock.now = T0 + timedelta(days=30)                   # exactly the window: kept
    post(c, {"kind": "clear"})
    assert c.delete(f"/api/reports/{kept}", headers=SAME_ORIGIN).status_code == 200
    clock.now = T0 + timedelta(days=30, seconds=1)        # older than the window: dropped
    post(c, {"kind": "clear"})
    assert c.delete(f"/api/reports/{old}", headers=SAME_ORIGIN).status_code == 404


async def test_cap_500_reports(c, clock):
    """The oldest observation goes first (then the lowest id)."""
    oldest = post(c, {"kind": "rain", "minutes_ago": 30}).json()["report"]["id"]
    second = post(c, {"kind": "rain", "minutes_ago": 15}).json()["report"]["id"]
    for _ in range(498):
        post(c, {"kind": "fog"})
    assert c.delete(f"/api/reports/{oldest}", headers=SAME_ORIGIN).status_code == 200
    post(c, {"kind": "fog"})  # 500 again
    post(c, {"kind": "fog"})  # 501: the oldest left (second) is dropped
    assert c.delete(f"/api/reports/{second}", headers=SAME_ORIGIN).status_code == 404


async def test_moving_deletes_the_reports(setup):
    from app.config import LocationConfig

    c, agg = setup
    rid = post(c, {"kind": "rain"}).json()["report"]["id"]
    await agg.set_location(LocationConfig(52.001, 13.001, "Europe/Berlin"))  # same place
    assert current(c)["id"] == rid
    await agg.set_location(LocationConfig(48.137, 11.575, "Europe/Berlin"))
    assert current(c) is None
    assert c.delete(f"/api/reports/{rid}", headers=SAME_ORIGIN).status_code == 404


# ---------------------------------------------------------------------------
# P2: the models against the reports
# ---------------------------------------------------------------------------
def hour(hh: int) -> str:
    return f"2025-01-01T{hh:02d}:00:00Z"


async def seed_history(store) -> None:
    """Frozen forecast rows (with a station observation) for 06:00-11:00,
    a row without observation at 08:00, no row at all at 07:00."""
    def row(model, hh, mm):
        return {"model": model, "issued_at": hour(hh - 1), "valid_from": hour(hh),
                "valid_to": hour(hh + 1), "precip_mm": mm}

    await store.add_forecasts([
        row("icon_d2", 6, 0.0),                           # icon_eu has no 06:00 row
        row("icon_d2", 8, 0.4), row("icon_eu", 8, 0.4),   # no observation
        row("icon_d2", 9, 0.5), row("icon_eu", 9, 0.0),
        row("icon_d2", 10, 0.0), row("icon_eu", 10, 0.3),
        row("icon_d2", 11, 0.1), row("icon_eu", 11, 0.0),  # 0.1 is dry (strict >)
    ])
    for hh, mm in ((6, 0.0), (9, 0.0), (10, 0.4), (11, 0.0)):
        await store.set_observation(hour(hh), mm)


async def test_accuracy_without_a_store(client):
    """Endpoint tests with a fake aggregator have no Store: the block is empty."""
    from tests.api_fakes import FakeAgg

    body = client(FakeAgg(accuracy={})).get("/api/model-accuracy").json()
    assert body["user_reports"] == {"hours": 0, "confirmed_hours": 0, "models": {}}


async def test_accuracy_without_reports(c, store):
    await seed_history(store)
    body = c.get("/api/model-accuracy").json()
    assert body["user_reports"] == {"hours": 0, "confirmed_hours": 0, "models": {}}


async def test_accuracy_against_the_reports(c, store, clock):
    await seed_history(store)
    station_before = c.get("/api/model-accuracy").json()["models"]
    for hh, mm, body in [
        (6, 15, {"kind": "rain"}),                        # wet; only icon_d2 has a row
        (7, 0, {"kind": "hail"}),                         # no forecast row: not scored
        (8, 30, {"kind": "snow"}),                        # no observation yet: not scored
        (9, 10, {"kind": "thunderstorm"}),                # wet
        (10, 5, {"kind": "rain", "intensity": "light"}),  # superseded in its hour ...
        (10, 55, {"kind": "clear", "minutes_ago": 15}),   # ... by this one (10:40): dry
        (11, 20, {"kind": "cloudy", "confirms": True}),   # dry, a confirmation
    ]:
        at(clock, hh, mm)
        assert post(c, body).status_code == 201
    at(clock, 12)
    body = c.get("/api/model-accuracy").json()
    assert body["user_reports"] == {
        "hours": 4,
        "confirmed_hours": 1,
        "models": {
            # 06 miss, 09 hit, 10 correct negative, 11 correct negative
            "icon_d2": {"n_samples": 4, "hits": 1, "misses": 1, "false_alarms": 0,
                        "correct_negatives": 2, "event_accuracy": 0.75},
            # 09 miss, 10 false alarm, 11 correct negative
            "icon_eu": {"n_samples": 3, "hits": 0, "misses": 1, "false_alarms": 1,
                        "correct_negatives": 1, "event_accuracy": 0.333},
        },
    }
    assert body["models"] == station_before  # the station's table is unchanged


async def test_accuracy_newest_report_in_the_hour_decides(c, store, clock):
    await seed_history(store)
    at(clock, 9, 50)
    post(c, {"kind": "fog"})                                  # dry, observed 09:50
    at(clock, 9, 59)
    post(c, {"kind": "rain", "minutes_ago": 15})              # wet, observed 09:44: older
    at(clock, 12)
    models = c.get("/api/model-accuracy").json()["user_reports"]["models"]
    assert models["icon_d2"]["false_alarms"] == 1             # 09: 0.5 mm vs dry


async def test_accuracy_undone_reports_dont_count(c, store, clock):
    await seed_history(store)
    at(clock, 9, 10)
    rid = post(c, {"kind": "rain"}).json()["report"]["id"]
    c.delete(f"/api/reports/{rid}", headers=SAME_ORIGIN)
    at(clock, 12)
    assert c.get("/api/model-accuracy").json()["user_reports"]["hours"] == 0


async def test_accuracy_only_hours_inside_the_window(c, store, clock):
    await seed_history(store)
    at(clock, 9, 10)
    post(c, {"kind": "rain"})
    clock.now = datetime(2025, 1, 31, 9, 0, tzinfo=timezone.utc)   # 09:00 is 30 days back: in
    assert c.get("/api/model-accuracy").json()["user_reports"]["hours"] == 1
    clock.now = datetime(2025, 1, 31, 9, 0, 1, tzinfo=timezone.utc)  # out
    assert c.get("/api/model-accuracy").json()["user_reports"]["hours"] == 0
