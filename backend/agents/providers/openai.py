from __future__ import annotations

from typing import Any

from ..openai_tool_calling import OpenAIResponsesClient, run_gpt_tool_calling_loop
from .constants import CONTROL_PROVIDER_ROLE


class OpenAIToolCallingProvider:
  name = "openai"
  provider_role = CONTROL_PROVIDER_ROLE

  def __init__(self, client: OpenAIResponsesClient | None = None) -> None:
    self.client = client or OpenAIResponsesClient.from_env()

  def run_tool_loop(
    self,
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    execute_tool,
    max_steps: int = 6,
  ) -> dict[str, Any]:
    return run_gpt_tool_calling_loop(
      client=self.client,
      messages=messages,
      tools=tools,
      execute_tool=execute_tool,
      max_steps=max_steps,
    )
