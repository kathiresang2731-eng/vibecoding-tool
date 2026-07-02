from backend.llm.gemini_tool_calling import (
  extract_function_calls,
  openai_tool_to_gemini_function_declaration,
  run_gemini_tool_calling_loop,
)
from backend.llm.providers import ARTIFACT_PROVIDER_ROLE, CONTROL_PROVIDER_ROLE, GeminiProvider, assert_provider_role


def test_gemini_provider_is_control_and_artifact_provider():
  provider = GeminiProvider(client=FakeGeminiClient([]))

  assert_provider_role(provider, CONTROL_PROVIDER_ROLE)
  assert_provider_role(provider, ARTIFACT_PROVIDER_ROLE)


def test_openai_tool_schema_converts_to_gemini_function_declaration():
  declaration = openai_tool_to_gemini_function_declaration(
    {
      "type": "function",
      "name": "READ_PROJECT_FILES",
      "description": "Read files",
      "parameters": {
        "type": "object",
        "properties": {
          "project_id": {"type": "string", "description": "Project ID", "minimum": 1},
        },
        "required": ["project_id"],
        "additionalProperties": False,
      },
    }
  )

  assert declaration == {
    "name": "READ_PROJECT_FILES",
    "description": "Read files",
    "parameters": {
      "type": "object",
      "properties": {
        "project_id": {"type": "string", "description": "Project ID"},
      },
      "required": ["project_id"],
    },
  }


def test_gemini_tool_loop_executes_function_call_and_returns_final_text():
  client = FakeGeminiClient(
    [
      function_call_response("call-1", "READ_PROJECT_FILES", {"project_id": "project-1"}),
      text_response("Done."),
    ]
  )
  calls = []

  def execute_tool(name, arguments):
    calls.append({"name": name, "arguments": arguments})
    return {"file_count": 2}

  result = run_gemini_tool_calling_loop(
    client=client,
    messages=[{"role": "user", "content": "Read project files."}],
    tools=[tool_schema("READ_PROJECT_FILES")],
    execute_tool=execute_tool,
    max_steps=3,
  )

  assert result["status"] == "completed"
  assert result["output_text"] == "Done."
  assert calls == [{"name": "READ_PROJECT_FILES", "arguments": {"project_id": "project-1"}}]
  assert result["tool_calls"][0]["status"] == "completed"
  assert client.payloads[1]["contents"][-1]["parts"][0]["functionResponse"]["id"] == "call-1"


def test_gemini_tool_loop_records_failed_tool_call():
  client = FakeGeminiClient(
    [
      function_call_response("call-1", "BROKEN_TOOL", {}),
      text_response("Done."),
    ]
  )

  def execute_tool(name, arguments):
    raise RuntimeError("tool failed")

  result = run_gemini_tool_calling_loop(
    client=client,
    messages=[{"role": "user", "content": "Call a tool."}],
    tools=[tool_schema("BROKEN_TOOL")],
    execute_tool=execute_tool,
    max_steps=3,
  )

  assert result["tool_calls"][0]["status"] == "failed"
  assert result["tool_calls"][0]["error"] == "tool failed"


def test_gemini_tool_loop_compacts_completed_large_write_arguments(monkeypatch):
  monkeypatch.setenv("GEMINI_TOOL_LOOP_ARGUMENT_MAX_CHARS", "500")
  large_content = "export const value = '" + ("x" * 12_000) + "';"
  client = FakeGeminiClient(
    [
      function_call_response(
        "call-1",
        "WRITE_FILE",
        {"path": "src/data/generated.js", "content": large_content},
      ),
      text_response("Done."),
    ]
  )
  received = {}

  def execute_tool(name, arguments):
    received.update(arguments)
    return {"path": arguments["path"], "status": "staged", "size": len(arguments["content"])}

  run_gemini_tool_calling_loop(
    client=client,
    messages=[{"role": "user", "content": "Write the generated data file."}],
    tools=[tool_schema("WRITE_FILE")],
    execute_tool=execute_tool,
    max_steps=3,
  )

  assert received["content"] == large_content
  replayed_call = client.payloads[1]["contents"][-2]["parts"][0]["functionCall"]
  replayed_content = replayed_call["args"]["content"]
  assert len(replayed_content) < 1_000
  assert "chars omitted from completed tool call" in replayed_content


def test_gemini_tool_loop_compacts_old_tool_turns_after_context_budget(monkeypatch):
  monkeypatch.setenv("GEMINI_TOOL_LOOP_CONTEXT_MAX_CHARS", "16000")
  client = FakeGeminiClient(
    [
      function_call_response("call-1", "READ_FILE", {"path": "src/one.js"}),
      function_call_response("call-2", "READ_FILE", {"path": "src/two.js"}),
      text_response("Done."),
    ]
  )

  run_gemini_tool_calling_loop(
    client=client,
    messages=[{"role": "user", "content": "Read the relevant files."}],
    tools=[tool_schema("READ_FILE")],
    execute_tool=lambda name, arguments: {
      "path": arguments["path"],
      "content": "x" * 9_000,
      "size": 9_000,
    },
    max_steps=4,
  )

  third_request = client.payloads[2]["contents"]
  serialized = str(third_request)
  assert "Completed tool progress" in serialized
  retained_read_results = []
  for item in third_request:
    for part in item.get("parts") or []:
      response = part.get("functionResponse") if isinstance(part, dict) else None
      result = ((response or {}).get("response") or {}).get("result") if isinstance(response, dict) else None
      if isinstance(result, dict) and isinstance(result.get("content"), str):
        retained_read_results.append(result["content"])
  assert retained_read_results == ["x" * 9_000]


def test_extract_function_calls_accepts_rest_function_call_shape():
  calls = extract_function_calls(function_call_response("call-1", "READ_PROJECT_FILES", {"project_id": "p"}))

  assert calls[0].call_id == "call-1"
  assert calls[0].name == "READ_PROJECT_FILES"
  assert calls[0].arguments == {"project_id": "p"}


class FakeGeminiClient:
  model = "gemini-test"

  def __init__(self, responses):
    self.responses = list(responses)
    self.payloads = []

  def _post_generate_content(self, payload):
    self.payloads.append(payload)
    if not self.responses:
      return text_response("Done.")
    return self.responses.pop(0)


def tool_schema(name):
  return {
    "type": "function",
    "name": name,
    "description": f"Execute {name}.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
  }


def function_call_response(call_id, name, args):
  return {
    "candidates": [
      {
        "content": {
          "role": "model",
          "parts": [
            {
              "functionCall": {
                "id": call_id,
                "name": name,
                "args": args,
              }
            }
          ],
        }
      }
    ],
    "usageMetadata": {},
  }


def text_response(text):
  return {
    "candidates": [
      {
        "content": {
          "role": "model",
          "parts": [{"text": text}],
        }
      }
    ],
    "usageMetadata": {},
  }
