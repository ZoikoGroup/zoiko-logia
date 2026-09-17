# Provider adapter - Google Gemini
import asyncio
import logging
import os
import random

# Reuse the exact same answering system prompt as the Groq adapter, so
# switching providers changes only *who* answers, not *how* it is asked to
# answer. (Importing keeps the two providers identical instead of drifting.)
from app.domains.model_gateway.providers.groq_adapter import _SYSTEM_PROMPT

# Default Gemini model. Override with GEMINI_MODEL in the environment. Use the
# exact id your API key can access (list them: models?key=... — see
# RUNNING_KRITON.md). gemini-flash-latest always resolves to a current flash
# model (so it won't 404 when a dated version is retired — e.g. gemini-2.5-flash
# is blocked for new keys).
_DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
logger = logging.getLogger(__name__)


def _status_code(exc: Exception) -> int | None:
    """Extract only the sanitized HTTP status from google-genai errors."""
    for value in (getattr(exc, "status_code", None), getattr(exc, "code", None)):
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def _is_transient(exc: Exception) -> bool:
    status = _status_code(exc)
    if status is not None:
        return status in _RETRYABLE_STATUS_CODES
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    name = type(exc).__name__.casefold()
    return any(token in name for token in ("timeout", "connection", "servererror", "serviceunavailable"))


def _retry_delay(exc: Exception) -> float:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    retry_after = headers.get("retry-after") if headers else None
    if retry_after:
        try:
            return max(0.0, min(float(retry_after), 2.0))
        except (TypeError, ValueError):
            pass
    return random.uniform(0.3, 0.8)


class GeminiAdapter:
    """Google Gemini provider adapter. Reads GEMINI_API_KEY (or GOOGLE_API_KEY)
    from the environment and answers via the google-genai SDK.

    async, matching the ProviderAdapter protocol (providers/base.py) — see
    GroqAdapter's docstring for why this must not be a sync network call. The
    google-genai client exposes an async surface at `client.aio`, so no thread
    offloading is needed.
    """

    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.client = None
        if self.api_key:
            try:
                from google import genai
                from google.genai import types

                # Explicit bounded timeout — see GroqAdapter.__init__'s
                # docstring for why an unbounded LLM call is the one place in
                # this pipeline that could actually look like a hang to the
                # user, unlike every other network call here (already 6s-
                # bounded and fail-soft).
                self.client = genai.Client(
                    api_key=self.api_key,
                    http_options=types.HttpOptions(timeout=25_000),
                )
            except Exception:
                # SDK not installed / failed to init — stay soft (complete()
                # returns a clear error string rather than crashing the request).
                self.client = None

    async def complete(self, prompt: str, model: str = _DEFAULT_MODEL) -> str:
        if not self.client:
            return (
                "[Error: Gemini not configured. Add GEMINI_API_KEY to backend/.env "
                "and install 'google-genai' (pip install google-genai).]"
            )

        from google.genai import types
        config = types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            temperature=0.0,
        )

        async def call() -> str:
            response = await self.client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            return response.text or ""

        try:
            return await call()
        except Exception as e:
            if not _is_transient(e):
                return f"[Error connecting to Gemini API: {str(e)}]"
            status = _status_code(e)
            logger.info("gemini transient failure; retrying once (status=%s, attempt=1)", status)
            await asyncio.sleep(_retry_delay(e))
            try:
                return await call()
            except Exception as retry_exc:
                logger.info(
                    "gemini retry failed; provider fallback may proceed (status=%s, attempt=2)",
                    _status_code(retry_exc),
                )
                return f"[Error connecting to Gemini API: {str(retry_exc)}]"
