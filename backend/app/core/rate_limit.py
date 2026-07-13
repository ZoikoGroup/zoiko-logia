"""Shared slowapi Limiter instance — kept out of app.main to avoid a circular
import (app.main -> api router -> orchestration router -> app.main)."""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
