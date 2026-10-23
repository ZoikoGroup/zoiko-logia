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
            reasoning_effort=getattr(settings, "AGENT_REASONING_EFFORT", ""),
            deadline=time.monotonic() + (kwargs.get('deadline_seconds') or settings.ASK_KRITON_TIMEOUT_SECONDS),
        )
        # Each call reserves up to its request limit before it is sent, so a
        # run budget below a few full requests stops after a handful of calls
        # (the test server's 16,000-token requests under a 64,000 budget).
        if budget.max_request_tokens and budget.max_total_tokens < 6 * budget.max_request_tokens:
            import logging
            logging.getLogger(__name__).warning(
                "AGENT_MAX_TOKENS=%d allows fewer than 6 requests of AGENT_MAX_REQUEST_TOKENS=%d per question",
                budget.max_total_tokens, budget.max_request_tokens)
        token = _current.set(budget)
        try:
            return await func(*args, **kwargs)
        finally:
            budget.closed = True
            _current.reset(token)
    return wrapped
