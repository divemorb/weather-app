"""Open-Meteo clients: multi-model forecast + ensemble.

Verified API facts (checked live):

  * Forecast: ``https://api.open-meteo.com/v1/forecast``
    - model names use underscores; with several models every variable key is
      suffixed: ``minutely_15.precipitation_<model>``,
      ``hourly.precipitation_<model>``, ``hourly.apparent_temperature_<model>``,
      ...
    - units (Open-Meteo defaults): precipitation mm, temperature_2m °C,
      apparent_temperature °C, wind_speed_10m km/h, cloud_cover %.
  * Ensemble: ``https://ensemble-api.open-meteo.com/v1/ensemble`` (different
    host) returns ``hourly.precipitation`` (control) plus
    ``precipitation_member01`` .. ``precipitation_member50``. There is NO
    ready-made probability: we compute the rain probability ourselves as the
    share of members above the threshold (step 3).

The parsers (:func:`parse_forecast`, :func:`parse_ensemble`) are pure
functions so they are unit-testable without any network. The client raises
:exc:`SourceError` on any failure. Payload protection (step 7c): the
parsers are wrapped with :func:`malformed_is_source_error` and the HTTP
layer reads bodies through :func:`stream_json_capped` (size cap) — see
``app/brightsky_client.py`` for the convention.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import httpx

from .brightsky_client import SourceError, malformed_is_source_error, stream_json_capped
from .config import AppConfig
from .models import EnsembleData, ForecastBundle, ModelSeries

#: Variables requested hourly per model.
HOURLY_VARS = (
    "precipitation",
    "temperature_2m",
    "apparent_temperature",
    "wind_speed_10m",
    "cloud_cover",
)


def _parse_time_list(times: list[str]) -> list[datetime]:
    out: list[datetime] = []
    for t in times:
        s = t.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        out.append(datetime.fromisoformat(s).astimezone(timezone.utc))
    return out


def _series(payload: dict[str, Any], section: str, key: str) -> list[float | None]:
    """Return a variable list, tolerating missing keys / null values."""
    block = payload.get(section, {})
    raw = block.get(key)
    if raw is None:
        return []
    return [None if v is None else float(v) for v in raw]


@malformed_is_source_error("Open-Meteo forecast")
def parse_forecast(payload: dict[str, Any], model_names: list[str]) -> ForecastBundle:
    """Parse a multi-model forecast payload into a :class:`ForecastBundle`.

    Units are converted to the internal convention: precipitation mm,
    temperature °C, wind **km/h** (as delivered), cloud cover %.
    """
    if payload.get("error"):
        raise SourceError(f"Open-Meteo forecast error: {payload.get('reason')}")

    min15 = payload.get("minutely_15", {})
    hourly = payload.get("hourly", {})

    min15_times = _parse_time_list(min15.get("time", []))
    hourly_times = _parse_time_list(hourly.get("time", []))

    bundle = ForecastBundle()
    for name in model_names:
        m15 = _series(payload, "minutely_15", f"precipitation_{name}")
        h = {v: _series(payload, "hourly", f"{v}_{name}") for v in HOURLY_VARS}
        bundle.models.append(
            ModelSeries(
                name=name,
                min15_time=min15_times,
                min15_precip_mm=m15,
                hourly_time=hourly_times,
                hourly_precip_mm=h["precipitation"],
                hourly_temp_c=h["temperature_2m"],
                hourly_apparent_c=h["apparent_temperature"],
                hourly_wind_kmh=h["wind_speed_10m"],
                hourly_cloud_cover_pct=h["cloud_cover"],
            )
        )
    return bundle


_MEMBER_RE = re.compile(r"precipitation_member(\d+)$")


@malformed_is_source_error("Open-Meteo ensemble")
def parse_ensemble(payload: dict[str, Any]) -> EnsembleData:
    """Parse an ensemble payload into :class:`EnsembleData`.

    Members are extracted from the ``precipitation_memberNN`` keys and
    returned ordered by member number. The control run is ``precipitation``.
    """
    if payload.get("error"):
        raise SourceError(f"Open-Meteo ensemble error: {payload.get('reason')}")

    hourly = payload.get("hourly", {})
    times = _parse_time_list(hourly.get("time", []))
    control = _series(payload, "hourly", "precipitation")

    members: dict[int, list[float | None]] = {}
    for key, values in hourly.items():
        match = _MEMBER_RE.search(key)
        if match:
            idx = int(match.group(1)) - 1  # member01 -> index 0
            members[idx] = [None if v is None else float(v) for v in values]

    ordered = [members[i] for i in sorted(members)]
    return EnsembleData(
        hourly_time=times,
        control_precip_mm=control,
        member_precip_mm=ordered,
    )


class OpenMeteoClient:
    def __init__(self, cfg: AppConfig, client: httpx.AsyncClient | None = None):
        self._forecast_base = cfg.api.open_meteo_base_url.rstrip("/")
        self._ensemble_base = cfg.api.ensemble_base_url.rstrip("/")
        self._timeout = cfg.api.timeout_seconds
        self._lat = cfg.location.latitude
        self._lon = cfg.location.longitude
        self._forecast_models: list[str] = list(cfg.models.forecast)
        self._ensemble_model: str = cfg.models.ensemble_model
        self._owns_client = client is None
        self._http = client or httpx.AsyncClient(timeout=self._timeout)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        data = await stream_json_capped(self._http, url, params)
        if not isinstance(data, dict) or data.get("error"):
            reason = data.get("reason") if isinstance(data, dict) else "bad payload"
            raise SourceError(f"Open-Meteo error: {reason}")
        return data

    # -- raw payloads (what gets cached) ---------------------------------
    async def fetch_forecast_payload(self) -> dict[str, Any]:
        """Multi-model forecast: 15-min precipitation + hourly model vars."""
        params: dict[str, Any] = {
            "latitude": self._lat,
            "longitude": self._lon,
            "models": ",".join(self._forecast_models),
            "minutely_15": "precipitation",
            "hourly": ",".join(HOURLY_VARS),
            # 3 days: with 2, fewer than 24 *future* hours (t > now) would
            # remain late in the UTC day, shortening the 24 h chart.
            "forecast_days": 3,
            "timezone": "UTC",
        }
        return await self._get(f"{self._forecast_base}/forecast", params)

    async def fetch_ensemble_payload(self) -> dict[str, Any]:
        """Ensemble precipitation per member (hourly), next 2 days."""
        params: dict[str, Any] = {
            "latitude": self._lat,
            "longitude": self._lon,
            "models": self._ensemble_model,
            "hourly": "precipitation",
            "forecast_days": 2,
            "timezone": "UTC",
        }
        return await self._get(f"{self._ensemble_base}/ensemble", params)

    # -- parsed (convenience wrappers) ------------------------------------
    async def fetch_forecast(self) -> ForecastBundle:
        return parse_forecast(await self.fetch_forecast_payload(), self._forecast_models)

    async def fetch_ensemble(self) -> EnsembleData:
        return parse_ensemble(await self.fetch_ensemble_payload())
