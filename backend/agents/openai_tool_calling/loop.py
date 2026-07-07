from __future__ import annotations

import json
from typing import Any, Callable

from .client import OpenAIResponsesClient
from .errors import OpenAIToolCallingError
from .response import extract_function_calls, extract_output_text


def run_gpt_tool_calling_loop(
  *,
  client: OpenAIResponsesClient,
  messages: list[dict[str, Any]],
  tools: list[dict[str, Any]],
  execute_tool: Callable[[str, dict[str, Any]], dict[str, Any]],
  max_steps: int = 6,
) -> dict[str, Any]:
  if not messages:
    raise OpenAIToolCallingError("At least one message is required.")
  if max_steps < 1:
    raise OpenAIToolCallingError("max_steps must be at least 1.")

  response = client.create_response(input_items=messages, tools=tools)
  executed_tool_calls: list[dict[str, Any]] = []

  for step_index in range(max_steps):
    function_calls = extract_function_calls(response)
    if not function_calls:
      return {
        "status": "completed",
        "response": response,
        "output_text": extract_output_text(response),
        "tool_calls": executed_tool_calls,
      }

    function_outputs = []
    for function_call in function_calls:
      try:
        result = execute_tool(function_call.name, function_call.arguments)
        status = "completed"
        error = None
      except Exception as exc:
        result = {"error": str(exc)}
        status = "failed"
        error = str(exc)
      executed_tool_calls.append(
        {
          "call_id": function_call.call_id,
          "name": function_call.name,
          "arguments": function_call.arguments,
          "result": result,
          "status": status,
          "error": error,
        }
      )
      function_outputs.append(
        {
          "type": "function_call_output",
          "call_id": function_call.call_id,
          "output": json.dumps(result, ensure_ascii=False),
        }
      )

    if step_index == max_steps - 1:
      break

    response = client.create_response(
      input_items=function_outputs,
      tools=tools,
      previous_response_id=response.get("id"),
    )

  raise OpenAIToolCallingError(f"GPT tool-calling loop exceeded {max_steps} steps.")
