"""Reviewer-only features are hidden unless CSO_ADVANCED=1 (read at call time so tests can switch it)."""
import os


def advanced() -> bool:
    return os.environ.get("CSO_ADVANCED") == "1"
