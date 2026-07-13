class MockProviderAdapter:
    """Deterministic placeholder provider - no real model call happens here.

    Stands in for anthropic_adapter.py / openai_adapter.py / etc. until a real
    provider is approved and API keys are configured. Implements the same
    ProviderAdapter interface (see base.py) so the swap requires no other change.
    """

    async def complete(self, prompt: str) -> str:
        return f"[mock completion] Received {len(prompt)} characters. Acknowledged: {prompt[:80]!r}"
