"""One model execution allowance for the whole orchestration request."""
from contextvars import ContextVar
from functools import wraps
import time

from app.domains.model_gateway.agent_budget import GenerationBudget

_current: ContextVar[GenerationBudget | None] = ContextVar('model_request_budget', default=None)


def current_budget() -> GenerationBudget | None:
    return _current.get()


def request_execution_scope(func):
    @wraps(func)
    async def wrapped(*args, **kwargs):
        if current_budget() is not None:
            return await func(*args, **kwargs)
        from app.core.config import get_settings
        settings = get_settings()
        budget = GenerationBudget(
            max_total_tokens=settings.AGENT_MAX_TOKENS,
            max_completion_tokens=settings.AGENT_MAX_COMPLETION_TOKENS,
            max_request_tokens=settings.AGENT_MAX_REQUEST_TOKENS,
            max_cost_usd=settings.AGENT_MAX_COST_USD,
            price_per_million_tokens=settings.MODEL_PRICE_PER_MILLION_TOKENS,
            max_calls=settings.MODEL_REQUEST_MAX_CALLS,
            deadline=time.monotonic() + (kwargs.get('deadline_seconds') or settings.ASK_KRITON_TIMEOUT_SECONDS),
        )
        token = _current.set(budget)
        try:
            return await func(*args, **kwargs)
        finally:
            budget.closed = True
            _current.reset(token)
    return wrapped
