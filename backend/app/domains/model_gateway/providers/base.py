from typing import Protocol


class ProviderAdapter(Protocol):
    """Common interface every provider adapter (real or mock) must implement.

    Swapping the mock adapter for a real one (anthropic_adapter.py etc.) requires
    no change anywhere else in the gateway - only this contract is depended on.

    async, not sync: a real adapter makes a network call, and calling that
    synchronously from model_gateway/service.py's async request handler would
    block the whole event loop for every concurrent request while waiting on
    the model.
    """

    async def complete(self, prompt: str) -> str: ...
