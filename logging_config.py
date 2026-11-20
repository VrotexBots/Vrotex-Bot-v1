import logging
import os
import sys


def setup_logging():
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    numeric_level = getattr(logging, log_level, logging.INFO)

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout)
        ],
        force=True,
    )

    return logging.getLogger("vrotex")


def get_logger(name: str):
    return logging.getLogger(f"vrotex.{name}")


logger = setup_logging()
