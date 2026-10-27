"""
main.py - Runs the whole sync:

  1. Load settings (.env)         4. Transform each user to target JSON
  2. Check the mock API is up     5. Skip users already sent (SQLite state)
  3. Read users from Graph        6. POST new/changed users, with retries
     page by page                 7. Save users.json + print a summary

Usage:
    python -m src.main             normal run
    python -m src.main --dry-run   read + transform + save JSON, but send nothing
"""
import argparse
import json
import logging
import os
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone

import requests

from .api_client import TargetApiClient
from .auth import AuthError, GraphAuth
from .config import load_settings
from .graph_client import iter_user_pages
from .http_client import HttpError, RetryExhausted
from .logger import setup_logging
from .state_store import StateStore
from .transform import fingerprint, transform_user

log = logging.getLogger("sync")


def run(dry_run: bool = False) -> int:
    settings = load_settings()
    log_file = setup_logging(settings.log_dir)
    run_id = uuid.uuid4().hex[:8]
    started = time.monotonic()
    synced_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    log.info("=== Sync run %s started%s ===", run_id, " (DRY RUN - nothing will be sent)" if dry_run else "")
    log.info("Target API: %s | page size: %d | max attempts: %d",
             settings.target_api_url, settings.page_size, settings.max_attempts)

    session = requests.Session()
    try:
        auth = GraphAuth(settings.tenant_id, settings.client_id, settings.client_secret)
    except AuthError as exc:
        log.error("Authentication with Microsoft failed: %s", exc)
        return 2
    api = TargetApiClient(session, settings.target_api_url, settings.max_attempts, settings.request_timeout)
    store = StateStore(settings.state_db_path)

    stats: Counter = Counter()
    failed_ids: list[str] = []
    output_records: list[dict] = []
    seen_this_run: set[str] = set()

    try:
        if not dry_run:
            try:
                api.health_check()
            except (HttpError, RetryExhausted) as exc:
                log.error("Target API is not reachable (%s). Is the mock API running?", exc)
                return 2

        for page in iter_user_pages(session, auth, settings.page_size,
                                    settings.max_attempts, settings.request_timeout):
            for raw in page:
                stats["fetched"] += 1
                record, warnings = transform_user(raw)
                user_ref = raw.get("id") or "<no id>"
                for warning in warnings:
                    log.warning("user %s: %s", user_ref, warning)

                if record is None:
                    stats["invalid_skipped"] += 1
                    continue
                if record["missing_fields"]:
                    stats["with_missing_fields"] += 1

                source_id = record["source_id"]
                if source_id in seen_this_run:  # same user returned twice in one run
                    stats["duplicate_in_run"] += 1
                    continue
                seen_this_run.add(source_id)

                record_hash = fingerprint(record)
                output_records.append({**record, "synced_at": synced_at})

                state = store.status(source_id, record_hash)
                if state == "unchanged":
                    stats["skipped_unchanged"] += 1
                    log.debug("user %s unchanged since last run - skipped", source_id)
                    continue
                if dry_run:
                    stats[f"would_send_{state}"] += 1
                    continue

                try:
                    result = api.send_user({**record, "synced_at": synced_at}, record_hash)
                except (HttpError, RetryExhausted) as exc:
                    stats["failed"] += 1
                    failed_ids.append(source_id)
                    log.error("user %s: could not be sent - %s", source_id, exc)
                    continue

                store.mark_sent(source_id, record_hash)
                stats[result] += 1
                log.info("user %s: %s (%s)", source_id, result, state)

    except AuthError as exc:
        log.error("Authentication with Microsoft failed: %s", exc)
        return 2
    except (HttpError, RetryExhausted) as exc:
        log.error("Reading users from Microsoft Graph failed: %s", exc)
        return 2
    finally:
        store.close()

    # Save the transformed JSON
    os.makedirs(os.path.dirname(settings.output_path) or ".", exist_ok=True)
    with open(settings.output_path, "w", encoding="utf-8") as fh:
        json.dump({"run_id": run_id, "synced_at": synced_at, "count": len(output_records),
                   "users": output_records}, fh, indent=2)

    elapsed = time.monotonic() - started
    log.info("Transformed JSON written to %s", settings.output_path)
    log.info("=== Summary (run %s, %.1fs) ===", run_id, elapsed)
    for key in ("fetched", "created", "updated", "already_received", "skipped_unchanged",
                "would_send_new", "would_send_changed", "with_missing_fields",
                "invalid_skipped", "duplicate_in_run", "failed"):
        if stats[key] or key in ("fetched", "failed"):
            log.info("  %-20s %d", key, stats[key])
    if failed_ids:
        log.warning("Failed user ids (will be retried next run): %s", ", ".join(failed_ids))
    log.info("Log file: %s", log_file)

    return 1 if failed_ids else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync users from Microsoft Graph to a REST API")
    parser.add_argument("--dry-run", action="store_true", help="read and transform only, send nothing")
    args = parser.parse_args()
    sys.exit(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
