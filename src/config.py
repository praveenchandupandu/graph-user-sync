"""
config.py - Loads all settings from the .env file / environment variables.

Why: secrets (client secret) must never be hard-coded in source code.
They live in a local .env file that is excluded from Git (.gitignore).
"""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    tenant_id: str
    client_id: str
    # repr=False -> the secret is never printed if someone logs the settings object
    client_secret: str = field(repr=False)
    target_api_url: str = "http://127.0.0.1:5000"
    page_size: int = 100
    max_attempts: int = 5
    request_timeout: int = 30
    state_db_path: str = "state/processed_users.db"
    output_path: str = "output/users.json"
    log_dir: str = "logs"


REQUIRED = ("TENANT_ID", "CLIENT_ID", "CLIENT_SECRET")


def load_settings() -> Settings:
    load_dotenv()  # reads .env in the current folder (if present) into environment variables

    missing = [name for name in REQUIRED if not os.getenv(name, "").strip()]
    if missing:
        raise SystemExit(
            f"Missing required setting(s): {', '.join(missing)}. "
            "Copy .env.example to .env and fill in your values."
        )

    return Settings(
        tenant_id=os.environ["TENANT_ID"].strip(),
        client_id=os.environ["CLIENT_ID"].strip(),
        client_secret=os.environ["CLIENT_SECRET"].strip(),
        target_api_url=os.getenv("TARGET_API_URL", Settings.target_api_url).rstrip("/"),
        page_size=int(os.getenv("PAGE_SIZE", Settings.page_size)),
        max_attempts=int(os.getenv("MAX_ATTEMPTS", Settings.max_attempts)),
        request_timeout=int(os.getenv("REQUEST_TIMEOUT", Settings.request_timeout)),
        state_db_path=os.getenv("STATE_DB_PATH", Settings.state_db_path),
        output_path=os.getenv("OUTPUT_PATH", Settings.output_path),
        log_dir=os.getenv("LOG_DIR", Settings.log_dir),
    )
