import os
from groq import AsyncGroq

_SYSTEM_PROMPT = (
    "You are Kriton™, a helpful professional advisor. Answer based only on "
    "the provided context. If no context is provided, state that you cannot "
    "answer without sufficient source material."
)


class GroqAdapter:
    """Groq provider adapter. Reads GROQ_API_KEY from environment.

    async, matching the ProviderAdapter protocol (providers/base.py) — uses
    AsyncGroq rather than the sync client, since a sync network call awaited
    from model_gateway/service.py's async handler would block the whole
    event loop for every concurrent request while waiting on the model.
    """

    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY")
        self.client = AsyncGroq(api_key=self.api_key) if self.api_key else None

    async def complete(self, prompt: str, model: str = "llama-3.1-8b-instant") -> str:
        if not self.client:
            return "[Error: GROQ_API_KEY not found in environment. Please add it to backend/.env]"

        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,  # Deterministic routing/answering per governance
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            return f"[Error connecting to Groq API: {str(e)}]"
