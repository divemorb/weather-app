"""Aggregation: scheduler-driven cache refreshes + read-model queries.

The *decisions* (radar vote, model votes, ensemble share, weighted
combination) are pure functions in :mod:`app.probability`; this class only
moves data: the scheduler refreshes the SQLite cache, and the read methods
parse it. A failing source never blocks the app — the last good cache is
served (with its age) and the error is recorded for ``/api/sources``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from .brightsky_client import (
    BrightSkyClient,
    SourceError,
    parse_current_weather,
    parse_hourly_observations,
    parse_radar,
    parse_station_info,
)
from .accuracy import model_accuracy
from .config import AppConfig
from .models import (
    CurrentConditions,
    EnsembleVote,
    ForecastBundle,
    ModelVote,
    RainProbability,
    RadarNowcast,
)
from .openmeteo_client import OpenMeteoClient, parse_ensemble, parse_forecast
from .probability import (
    build_explanation,
    combine_signals,
    ensemble_vote,
    model_rain_signal,
    model_votes,
    radar_rain_signal,
    weighted_model_signal,
)
from .series import build_24h_series, build_forecast_history_rows, build_radar_next_hour_bar
from .store import Store
from .times import to_iso, utcnow

log = logging.getLogger("weather.aggregator")

#: cache key -> (upstream label, stale-threshold attribute on SchedulingConfig)
_SOURCES: dict[str, tuple[str, str]] = {
    "radar": ("DWD (Bright Sky)", "stale_radar_minutes"),
    "current": ("DWD (Bright Sky)", "stale_radar_minutes"),
    "forecast": ("Open-Meteo", "stale_models_minutes"),
    "ensemble": ("Open-Meteo", "stale_models_minutes"),
}


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
        self._last_error: dict[str, str] = {}

    # -- refresh (called by the scheduler, never per page load) ------------
    async def refresh_radar(self) -> None:
        """Fetch Bright Sky ``current_weather`` + radar into the cache.

        Each endpoint is fetched independently so one failure does not
        discard the other; failures keep the stale cache and are recorded.
        """
        await self._fetch_into_cache("current", self._brightsky.fetch_current_payload)
        await self._fetch_into_cache("radar", self._brightsky.fetch_radar_payload)

    async def refresh_models(self) -> None:
        """Fetch Open-Meteo forecast + ensemble into the cache.

        After a successful forecast refresh, hourly rows are appended to
        ``forecast_history`` (feeds the step-6 accuracy extension), and the
        hourly observation backfill fills in ``observed_mm`` for the hours
        that have already passed (step 6d).
        """
        await self._fetch_into_cache("forecast", self._openmeteo.fetch_forecast_payload)
        await self._fetch_into_cache("ensemble", self._openmeteo.fetch_ensemble_payload)
        await self._record_forecast_history()
        await self.backfill_observations()

    async def backfill_observations(self) -> None:
        """Fill ``observed_mm`` in ``forecast_history`` from DWD observations.

        Fetches the last 48 h of Bright Sky ``/weather`` hourly records and
        writes each real observation (``observation_type != "forecast"``) as
        the observation for its hour start (``timestamp - 1h``, see Data
        conventions). Run from the hourly model refresh — never on a page
        load. Any failure is logged and swallowed: a failing source must
        never break a refresh.
        """
        now = utcnow()
        try:
            payload = await self._brightsky.fetch_weather_payload(now - timedelta(hours=48), now)
            station = parse_station_info(payload)
            if station is not None:
                log.info(
                    "observation backfill: station %s (%s m away)",
                    station[0],
                    station[1],
                )
            observations = parse_hourly_observations(payload, now)
        except Exception:
            log.exception("observation backfill fetch failed")
            return
        if not observations:
            log.info("observation backfill: no observation records in the last 48 h")
            return
        try:
            for hour_start, mm in observations:
                await self._store.set_observation(to_iso(hour_start), mm)
            log.info("observation backfill: %d hourly observations written", len(observations))
        except Exception:
            log.exception("observation backfill: writing observations failed")

    async def _fetch_into_cache(
        self, source: str, fetch: Callable[[], Awaitable[dict[str, Any]]]
    ) -> None:
        try:
            payload = await fetch()
            await self._store.put_cache(source, payload)
            self._last_error.pop(source, None)
            log.info("cache refreshed: %s", source)
        except SourceError as exc:
            self._last_error[source] = str(exc)
            log.warning("refresh %s failed (keeping stale cache): %s", source, exc)

    async def _record_forecast_history(self) -> None:
        """Append this hour's model forecasts to forecast_history."""
        payload, _age = await self._store.get_cache("forecast")
        if payload is None:
            return
        try:
            bundle = parse_forecast(payload, list(self._cfg.models.forecast))
        except SourceError:
            return
        try:
            await self._store.add_forecasts(build_forecast_history_rows(bundle, utcnow()))
        except Exception:  # history is a nicety; never break the refresh
            log.exception("storing forecast history failed")

    # -- read model (page loads) --------------------------------------------
    async def get_current_conditions(self) -> CurrentConditions | None:
        """Parsed cached Bright Sky ``current_weather``.

        ``feels_like_c`` is filled from the forecast cache (apparent
        temperature of the current hour, first model with data).
        """
        payload, _age = await self._store.get_cache("current")
        if payload is None:
            return None
        try:
            cond = parse_current_weather(payload)
        except SourceError:
            return None
        bundle = await self._get_forecast_bundle()
        cond.feels_like_c = _first_hour_apparent(bundle, utcnow())
        return cond

    async def get_radar_nowcast(self) -> RadarNowcast | None:
        """Cached radar parsed into 5-min frames.

        Radius filtering happens in the probability logic (cells carry
        full-grid coordinates; the nowcast carries bbox + location).
        """
        payload, _age = await self._store.get_cache("radar")
        if payload is None:
            return None
        try:
            return parse_radar(payload)
        except SourceError:
            return None

    async def get_radar_next_hour(self) -> dict[str, Any]:
        """12 x 5-min local-rain bar for the next hour (radar nowcast).

        Radius filtering + the rain threshold come from the config, so the bar
        and the radar vote agree on "local rain". Returns the shaped series
        (see :func:`build_radar_next_hour_bar`).
        """
        nowcast = await self.get_radar_nowcast()
        return build_radar_next_hour_bar(
            nowcast,
            utcnow(),
            self._cfg.radar.radius_km,
            self._cfg.radar.grid_size_km,
            self._cfg.probability.radar_cell_rain_threshold_mm,
            n_steps=12,
        )

    async def get_model_votes(self) -> list[ModelVote]:
        """Each configured model's next-60-min precipitation (minutely_15)."""
        return model_votes(await self._get_forecast_bundle(), utcnow())

    async def get_ensemble_vote(self) -> EnsembleVote:
        """Share of ensemble members with > threshold mm in the next hour."""
        payload, _age = await self._store.get_cache("ensemble")
        if payload is None:
            return EnsembleVote(probability_pct=None)
        try:
            data = parse_ensemble(payload)
        except SourceError:
            return EnsembleVote(probability_pct=None)
        return ensemble_vote(data, self._cfg.probability.model_rain_threshold_mm, utcnow())

    async def get_rain_probability(self) -> RainProbability:
        """Weighted combination of radar / model / ensemble signals.

        See README "How the rain probability is calculated". With
        ``use_accuracy_weights`` enabled, the model signal is weighted by each
        model's event accuracy (step 6g) — gated on every voting model having
        enough compared hours, with fallback to equal weights. Always returns
        a :class:`RainProbability` (0 % with a "no data" explanation when
        every signal is missing) so the UI degrades gracefully.
        """
        now = utcnow()
        nowcast = await self.get_radar_nowcast()
        votes = await self.get_model_votes()
        evote = await self.get_ensemble_vote()
        prob_cfg = self._cfg.probability

        radar_available, radar_raining = radar_rain_signal(
            nowcast, now, self._cfg.radar, prob_cfg
        )
        if self._cfg.use_accuracy_weights:
            # Optional accuracy weighting (step 6g): the pure function gates
            # internally — if any voting model lacks enough compared hours,
            # it reports weighted_applied=False and the equal-weight signal.
            # A failing accuracy read (database error) must not break the
            # headline number either: {} makes the same gate fall back to
            # equal weights by itself.
            try:
                accuracy = await self.get_model_accuracy()
            except Exception:
                log.exception("model accuracy read failed; using equal weights")
                accuracy = {}
            model_pct, n_rain, n_total, accuracy_weighted = weighted_model_signal(
                votes,
                accuracy,
                prob_cfg.model_rain_threshold_mm,
                self._cfg.accuracy.min_samples,
            )
        else:
            model_pct, n_rain, n_total = model_rain_signal(
                votes, prob_cfg.model_rain_threshold_mm
            )
            accuracy_weighted = False
        prob, weights = combine_signals(
            prob_cfg,
            radar_available=radar_available,
            radar_raining=radar_raining,
            model_pct=model_pct,
            ensemble_pct=evote.probability_pct,
        )
        if not weights:
            explanation = "No data available yet (all sources empty or failing)"
        else:
            explanation = build_explanation(
                radar_available,
                radar_raining,
                n_rain,
                n_total,
                evote.probability_pct,
                prob_cfg.model_rain_threshold_mm,
                accuracy_weighted,
            )
        return RainProbability(
            probability_pct=round(prob, 1),
            radar_available=radar_available,
            radar_raining=radar_raining,
            models_rain_count=n_rain,
            models_total=n_total,
            ensemble_pct=(
                round(evote.probability_pct, 1) if evote.probability_pct is not None else None
            ),
            weights_used=weights,
            explanation=explanation,
        )

    async def get_24h_model_comparison(self) -> dict[str, Any]:
        """Hourly precipitation per model for the next 24 h (chart data).

        The window is relative to *now* (first hour = current hour), not the
        UTC calendar day — see :func:`build_24h_series`.
        """
        return build_24h_series(await self._get_forecast_bundle(), utcnow())

    async def get_model_accuracy(self) -> dict[str, dict[str, Any]]:
        """Per-model accuracy over the configured window (step 6e).

        Compares stored forecasts against the observed rain of the same
        hour — the same ``> model_rain_threshold_mm`` event the next-hour
        vote uses. Only moves data: raw rows come from the store, the math
        is the pure :func:`model_accuracy`. Returns ``{}`` for ``models``
        while nothing has been compared yet.
        """
        now = utcnow()
        since = to_iso(now - timedelta(days=self._cfg.accuracy.window_days))
        rows = await self._store.compared_forecasts(since)
        return model_accuracy(
            rows, self._cfg.probability.model_rain_threshold_mm
        )

    async def get_source_status(self) -> dict[str, dict[str, Any]]:
        """Per-source cache age + staleness + last error, for the UI."""
        out: dict[str, dict[str, Any]] = {}
        for source, (upstream, _stale_attr) in _SOURCES.items():
            meta = await self.cache_meta(source)
            out[source] = {
                "upstream": upstream,
                "last_error": self._last_error.get(source),
                **meta,
            }
        return out

    # -- helpers --------------------------------------------------------------
    async def cache_meta(self, source: str) -> dict[str, Any]:
        """Cache ``available`` / ``age_seconds`` / ``stale`` for one source.

        ``age_seconds`` is None when the source has never been fetched. Used
        both by :meth:`get_source_status` and by the API endpoints that
        attach a data-age badge to a single source's payload.
        """
        _payload, age = await self._store.get_cache(source)
        stale_minutes = getattr(self._cfg.scheduling, _SOURCES[source][1])
        return {
            "available": age is not None,
            "age_seconds": round(age) if age is not None else None,
            "stale": age is None or age > stale_minutes * 60,
        }

    async def _get_forecast_bundle(self) -> ForecastBundle | None:
        payload, _age = await self._store.get_cache("forecast")
        if payload is None:
            return None
        try:
            return parse_forecast(payload, list(self._cfg.models.forecast))
        except SourceError:
            return None


def _first_hour_apparent(bundle: ForecastBundle | None, now: datetime) -> float | None:
    """Feels-like: apparent temperature of the current hour (first model)."""
    if bundle is None:
        return None
    for m in bundle.models:
        if not m.hourly_time or not m.hourly_apparent_c:
            continue
        for t, v in zip(m.hourly_time, m.hourly_apparent_c):
            if v is not None and t <= now < t + timedelta(hours=1):
                return v
        first = m.hourly_apparent_c[0]
        return first if first is not None else None
    return None
