"""Aggregation: cache refresh scheduling + rain-probability computation.

Step 3 implements the probability logic (radar nowcast, model votes,
ensemble share, weighted combination, fallback without radar). The public
interface below is final — the FastAPI layer and frontend depend on it.
"""
from __future__ import annotations

import time
from typing import Any

from .brightsky_client import BrightSkyClient
from .config import AppConfig
from .models import (
    CurrentConditions,
    EnsembleVote,
    ModelVote,
    RainProbability,
    RadarNowcast,
)
from .openmeteo_client import OpenMeteoClient
from .store import Store


class Aggregator:
    def __init__(
        self,
        cfg: AppConfig,
        store: Store,
        brightsky: BrightSkyClient,
        openmeteo: OpenMeteoClient,
    ):
        self._cfg = cfg
        self._store = store
        self._brightsky = brightsky
        self._openmeteo = openmeteo

    # -- refresh (called by the scheduler, never per page load) ------------
    async def refresh_radar(self) -> None:
        """Fetch Bright Sky current_weather + radar and cache them.

        TODO(step 3): call the clients, store via store.put_cache,
        tolerate SourceError (keep stale cache, log the error).
        """
        raise NotImplementedError("step 3")

    async def refresh_models(self) -> None:
        """Fetch Open-Meteo forecast + ensemble and cache them.

        TODO(step 3): call the clients, store via store.put_cache,
        tolerate SourceError, and append hourly rows to forecast_history.
        """
        raise NotImplementedError("step 3")

    # -- read model (page loads) --------------------------------------------
    async def get_current_conditions(self) -> CurrentConditions | None:
        """Parse the cached Bright Sky current_weather.

        TODO(step 3): parse 'raw' payload into CurrentConditions.
        """
        raise NotImplementedError("step 3")

    async def get_radar_nowcast(self) -> RadarNowcast | None:
        """Parse the cached radar payload into 5-min frames near the location.

        TODO(step 3): keep only cells within cfg.radar.radius_km of the
        location (haversine); mark covered=False outside Germany.
        """
        raise NotImplementedError("step 3")

    async def get_model_votes(self) -> list[ModelVote]:
        """Sum each model's next-60-min precipitation from minutely_15.

        TODO(step 3): parse precipitation_<model> series, sum the four
        15-min steps covering the next hour.
        """
        raise NotImplementedError("step 3")

    async def get_ensemble_vote(self) -> EnsembleVote:
        """Share of ensemble members with > threshold mm in the next hour.

        TODO(step 3): precipitation_memberNN over the next hour.
        """
        raise NotImplementedError("step 3")

    async def get_rain_probability(self) -> RainProbability | None:
        """Weighted combination of radar/model/ensemble signals.

        TODO(step 3): see README 'How the probability is calculated'.
        """
        raise NotImplementedError("step 3")

    async def get_24h_model_comparison(self) -> dict[str, Any]:
        """Hourly precipitation per model for the next 24 h (chart data).

        TODO(step 3): align all models on a common hourly UTC grid.
        """
        raise NotImplementedError("step 3")

    async def get_source_status(self) -> dict[str, dict[str, Any]]:
        """Per-source cache age + staleness flag for the UI.

        TODO(step 3): from store.get_cache + cfg.scheduling.stale_*.
        """
        raise NotImplementedError("step 3")
