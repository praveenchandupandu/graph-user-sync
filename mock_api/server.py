"""
mock_api/server.py - A small fake "university HR system" REST API.

Endpoints:
    GET  /health   -> {"status": "ok"}
    POST /users    -> 201 created | 200 updated | 409 duplicate | 400 invalid
    GET  /users    -> everything received so far

Failure injection (so the client's retry logic can be demonstrated):
    FAIL_500_RATE  share of POSTs answered with 500 Internal Server Error (default 0.05)
    FAIL_429_RATE  share of POSTs answered with 429 Too Many Requests  (default 0.03)
    RETRY_AFTER    seconds put in the 429 Retry-After header            (default 2)
Set both rates to 0 for a clean run.

Run:  python mock_api/server.py
"""
import logging
import os
import random
import threading

from flask import Flask, jsonify, request

FAIL_500_RATE = float(os.getenv("FAIL_500_RATE", "0.05"))
FAIL_429_RATE = float(os.getenv("FAIL_429_RATE", "0.03"))
RETRY_AFTER = int(os.getenv("RETRY_AFTER", "2"))
PORT = int(os.getenv("MOCK_API_PORT", "5000"))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | MOCK-API | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("mock_api")
logging.getLogger("werkzeug").setLevel(logging.WARNING)

_lock = threading.Lock()
_users: dict[str, dict] = {}          # source_id -> latest record
_idempotency_keys: set[str] = set()   # keys already processed


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.post("/users")
def create_user():
    # --- simulated failures (before any data is stored) ---
    roll = random.random()
    if roll < FAIL_500_RATE:
        log.info("injected 500 Internal Server Error")
        return jsonify(error="simulated internal server error"), 500
    if roll < FAIL_500_RATE + FAIL_429_RATE:
        log.info("injected 429 Too Many Requests (Retry-After: %ss)", RETRY_AFTER)
        return jsonify(error="rate limit exceeded"), 429, {"Retry-After": str(RETRY_AFTER)}

    # --- validation ---
    record = request.get_json(silent=True)
    if not isinstance(record, dict) or not record.get("source_id"):
        return jsonify(error="body must be JSON with a 'source_id'"), 400

    key = request.headers.get("Idempotency-Key")
    with _lock:
        if key and key in _idempotency_keys:
            log.info("duplicate request rejected (Idempotency-Key %s)", key)
            return jsonify(status="duplicate", source_id=record["source_id"]), 409
        if key:
            _idempotency_keys.add(key)

        existed = record["source_id"] in _users
        _users[record["source_id"]] = record

    status = "updated" if existed else "created"
    log.info("%s user %s (total stored: %d)", status, record["source_id"], len(_users))
    return jsonify(status=status, source_id=record["source_id"]), (200 if existed else 201)


@app.get("/users")
def list_users():
    with _lock:
        return jsonify(count=len(_users), users=list(_users.values()))


if __name__ == "__main__":
    log.info("Mock API on http://127.0.0.1:%d  (500 rate=%.0f%%, 429 rate=%.0f%%)",
             PORT, FAIL_500_RATE * 100, FAIL_429_RATE * 100)
    app.run(host="127.0.0.1", port=PORT, threaded=True)
