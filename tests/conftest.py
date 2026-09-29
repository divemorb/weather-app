"""Shared fixtures. (Client/aggregation fixtures land with steps 2-3.)"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from fastapi.testclient import TestClient

from app.config import load_config
from app.main import app
from app.store import Store
from tests.aggregator_support import (
    NOW,
    current_payload,
    ensemble_payload,
    forecast_payload,
    radar_payload,
)


@pytest.fixture
def make_config(tmp_path: Path):
    """Write a YAML config file and return the path."""

    def _make(data: dict, name: str = "weather.yaml") -> Path:
        path = tmp_path / name
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    return _make


@pytest.fixture
def all_payloads() -> dict:
    return {
        "current": current_payload(),
        "radar": radar_payload([("2025-01-01T12:00:00Z", [(5, 5, 20)])]),  # 0.2 mm at location
        "forecast": forecast_payload(),
        "ensemble": ensemble_payload(),
    }


@pytest_asyncio.fixture
async def store() -> Store:
    s = Store(":memory:")
    await s.connect()
    yield s
    await s.close()


@pytest.fixture
def frozen_now(monkeypatch):
    monkeypatch.setattr("app.aggregator.utcnow", lambda: NOW)


@pytest.fixture
def cfg():
    return load_config()


@pytest.fixture
def client(cfg):
    """TestClient with the given fakes installed on ``app.state``.

    The context manager is NOT entered, so the real lifespan (DB + scheduler +
    network) is skipped.
    """

    def _install(agg) -> TestClient:
        app.state.cfg = cfg
        app.state.aggregator = agg
        # base_url on an IP literal: the Host header check (step 7g) rejects
        # the TestClient default "testserver", but accepts any IP literal.
        return TestClient(app, base_url="http://127.0.0.1:8000")

    return _install
