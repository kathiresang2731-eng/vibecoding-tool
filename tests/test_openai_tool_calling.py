import pytest

from backend.llm.openai_tool_calling import (
  OpenAIToolCallingError,
  extract_function_calls,
  extract_output_text,
  run_gpt_tool_calling_loop,
)


class FakeOpenAIResponsesClient:
  def __init__(self, responses):
    self.responses = list(responses)
    self.requests = []

  def create_response(self, *, input_items, tools, previous_response_id=None):
    self.requests.append(
      {
        "input_items": input_items,
        "tools": tools,
        "previous_response_id": previous_response_id,
      }
    )
    if not self.responses:
      raise AssertionError("No fake response queued.")
    return self.responses.pop(0)


def test_extract_function_calls_parses_responses_api_function_calls():
  calls = extract_function_calls(
    {
      "output": [
        {
          "type": "function_call",
          "call_id": "call-1",
          "name": "READ_PROJECT_FILES",
          "arguments": "{\"project_id\":\"project-1\"}",
        }
      ]
    }
  )

  assert len(calls) == 1
  assert calls[0].call_id == "call-1"
  assert calls[0].name == "READ_PROJECT_FILES"
  assert calls[0].arguments == {"project_id": "project-1"}


def test_extract_output_text_reads_message_content():
  text = extract_output_text(
    {
      "output": [
        {
          "type": "message",
          "content": [
            {"type": "output_text", "text": "Done"},
            {"type": "output_text", "text": "."},
          ],
        }
      ]
    }
  )

  assert text == "Done."


def test_run_gpt_tool_calling_loop_executes_tool_and_returns_final_response():
  client = FakeOpenAIResponsesClient(
    [
      {
        "id": "response-1",
        "output": [
          {
            "type": "function_call",
            "call_id": "call-1",
            "name": "READ_PROJECT_FILES",
            "arguments": "{\"project_id\":\"project-1\"}",
          }
        ],
      },
      {
        "id": "response-2",
        "output": [
          {
            "type": "message",
            "content": [{"type": "output_text", "text": "Read 2 files."}],
          }
        ],
      },
    ]
  )

  def execute_tool(name, arguments):
    assert name == "READ_PROJECT_FILES"
    assert arguments == {"project_id": "project-1"}
    return {"file_count": 2}

  result = run_gpt_tool_calling_loop(
    client=client,
    messages=[{"role": "user", "content": "Read files"}],
    tools=[{"type": "function", "name": "READ_PROJECT_FILES", "parameters": {"type": "object"}}],
    execute_tool=execute_tool,
  )

  assert result["status"] == "completed"
  assert result["output_text"] == "Read 2 files."
  assert result["tool_calls"][0]["result"] == {"file_count": 2}
  assert client.requests[1]["previous_response_id"] == "response-1"
  assert client.requests[1]["input_items"][0]["type"] == "function_call_output"


def test_run_gpt_tool_calling_loop_fails_after_max_steps():
  client = FakeOpenAIResponsesClient(
    [
      {
        "id": "response-1",
        "output": [
          {
            "type": "function_call",
            "call_id": "call-1",
            "name": "READ_PROJECT_FILES",
            "arguments": "{}",
          }
        ],
      }
    ]
  )

  with pytest.raises(OpenAIToolCallingError, match="exceeded"):
    run_gpt_tool_calling_loop(
      client=client,
      messages=[{"role": "user", "content": "Read files"}],
      tools=[],
      execute_tool=lambda name, arguments: {"ok": True},
      max_steps=1,
    )
