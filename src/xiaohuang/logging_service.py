from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path


def configure_logging(log_dir: str | Path, name: str, level: str = "INFO") -> logging.Logger:
    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_handler = logging.FileHandler(directory / f"{name}_{timestamp}.log", encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger

