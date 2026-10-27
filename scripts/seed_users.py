"""
scripts/seed_users.py - ONE-TIME SETUP: creates 250 fictional university users
in YOUR OWN test tenant, so the sync has realistic data to read.

Not part of the sync itself. Needs the Graph application permission
User.ReadWrite.All (remove it again after seeding - the sync only needs User.Read.All).

About 10% of users are created with missing fields on purpose
(no department / no job title / no email / no office) to exercise the
"handling missing data" logic. A few accounts are disabled.

Usage:
    python -m scripts.seed_users              create the 250 users
    python -m scripts.seed_users --count 20   create fewer
    python -m scripts.seed_users --delete     delete the users this script created

Requires TENANT_DOMAIN in .env, e.g. TENANT_DOMAIN=yourname.onmicrosoft.com
"""
import argparse
import json
import logging
import os
import random
import secrets
import string
import sys

import requests

from src.auth import GraphAuth
from src.config import load_settings
from src.http_client import HttpError, RetryExhausted, request_with_retry
from src.logger import setup_logging

log = logging.getLogger("seed")
GRAPH = "https://graph.microsoft.com/v1.0"
CREATED_FILE = "state/seeded_users.json"

FIRST = ["Priya", "Ravi", "Ananya", "Arjun", "Sneha", "Rahul", "Divya", "Kiran", "Meera", "Vikram",
         "Emily", "James", "Olivia", "Michael", "Sophia", "Daniel", "Emma", "Ethan", "Ava", "Noah",
         "Maria", "Carlos", "Sofia", "Diego", "Lucia", "Wei", "Mei", "Hiroshi", "Yuki", "Aisha",
         "Omar", "Fatima", "Kwame", "Amara", "Liam", "Grace", "Samuel", "Hannah", "David", "Chloe"]
LAST = ["Sharma", "Reddy", "Patel", "Kumar", "Rao", "Nair", "Iyer", "Gupta", "Smith", "Johnson",
        "Williams", "Brown", "Jones", "Garcia", "Martinez", "Lopez", "Chen", "Wang", "Tanaka", "Kim",
        "Okafor", "Mensah", "Hassan", "Ali", "Miller", "Davis", "Wilson", "Taylor", "Anderson", "Thomas"]
DEPARTMENTS = ["Computer Science", "Data Science", "Business Administration", "Nursing", "Psychology",
               "Mathematics", "English", "Biology", "Finance", "Information Technology",
               "Admissions", "Registrar", "Student Affairs", "Library"]
OFFICES = ["Science Hall 210", "Main Building 105", "Library 3F", "Business Center 12",
           "Admin Building 201", "Online"]
ROLES = [  # (weight, job titles, staff-only departments?)
    (70, ["Undergraduate Student", "Graduate Student"], False),
    (15, ["Professor", "Assistant Professor", "Lecturer", "Adjunct Faculty"], False),
    (15, ["IT Support Specialist", "Admissions Counselor", "Registrar Assistant",
          "Academic Advisor", "Librarian", "Financial Aid Officer"], True),
]


def make_user(i: int, domain: str, rng: random.Random) -> dict:
    first, last = rng.choice(FIRST), rng.choice(LAST)
    nickname = f"{first}.{last}{i:03d}".lower()
    upn = f"{nickname}@{domain}"
    _, titles, staff = rng.choices(ROLES, weights=[r[0] for r in ROLES])[0]
    dept_pool = DEPARTMENTS[10:] if staff else DEPARTMENTS[:10]

    user = {
        "accountEnabled": rng.random() > 0.03,          # ~3% disabled accounts
        "displayName": f"{first} {last}",
        "givenName": first,
        "surname": last,
        "mailNickname": nickname,
        "userPrincipalName": upn,
        "mail": upn,
        "jobTitle": rng.choice(titles),
        "department": rng.choice(dept_pool),
        "officeLocation": rng.choice(OFFICES),
        "passwordProfile": {
            "forceChangePasswordNextSignIn": True,
            "password": _random_password(),
        },
    }
    # Missing data on purpose (~10% each field)
    for field in ("department", "jobTitle", "mail", "officeLocation"):
        if rng.random() < 0.10:
            del user[field]
    return user


def _random_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "Aa1!" + "".join(secrets.choice(alphabet) for _ in range(16))


def create_users(count: int, domain: str, session, auth, settings) -> None:
    rng = random.Random(42)  # same seed -> same names every time
    created = _load_created()
    ok = skipped = failed = 0

    for i in range(1, count + 1):
        user = make_user(i, domain, rng)
        try:
            try:
                resp = _post_user(session, auth, settings, user)
            except HttpError as exc:
                if "mail" in user and exc.status == 400 and "mail" in exc.body.lower():
                    # Some tenants don't allow setting 'mail' without a mailbox -> create without it
                    user.pop("mail")
                    resp = _post_user(session, auth, settings, user)
                else:
                    raise
        except HttpError as exc:
            if "already exists" in exc.body:
                skipped += 1
                log.info("user %d already exists - skipped", i)
            else:
                failed += 1
                log.error("user %d failed: %s", i, exc)
            continue
        except RetryExhausted as exc:
            failed += 1
            log.error("user %d failed: %s", i, exc)
            continue

        created.append(resp.json()["id"])
        ok += 1
        if ok % 25 == 0:
            log.info("created %d users so far...", ok)
            _save_created(created)

    _save_created(created)
    log.info("Done. created=%d, already existed=%d, failed=%d", ok, skipped, failed)


def _post_user(session, auth, settings, user):
    return request_with_retry(session, "POST", f"{GRAPH}/users", json=user,
                              auth_header=auth.auth_header,
                              max_attempts=settings.max_attempts, timeout=settings.request_timeout)


def delete_users(session, auth, settings) -> None:
    ids = _load_created()
    for uid in ids:
        try:
            request_with_retry(session, "DELETE", f"{GRAPH}/users/{uid}", auth_header=auth.auth_header,
                               max_attempts=settings.max_attempts, timeout=settings.request_timeout)
        except (HttpError, RetryExhausted) as exc:
            log.error("delete %s failed: %s", uid, exc)
    _save_created([])
    log.info("Deleted %d seeded users", len(ids))


def _load_created() -> list:
    if os.path.exists(CREATED_FILE):
        with open(CREATED_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    return []


def _save_created(ids: list) -> None:
    os.makedirs(os.path.dirname(CREATED_FILE), exist_ok=True)
    with open(CREATED_FILE, "w", encoding="utf-8") as fh:
        json.dump(ids, fh)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=250)
    parser.add_argument("--delete", action="store_true")
    args = parser.parse_args()

    settings = load_settings()
    setup_logging(settings.log_dir)
    domain = os.getenv("TENANT_DOMAIN", "").strip()
    if not domain and not args.delete:
        sys.exit("Set TENANT_DOMAIN in .env (e.g. yourname.onmicrosoft.com)")

    session = requests.Session()
    auth = GraphAuth(settings.tenant_id, settings.client_id, settings.client_secret)
    if args.delete:
        delete_users(session, auth, settings)
    else:
        create_users(args.count, domain, session, auth, settings)


if __name__ == "__main__":
    main()
