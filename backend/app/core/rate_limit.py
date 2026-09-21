"""Shared slowapi Limiter instance — kept out of app.main to avoid a circular
import (app.main -> api router -> orchestration router -> app.main)."""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=get_settings().RATE_LIMIT_STORAGE_URI,
)
