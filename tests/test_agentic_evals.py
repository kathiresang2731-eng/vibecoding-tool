from __future__ import annotations

from backend import main as backend_main
from backend.llm.agentic_evals import evaluate_agentic_response, evaluate_failure_payload
from backend.llm.generator import generate_website
from backend.llm.providers import ARTIFACT_PROVIDER_ROLE, CONTROL_PROVIDER_ROLE


class EvalProvider:
  def __init__(self, *, name: str, provider_role: str, route=None, conversation=None, artifact=None):
    self.name = name
    self.provider_role = provider_role
    self.route = route or {}
    self.conversation = conversation or {}
    self.artifact = artifact or {}
    self.trace_labels: list[str | None] = []

  def generate_json(self, prompt, **kwargs):
    trace_label = kwargs.get("trace_label")
    self.trace_labels.append(trace_label)
    if trace_label == "route_generation_action":
      return self.route
    if trace_label in {"handle_greeting", "request_website_details"}:
      return self.conversation
    return self.artifact


def test_agentic_eval_scores_golden_generation_response_at_100():
  response = golden_agentic_response("website_generation")

  result = evaluate_agentic_response(response)

  assert result["passed"] is True
  assert result["percentage"] == 100
  assert result["score"] == result["max_score"]
  assert result["missing"] == []


def test_agentic_eval_scores_golden_update_response_at_100():
  response = golden_agentic_response("website_update")

  result = evaluate_agentic_response(response)

  assert result["passed"] is True
  assert result["percentage"] == 100
  assert result["missing"] == []


def test_agentic_eval_scores_real_conversation_response_without_artifact_generation():
  control = EvalProvider(
    name="local-gpt",
    provider_role=CONTROL_PROVIDER_ROLE,
    route={
      "intent": "greeting",
      "next_action": "respond_and_collect_website_brief",
      "next_tool": "handle_greeting",
      "reason": "Greeting only.",
    },
    conversation={
      "type": "greeting",
      "message": "Hi. Tell me what website you want to build.",
      "next_prompt_guidance": ["Share website type", "Share brand name"],
    },
  )
  artifact = EvalProvider(name="gemini", provider_role=ARTIFACT_PROVIDER_ROLE, artifact={})

  response = generate_website("hi", control_provider=control, artifact_provider=artifact)
  result = evaluate_agentic_response(response)

  assert result["passed"] is True
  assert result["percentage"] == 100
  assert response["gemini_tool_calling_setup"]["provider"] == "gemini-native-control-artifact"
  assert response["gemini_tool_calling_setup"]["artifact_provider"] == "not-used"
  assert control.trace_labels == ["route_generation_action", "handle_greeting"]
  assert artifact.trace_labels == []


def test_agentic_eval_reports_missing_proof_for_broken_generation_response():
  response = golden_agentic_response("website_generation")
  response["multi_agent_system"]["agentic_runtime"]["visual_qa"] = {"status": "skipped"}
  response["multi_agent_system"]["agentic_runtime"]["completion_status"]["visual_qa_passed"] = False
  response["agent_to_agent_communication"]["a2a_runtime"]["messages"] = []
  response["agent_to_agent_communication"]["agentic_handoffs"] = []

  result = evaluate_agentic_response(response)

  assert result["passed"] is False
  assert result["percentage"] < 100
  assert "agentic_runtime.completion_status.visual_qa_passed" in result["missing"]
  assert "agent_to_agent_communication.a2a_runtime.messages" in result["missing"]


def test_failure_payload_eval_scores_structured_generation_error_at_100():
  payload = backend_main.generation_failure_payload(RuntimeError("Preview visual QA did not pass: No browser command found."))

  result = evaluate_failure_payload(payload)

  assert result["passed"] is True
  assert result["percentage"] == 100
  assert result["missing"] == []


def golden_agentic_response(intent: str) -> dict:
  runtime = golden_runtime(intent)
  return {
    "multi_agent_system": {
      "intent": intent,
      "active_agent": "Memory Agent",
      "agentic_runtime": runtime,
    },
    "gemini_tool_calling_setup": {
      "provider": "gemini-native-control-artifact",
      "control_provider": "gemini",
      "artifact_provider": "gemini",
      "tool_call_sequence": ["route_generation_action", *[call["name"] for call in runtime["tool_calls"]]],
    },
    "orchestration_flow": {
      "generated_website": {
        "title": "Golden Site",
        "files": [
          {"path": "src/App.jsx", "purpose": "App", "code": "export default function App() { return <main />; }"},
          {"path": "src/styles.css", "purpose": "Styles", "code": "body { margin: 0; }"},
        ],
      }
    },
    "agent_to_agent_communication": {
      "agentic_handoffs": [canonical_handoff()],
      "a2a_runtime": {
        "protocol": "worktual-a2a-v1",
        "messages": [canonical_handoff()],
        "acknowledgements": [{"message_id": "a2a-1", "status": "accepted"}],
        "validation": {"status": "valid"},
      },
    },
  }


def golden_runtime(intent: str) -> dict:
  is_update = intent == "website_update"
  changed_file_paths = ["src/App.jsx"] if is_update else []
  return {
    "runtime": "worktual-real-agent-runtime-loop",
    "status": "completed",
    "branch": intent,
    "operation": "update" if is_update else "generate",
    "tool_source_of_truth": True,
    "completion_status": {
      "files_exist": True,
      "artifact_valid": True,
      "staged_preview_ready": True,
      "visual_qa_passed": True,
      "files_committed": True,
      "memory_prepared": True,
    },
    "completion_proof": {
      "satisfied": True,
      "requirements": {
        "files_exist": True,
        "artifact_valid": True,
        "staged_preview_ready": True,
        "visual_qa_passed": True,
        "files_committed": True,
        "memory_prepared": True,
      },
      "rejections": [],
    },
    "tool_calls": [{"name": name, "status": "completed"} for name in REQUIRED_TOOL_CALLS_FOR_TEST],
    "supervisor_audit_trail": [
      {
        "audit_id": "audit-1",
        "action": "DONE",
        "next_agent": "Supervisor Agent",
        "completion_proof_before": True,
      }
    ],
    "visual_qa": {"status": "passed", "warnings": []},
    "memory": {"memory_kind": "generation_summary", "content": "Generated Golden Site."},
    "persisted_memory_events": [{"key": "latest_generation_summary", "kind": "generation_summary"}],
    "handoffs": [canonical_handoff()],
    "final_output": {
      "intent": intent,
      "message": "Updated and built Golden Site." if is_update else "Generated and built Golden Site.",
      "file_count": 2,
      "changed_file_paths": changed_file_paths,
      "completion_proof_satisfied": True,
      "preview_status": "ready",
    },
  }


def canonical_handoff() -> dict:
  return {
    "message_id": "a2a-1",
    "sender": "Intent Router Agent",
    "receiver": "Prompt Analyst Agent",
    "task": "Run extract_website_brief after route_user_turn.",
    "input": {"prompt": "Build a website"},
    "output": {"intent": "website_generation"},
    "confidence": 0.92,
    "next_action": "extract_website_brief",
  }


REQUIRED_TOOL_CALLS_FOR_TEST = (
  "READ_PROJECT_FILES",
  "LOAD_PROJECT_MEMORY",
  "VALIDATE_PROJECT_ARTIFACT",
  "BUILD_STAGED_PROJECT_PREVIEW",
  "RUN_PREVIEW_VISUAL_QA",
  "WRITE_PROJECT_FILES",
  "PERSIST_PROJECT_MEMORY",
)
