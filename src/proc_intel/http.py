"""Polite JSON fetching: explicit timeouts, bounded retries, exponential backoff."""
from __future__ import annotations

import random
import re
import time
from collections.abc import Callable, Mapping
from typing import Any

import requests

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_TRY_AGAIN = re.compile(r"try again in (\d+) seconds", re.IGNORECASE)


def retry_delay(attempt: int, response_text: str = "", retry_after: str | None = None,
                base: float = 2.0, cap: float = 120.0) -> float:
    """Seconds to wait before retry number `attempt` (0-based).

    A server hint wins: the `Retry-After` header, or the FinancesOne message
    "Try again in N seconds". Otherwise exponential backoff base * 2**attempt, capped.
    """
    if retry_after and retry_after.strip().isdigit():
        return min(float(retry_after), cap)
    hint = _TRY_AGAIN.search(response_text or "")
    if hint:
        # one extra second so the retry lands after the server's window, not on its edge
        return min(float(hint.group(1)) + 1.0, cap)
    return min(base * 2 ** attempt, cap)


def get_json(url: str, params: Mapping[str, Any], *, session: requests.Session | None = None,
             timeout: float = 120.0, max_retries: int = 6,
             sleep: Callable[[float], None] = time.sleep) -> Any:
    """GET `url` and return the decoded JSON body.

    Retries on connection errors, timeouts, HTTP 429/5xx and on a 200 whose body is not JSON
    (the search API occasionally returns an HTML error page). Other 4xx errors raise at once,
    because repeating a bad request cannot fix it.
    """
    http = session or requests
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = http.get(url, params=params, timeout=timeout)
            if resp.status_code in RETRYABLE_STATUS:
                last_error = requests.HTTPError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                delay = retry_delay(attempt, resp.text, resp.headers.get("Retry-After"))
            else:
                resp.raise_for_status()
                return resp.json()
        except (requests.ConnectionError, requests.Timeout, requests.JSONDecodeError) as exc:
            last_error = exc
            delay = retry_delay(attempt)
        # no sleep after the last attempt: the caller gets the error straight away
        if attempt < max_retries:
            # jitter so parallel workers (4 countries at once in p02) do not retry in lockstep
            sleep(delay + random.uniform(0, 1))
    raise RuntimeError(f"giving up on {url} {dict(params)} after {max_retries + 1} attempts") from last_error
