"""BHASHINI exceptions."""
from __future__ import annotations


class BhashiniError(Exception):
    """Base BHASHINI error (safe message, no secrets)."""


class BhashiniUnavailable(BhashiniError):
    """The language service is not configured or not reachable."""
