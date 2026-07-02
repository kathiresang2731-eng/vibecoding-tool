from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

try:
  from ....agent_tools import ToolRuntimeContext
except ImportError:
  from agent_tools import ToolRuntimeContext


ToolExecutor = Callable[[str, ToolRuntimeContext, Any, dict[str, Any]], dict[str, Any]]
AgentProgressCallback = Callable[..., None]


@dataclass(slots=True)
class RuntimeActionContext:
  action: str
  state: dict[str, Any]
  decision: dict[str, Any]
  control_provider: Any
  artifact_provider: Any
  prepared_sections: dict[str, Any]
  tool_executor: ToolExecutor
  tool_context: ToolRuntimeContext
  user: Any
  project_id: str
  start_time: float
  timeout_seconds: int
  progress: AgentProgressCallback
  runtime_objects: dict[str, Any]

  @property
  def agent(self) -> str:
    return str(self.decision["next_agent"])
