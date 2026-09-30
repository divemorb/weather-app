"""Run the Python backend (the reference) with a frozen clock.

Used only to produce the goldens: ``WETTER_FAKE_NOW`` (ISO-8601 UTC) is
the time the app believes it is. The Python code stays unchanged; this
launcher patches the few places that read the clock (``utcnow`` as
imported by each module, and the store's ``time`` module) after import
and before the app starts. Runs inside the Python image
(``localhost/wetter_weather``) with the repo at the working directory.

Usage: python rust/contract/pyapp.py PORT
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import time as _time

sys.path.insert(0, os.getcwd())

import uvicorn  # noqa: E402

import app.aggregator  # noqa: E402
import app.brightsky_client  # noqa: E402
import app.main  # noqa: E402
import app.scheduler  # noqa: E402
import app.store  # noqa: E402
import app.times  # noqa: E402

fake = os.environ.get("WETTER_FAKE_NOW")
if fake:
    fixed = dt.datetime.fromisoformat(fake.replace("Z", "+00:00"))

    def utcnow() -> dt.datetime:
        return fixed

    for module in (app.times, app.aggregator, app.brightsky_client, app.scheduler):
        module.utcnow = utcnow

    class FrozenTime:
        """Stands in for the ``time`` module inside app.store."""

        @staticmethod
        def time() -> float:
            return fixed.timestamp()

        @staticmethod
        def gmtime(secs=None):
            return _time.gmtime(fixed.timestamp() if secs is None else secs)

        strftime = staticmethod(_time.strftime)

    app.store.time = FrozenTime

uvicorn.run(app.main.app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
