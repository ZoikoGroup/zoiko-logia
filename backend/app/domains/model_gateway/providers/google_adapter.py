# Provider adapter - Google Gemini
import os

# Reuse the exact same answering system prompt as the Groq adapter, so
# switching providers changes only *who* answers, not *how* it is asked to
# answer. (Importing keeps the two providers identical instead of drifting.)
from app.domains.model_gateway.providers.groq_adapter import _SYSTEM_PROMPT

# Default Gemini model. Override with GEMINI_MODEL in the environment. Use the
# exact id your API key can access (list them: models?key=... — see
# RUNNING_KRITON.md). gemini-flash-latest always resolves to a current flash
# model (so it won't 404 when a dated version is retired — e.g. gemini-2.5-flash
# is blocked for new keys) and is much better than Llama at reliably emitting
# the ```chart / ```mermaid blocks.
_DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")


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

                self.client = genai.Client(api_key=self.api_key)
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

        try:
            from google.genai import types

            response = await self.client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM_PROMPT,
                    temperature=0.0,  # Deterministic answering per governance
                ),
            )
            return response.text or ""
        except Exception as e:
            return f"[Error connecting to Gemini API: {str(e)}]"
