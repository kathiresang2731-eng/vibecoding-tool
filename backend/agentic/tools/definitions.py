from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

try:
  from ...config import Settings
  from ...storage import PostgresStore, UserContext
except ImportError:
  from config import Settings
  from storage import PostgresStore, UserContext

class ToolExecutionError(RuntimeError):
  pass


@dataclass(frozen=True)
class ToolRuntimeContext:
  store: PostgresStore
  settings: Settings


@dataclass(frozen=True)
class ToolDefinition:
  name: str
  description: str
  parameters: dict[str, Any]
  handler: Callable[[ToolRuntimeContext, UserContext, dict[str, Any]], dict[str, Any]]

  def openai_schema(self) -> dict[str, Any]:
    return {
      "type": "function",
      "name": self.name,
      "description": self.description,
      "parameters": self.parameters,
    }
