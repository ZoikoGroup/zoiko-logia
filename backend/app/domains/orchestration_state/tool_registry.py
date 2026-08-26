from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from pydantic import BaseModel


class AgentToolError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ToolContext:
    db: object
    run_id: str
    tenant_id: str
    user_id: str
    conversation_id: str | None
    goal: str


ToolHandler = Callable[[ToolContext, BaseModel], Awaitable[BaseModel]]


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: ToolHandler
    risk: str = "READ_ONLY"
    mutates_state: bool = False
    requires_approval: bool = False
    timeout_seconds: int = 30


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate agent tool: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> AgentTool:
        tool = self._tools.get(name)
        if tool is None:
            raise AgentToolError("UNKNOWN_TOOL", f"Unknown agent tool: {name}")
        return tool

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)
