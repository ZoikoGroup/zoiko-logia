from typing import Protocol


class ProviderAdapter(Protocol):
    """Common interface every provider adapter (real or mock) must implement.

    Swapping the mock adapter for a real one (anthropic_adapter.py etc.) requires
    no change anywhere else in the gateway - only this contract is depended on.
    """

    def complete(self, prompt: str) -> str: ...
