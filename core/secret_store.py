"""Compatibility interface for the local credential vault."""
from __future__ import annotations

from core.local_vault import get_value, set_value


def get_secret(name: str):
    return get_value(name)


def set_secret(name: str, value: str) -> None:
    set_value(name, value)
