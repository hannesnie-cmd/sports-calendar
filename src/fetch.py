"""Small JSON-over-HTTP helper with retries."""

from __future__ import annotations

import time

import requests

USER_AGENT = "hannes-sports-calendar/1.0 (+https://github.com)"
_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT


class FetchError(Exception):
    pass


def get_json(url: str, params: dict | None = None, retries: int = 2, timeout: float = 20) -> dict:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = _session.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            last = FetchError(f"HTTP {r.status_code} for {r.url}")
            if r.status_code < 500 and r.status_code != 429:
                break
        except (requests.RequestException, ValueError) as e:
            last = e
        if attempt < retries:
            time.sleep(2 * (attempt + 1))
    raise FetchError(str(last))
