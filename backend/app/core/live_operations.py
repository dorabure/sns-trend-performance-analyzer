"""Execution switch, deliberately disabled unless explicitly configured."""
import os


def live_enabled():
    return os.getenv('LIVE_MODE_ENABLED', 'false').strip().lower() == 'true'
