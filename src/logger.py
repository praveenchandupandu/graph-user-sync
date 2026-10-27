"""
logger.py - One place to configure logging.

Every run writes to the console AND to a timestamped file in logs/,
so there is a permanent record of what happened in each run.
Privacy: the code logs user IDs, never names or emails.
"""
import logging
import os
from datetime import datetime

FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-12s | %(message)s"


def setup_logging(log_dir: str, level: int = logging.INFO) -> str:
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"sync_{datetime.now():%Y%m%d_%H%M%S}.log")

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    formatter = logging.Formatter(FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Keep third-party libraries quiet unless something is wrong
    for noisy in ("urllib3", "msal"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return log_file
