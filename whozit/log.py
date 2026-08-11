# Adapted from UniFace (MIT) — see THIRD_PARTY_UNIFACE_LICENSE.txt
from __future__ import annotations

import logging

__all__ = ['Logger', 'enable_logging']

Logger = logging.getLogger('whozit')
Logger.setLevel(logging.WARNING)
Logger.addHandler(logging.NullHandler())


def enable_logging(level: int = logging.INFO) -> None:
    """Enable verbose logging for whozit."""
    Logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    Logger.addHandler(handler)
    Logger.setLevel(level)
    Logger.propagate = False
