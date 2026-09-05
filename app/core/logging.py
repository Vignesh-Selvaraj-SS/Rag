import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    """
    One plain, timestamped log format for the app and uvicorn. Third-party
    libraries that are noisy at INFO are pinned to WARNING.
    """

    root = logging.getLogger()

    if root.handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )

    root.addHandler(handler)
    root.setLevel(level.upper())

    for noisy in ("httpx", "httpcore", "fastembed", "qdrant_client", "groq"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
