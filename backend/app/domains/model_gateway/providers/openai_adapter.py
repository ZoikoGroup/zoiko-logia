import os
from openai import AsyncOpenAI

_SYSTEM_PROMPT = (
    "You are Kriton™, a helpful professional advisor. Answer based only on "
    "the provided context. If no context is provided, state that you cannot "
    "answer without sufficient source material."
)


class OpenAIAdapter:
    """OpenAI provider adapter. Reads OPENAI_API_KEY from environment.

    async, matching the ProviderAdapter protocol (providers/base.py) — see
    GroqAdapter's docstring for why this must not be a sync network call.
    """

    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        self.client = AsyncOpenAI(api_key=self.api_key) if self.api_key else None

    async def complete(self, prompt: str, model: str = "gpt-4o-mini") -> str:
        if not self.client:
            return "[Error: OPENAI_API_KEY not found in environment. Please add it to backend/.env]"

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
            return f"[Error connecting to OpenAI API: {str(e)}]"
