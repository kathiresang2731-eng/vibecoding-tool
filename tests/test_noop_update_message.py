from backend.agents.agent_runtime.runtime_summary import build_runtime_summary
from backend.agents.orchestration.artifact_response import build_update_conversation_message


def test_generic_update_summary_with_no_files_reports_no_code_changes() -> None:
  message = build_update_conversation_message(
    artifact_response={
      "summary": "Parallel file workers completed.",
      "files": [],
    }
  )

  assert "no code changes were applied" in message.lower()
  assert "Updated the website preview" not in message


def test_empty_scoped_update_paths_report_no_code_changes() -> None:
  message = build_update_conversation_message(
    artifact_response={
      "summary": "Updated project files from your prompt.",
      "scoped_update": {
        "status": "applied",
        "changed_file_paths": [],
      },
    }
  )

  assert "no code changes were applied" in message.lower()
  assert "Updated the website preview" not in message


def test_empty_changed_paths_with_changed_files_does_not_report_no_code_changes() -> None:
  message = build_update_conversation_message(
    artifact_response={
      "summary": "Parallel file workers completed.",
      "changed_paths": [],
      "files": [{"path": "src/App.jsx", "content": "export default function App() { return null; }"}],
    }
  )

  assert "no code changes were applied" not in message.lower()
  assert message == "Updated the website preview from the provided prompt."


def test_generated_website_updated_file_does_not_report_no_code_changes() -> None:
  message = build_update_conversation_message(
    artifact_response={
      "summary": "Updated project files from your prompt.",
      "scoped_update": {
        "status": "applied",
        "changed_file_paths": [],
      },
    },
    generated_website={
      "files": [
        {
          "path": "src/App.jsx",
          "purpose": "Updated project file.",
          "code": "export default function App() { return null; }",
        }
      ]
    },
  )

  assert "no code changes were applied" not in message.lower()
  assert message == "Updated the website preview from the provided prompt."


def test_runtime_final_output_does_not_claim_update_when_changed_paths_are_empty() -> None:
  runtime = build_runtime_summary(
    {
      "agent_steps": [],
      "tool_calls": [],
      "messages": [],
      "operation": "update",
      "runtime_engine": "legacy",
      "changed_file_paths": [],
      "routing_result": {"intent": "website_update"},
    },
    {
      "title": "Synapse AI",
      "files": [],
    },
    validation_result=None,
    preview_result={"version": {"status": "ready", "preview_url": "/api/previews/p/v/"}},
  )

  assert runtime["final_output"]["message"] == "No code changes were applied for Synapse AI."
  assert runtime["final_output"]["changed_file_paths"] == []


def test_brand_rename_failure_defers_to_agent_summary_when_changes_exist() -> None:
  message = build_update_conversation_message(
    artifact_response={
      "summary": "Added handleAddToCart and cart state to the marketplace page.",
      "changed_paths": ["src/pages/Marketplace.jsx"],
      "update_validation": {
        "kind": "brand_rename",
        "applied": False,
        "expected": "AgriGrow Marketplace",
      },
    }
  )
  assert "handleAddToCart" in message
  assert "website name was not changed" not in message.lower()
