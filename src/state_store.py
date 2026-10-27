"""
state_store.py - Duplicate prevention using a small SQLite database.

For every user that was successfully sent we store:
    source_id (Graph user id)  |  record_hash (fingerprint)  |  last_sent_at

Before sending a user we compare:
    not in table              -> "new"        -> send
    in table, same hash       -> "unchanged"  -> skip (duplicate)
    in table, different hash  -> "changed"    -> send the update

A user is written to the table ONLY after the API confirmed success,
so a failed user is automatically retried on the next run.
"""
import os
import sqlite3
from datetime import datetime, timezone


class StateStore:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_users (
                source_id    TEXT PRIMARY KEY,
                record_hash  TEXT NOT NULL,
                last_sent_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def status(self, source_id: str, record_hash: str) -> str:
        row = self._conn.execute(
            "SELECT record_hash FROM processed_users WHERE source_id = ?", (source_id,)
        ).fetchone()
        if row is None:
            return "new"
        return "unchanged" if row[0] == record_hash else "changed"

    def mark_sent(self, source_id: str, record_hash: str) -> None:
        self._conn.execute(
            """
            INSERT INTO processed_users (source_id, record_hash, last_sent_at)
            VALUES (?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                record_hash = excluded.record_hash,
                last_sent_at = excluded.last_sent_at
            """,
            (source_id, record_hash, datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()  # commit per user: a crash mid-run never loses confirmed sends

    def close(self) -> None:
        self._conn.close()
