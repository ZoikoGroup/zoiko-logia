"""Compatibility exports for the governed agent tool registry.

The registry lives with durable orchestration state because tools are executed
by the application runner, never directly by a provider adapter. Keeping these
exports here preserves the Model Gateway's documented discovery point.
"""

from app.domains.orchestration_state.agent_tools import build_agent_tool_registry
from app.domains.orchestration_state.tool_registry import (
    AgentTool,
    AgentToolError,
    ToolContext,
    ToolRegistry,
)

__all__ = [
    "AgentTool",
    "AgentToolError",
    "ToolContext",
    "ToolRegistry",
    "build_agent_tool_registry",
]
