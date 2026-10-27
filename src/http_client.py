"""
http_client.py - One shared function for HTTP calls with retries.

Rules:
  * 2xx/3xx             -> success, return the response
  * 429 Too Many Req.   -> wait for the server's Retry-After header, then retry
  * 500/502/503/504     -> exponential backoff (1s, 2s, 4s, 8s ... + jitter), then retry
  * network error/timeout -> same backoff, then retry
  * other 4xx (400, 401, 403, 404, 409 ...) -> do NOT retry (the request itself is wrong);
    raise HttpError so the caller decides what to do
  * After max_attempts -> raise RetryExhausted
"""
import logging
import random
import time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests

log = logging.getLogger("http")

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class HttpError(Exception):
    """Non-retryable HTTP error (e.g. 400, 401, 403, 404, 409)."""

    def __init__(self, status: int, method: str, url: str, body: str):
        self.status = status
        self.body = body
        super().__init__(f"{method} {_short(url)} -> HTTP {status}: {body[:300]}")


class RetryExhausted(Exception):
    """All retry attempts failed."""


def _short(url: str) -> str:
    """URL without the query string (shorter logs, no tokens/filters leaked)."""
    parts = urlsplit(url)
    return f"{parts.netloc}{parts.path}"


def _backoff_delay(attempt: int, base: float, max_delay: float) -> float:
    # attempt 1 -> ~1s, 2 -> ~2s, 3 -> ~4s, 4 -> ~8s ... plus random jitter so many
    # clients don't all retry at the exact same moment
    return min(max_delay, base * 2 ** (attempt - 1)) + random.uniform(0, 0.5)


def _retry_after_seconds(response: requests.Response, max_delay: float):
    """Read the Retry-After header (either seconds, or an HTTP date)."""
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError):
            return None
    return max(0.0, min(seconds, max_delay))


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    max_attempts: int = 5,
    timeout: int = 30,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    auth_header=None,          # optional function returning "Bearer <token>"
    headers: dict | None = None,
    **kwargs,
) -> requests.Response:
    base_headers = dict(headers or {})

    for attempt in range(1, max_attempts + 1):
        req_headers = dict(base_headers)
        if auth_header:
            # Fetched on every attempt, so a token that expires mid-run is refreshed
            req_headers["Authorization"] = auth_header()

        try:
            response = session.request(method, url, headers=req_headers, timeout=timeout, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as exc:
            reason = f"network error ({exc.__class__.__name__})"
            wait = _backoff_delay(attempt, base_delay, max_delay)
        else:
            if response.status_code < 400:
                return response
            if response.status_code not in RETRYABLE_STATUS:
                raise HttpError(response.status_code, method, url, response.text)

            reason = f"HTTP {response.status_code}"
            wait = None
            if response.status_code == 429:
                wait = _retry_after_seconds(response, max_delay)
                if wait is not None:
                    reason += f" (server asked to wait {wait:.0f}s via Retry-After)"
            if wait is None:
                wait = _backoff_delay(attempt, base_delay, max_delay)

        if attempt == max_attempts:
            raise RetryExhausted(f"{method} {_short(url)} failed after {max_attempts} attempts: {reason}")

        log.warning(
            "%s %s -> %s | attempt %d/%d, retrying in %.1fs",
            method, _short(url), reason, attempt, max_attempts, wait,
        )
        time.sleep(wait)

    raise RetryExhausted("unreachable")  # loop always returns or raises
