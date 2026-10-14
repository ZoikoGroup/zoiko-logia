"""Shared helpers for the ZL-ENG-AGT-01 §14 QA pack (synthetic data only)."""
import json
from types import SimpleNamespace

from app.domains.model_gateway.agent import AgentLimits, run_agent
from app.domains.model_gateway.tool_registry import build_default_registry, decide

QUESTION = ("Compare FY2024 and FY2025 operating margins for Company A. FY2024: operating profit 120,000, "
            "revenue 1,000,000. FY2025: operating profit 150,000, revenue 1,200,000.")


def call(call_id, name, args):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def reply(content="", calls=None, tokens=300):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls))],
                           usage=SimpleNamespace(total_tokens=tokens))


class ScriptedModel:
    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.replies.pop(0)


def authorizer(registry, **overrides):
    facts = dict(role="Admin", active=True, same_tenant=True, role_unchanged=True, permissions=frozenset()) | overrides

    async def authorize(tool):
        return decide(registry.get(tool), tool, **facts)
    return authorize


async def run(replies, *, question=QUESTION, registry=None, authorize=True, limits=AgentLimits(), **facts):
    """Run the real agent loop and registry against a scripted model; returns
    (outcome, the audit records the loop produced, the model's requests)."""
    registry = registry or build_default_registry()
    model = ScriptedModel(replies)
    trace = []

    async def on_done(record):
        trace.append(record)

    outcome = await run_agent(
        model, model="scripted", system_prompt="", user_prompt=question, registry=registry,
        granted_permissions=frozenset(), limits=limits, on_tool_done=on_done,
        authorize=authorizer(registry, **facts) if authorize else None, request_id="req-qa",
    )
    return outcome, trace, model.requests
