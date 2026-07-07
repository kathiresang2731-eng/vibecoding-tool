from __future__ import annotations

from types import SimpleNamespace

from backend.agents.orchestration.runner_parts.document_artifact import handle_document_artifact_branch


class FakeArtifactClient:
  def __init__(self) -> None:
    self.calls: list[dict] = []

  def generate_json(self, prompt: str, **kwargs):
    self.calls.append({"prompt": prompt, **kwargs})
    return {
      "generated_website": {
        "files": [
          {
            "path": "reports/apj-history.pdf",
            "purpose": "Detailed history report",
            "code": "# A.P.J. Abdul Kalam\n\nDetailed history report.\n",
          }
        ]
      },
      "implementation_notes": {
        "recommended_next_actions": ["Review README.md"],
        "self_checks": ["README markdown generated"],
      },
    }


class FakeOrchestrator:
  project_id = "project-1"
  tool_context = None
  user = None

  def __init__(self) -> None:
    self.progress: list[tuple] = []

  def _emit_progress(self, *args, **kwargs) -> None:
    self.progress.append((args, kwargs))


def test_document_artifact_branch_generates_valid_files() -> None:
  client = FakeArtifactClient()
  state = SimpleNamespace(
    user_prompt="Give me this detailed as pdf about APJ Abdul Kalam",
    routing_result={
      "intent": "document_artifact",
      "reason": "User requested a PDF document.",
    },
    adaptive_route={},
    artifact_client=client,
    raw_llm_response=None,
    response=None,
    intent="document_artifact",
    prepared_sections={
      "multi_agent_system": {},
      "gemini_tool_calling_setup": {"tools": [{"name": "route_generation_action"}]},
      "google_adk_usage": {"adk_agents": [{"name": "document_artifact_agent"}]},
    },
  )

  result = handle_document_artifact_branch(FakeOrchestrator(), state)

  generated = result["generated_website"]
  assert generated["files"][0]["path"] == "reports/apj-history.pdf"
  assert generated["files"][0]["code"].startswith("data:application/pdf;base64,")
  assert state.response["multi_agent_system"]["intent"] == "document_artifact"
  assert state.response["multi_agent_system"]["active_agent"] == "Document Artifact Agent"
  assert client.calls[0]["trace_label"] == "generate_document_artifact"
