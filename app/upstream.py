"""Shared upstream HTTP plumbing.

Upstream data is *untrusted*: the parsers on the request path are wrapped
with :func:`malformed_is_source_error`, so a wrong type or missing key
raises :exc:`SourceError` instead of an unhandled 500. Both clients read
bodies through :func:`stream_json_capped`, which aborts above
:data:`MAX_RESPONSE_BYTES` (memory + SQLite cache protection).
"""
from __future__ import annotations

import functools
import json
from typing import Any, Callable

import httpx2

#: Cap for upstream response bodies; real payloads are ≤ ~20 KB, so 5 MB is
#: far above anything legitimate (memory + SQLite cache protection).
MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class SourceError(Exception):
    """A data source failed or returned an unusable payload."""


#: Payload-shape errors re-raised as :exc:`SourceError` by
#: :func:`malformed_is_source_error`.
_MALFORMED_TYPES = (
    KeyError,
    TypeError,
    ValueError,
    AttributeError,
    IndexError,
    OverflowError,
)


def malformed_is_source_error(label: str) -> Callable:
    """Re-raise payload-shape errors as :exc:`SourceError`.

    A :exc:`SourceError` raised inside the parser passes through unchanged.
    """

    def wrap(func: Callable) -> Callable:
        @functools.wraps(func)
        def inner(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except _MALFORMED_TYPES as exc:
                raise SourceError(f"{label}: malformed payload ({exc!r})") from exc

        return inner

    return wrap


async def stream_json_capped(
    http: httpx2.AsyncClient, url: str, params: dict[str, Any]
) -> Any:
    """GET ``url`` and parse the JSON body, aborting above MAX_RESPONSE_BYTES.

    Untrusted servers could otherwise answer with multi-GB bodies that
    exhaust memory and the SQLite cache. Raises :exc:`SourceError` for HTTP
    errors, size violations and undecodable bodies.
    """
    try:
        async with http.stream("GET", url, params=params) as resp:
            resp.raise_for_status()
            declared = resp.headers.get("content-length")
            if declared is not None:
                try:
                    if int(declared) > MAX_RESPONSE_BYTES:
                        raise SourceError(
                            f"response declares {declared} bytes, "
                            f"over the {MAX_RESPONSE_BYTES} byte cap"
                        )
                except ValueError as exc:
                    raise SourceError(f"bad content-length header: {declared!r}") from exc
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    raise SourceError(
                        f"response body exceeds the {MAX_RESPONSE_BYTES} byte cap"
                    )
                chunks.append(chunk)
            body = b"".join(chunks)
    except (httpx2.HTTPError, ValueError) as exc:
        raise SourceError(f"request failed: {exc}") from exc
    try:
        return json.loads(body)
    # Deeply nested JSON ("[[[[…") is far below the size cap but exhausts the
    # parser's recursion limit; it is a RecursionError, not a ValueError.
    except (ValueError, RecursionError) as exc:
        raise SourceError(f"response is not valid JSON: {exc}") from exc
