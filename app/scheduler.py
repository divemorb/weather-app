"""APScheduler wiring: refresh cadence for the cache.

Radar (Bright Sky): every N minutes (default 5) — never on page load.
Models (Open-Meteo): every M minutes (default 60).

Step 3 plugs the aggregator's refresh methods in; the structure here is
final so main.py can already start/stop it.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .aggregator import Aggregator
from .config import AppConfig

log = logging.getLogger("weather.scheduler")


def build_scheduler(cfg: AppConfig, aggregator: Aggregator) -> AsyncIOScheduler:
    """Create (do NOT start) the scheduler with both refresh jobs."""
    scheduler = AsyncIOScheduler(timezone="UTC")

    def _radar_job() -> None:
        log.info("scheduled radar refresh")
        # TODO(step 3): run asyncio.ensure_future(aggregator.refresh_radar())
        # with error handling so one failure never kills the scheduler.
        raise NotImplementedError("step 3")

    def _models_job() -> None:
        log.info("scheduled models refresh")
        # TODO(step 3): run asyncio.ensure_future(aggregator.refresh_models())
        raise NotImplementedError("step 3")

    scheduler.add_job(
        _radar_job,
        IntervalTrigger(minutes=cfg.scheduling.radar_interval_minutes),
        id="radar_refresh",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        _models_job,
        IntervalTrigger(minutes=cfg.scheduling.models_interval_minutes),
        id="models_refresh",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    return scheduler


async def initial_refresh(aggregator: Aggregator) -> None:
    """Warm the cache once at startup (before the scheduler takes over).

    TODO(step 3): run both refreshes concurrently (asyncio.gather with
    return_exceptions=True) so a slow/failing source can't delay startup.
    """
    raise NotImplementedError("step 3")
