"""
api_client.py - Sends transformed records to the mock REST API (REST POST).

Each request carries an Idempotency-Key header (user id + content hash).
If the same record is ever sent twice (for example the API saved it but
the response was lost and we retried), the API recognises the key and
answers 409 instead of creating a duplicate. That is the second layer of
duplicate protection, on the receiving side.
"""
import logging

import requests

from .http_client import HttpError, request_with_retry

log = logging.getLogger("target_api")


class TargetApiClient:
    def __init__(self, session: requests.Session, base_url: str, max_attempts: int, timeout: int):
        self._session = session
        self._base_url = base_url
        self._max_attempts = max_attempts
        self._timeout = timeout

    def health_check(self) -> None:
        """Fail fast if the API is not reachable, before we read anything from Graph."""
        request_with_retry(self._session, "GET", f"{self._base_url}/health",
                           max_attempts=2, timeout=5)

    def send_user(self, record: dict, record_hash: str) -> str:
        """Returns 'created', 'updated' or 'already_received'. Raises on failure."""
        headers = {"Idempotency-Key": f"{record['source_id']}:{record_hash[:16]}"}
        try:
            response = request_with_retry(
                self._session, "POST", f"{self._base_url}/users",
                json=record, headers=headers,
                max_attempts=self._max_attempts, timeout=self._timeout,
            )
        except HttpError as exc:
            if exc.status == 409:  # API already has exactly this record
                return "already_received"
            raise
        return response.json().get("status", "created")
