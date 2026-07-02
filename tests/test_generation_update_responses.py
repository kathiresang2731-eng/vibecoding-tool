from __future__ import annotations

from backend.agents.followup_routing import apply_existing_project_routing_bias
from backend.agents.orchestration.artifact_response import (
  build_generation_conversation_message,
  enrich_artifact_response_from_runtime,
)
from backend.agents.orchestration.routing import looks_like_website_generation_request
from backend.agents.streaming.update_clarification import check_streaming_update_clarification
from backend.agents.streaming.update_preflight import build_heuristic_update_analysis


EXISTING_PROJECT_FILES = [
  {"path": "package.json", "content": '{"dependencies":{"react":"latest","vite":"latest"}}'},
  {"path": "index.html", "content": "<!doctype html><html><body><div id='root'></div></body></html>"},
  {"path": "src/main.jsx", "content": 'import App from "./App.jsx";'},
  {"path": "src/App.jsx", "content": "export default function App(){ return <main>Existing site</main>; }"},
  {"path": "src/pages/Home.jsx", "content": "export default function Home(){ return <section>Home</section>; }"},
]


def test_generation_message_reports_missing_files_instead_of_static_success() -> None:
  message = build_generation_conversation_message(
    artifact_response={
      "summary": "Parallel file workers completed.",
      "files": [],
      "changed_paths": [],
    }
  )

  assert "no website files were generated" in message.lower()
  assert message != "Generated the website preview from the provided prompt."


def test_generation_message_uses_changed_paths_count() -> None:
  message = build_generation_conversation_message(
    artifact_response={
      "summary": "Parallel file workers completed.",
      "changed_paths": ["src/pages/Home.jsx", "src/App.jsx"],
      "files": [{"path": "src/pages/Home.jsx", "content": "export default function Home(){}"}],
    }
  )

  assert message == "Generated the website with 2 updated file(s)."


def test_generation_message_does_not_claim_missing_files_when_changed_paths_present() -> None:
  message = build_generation_conversation_message(
    artifact_response={
      "summary": "I have generated the complete working React project.",
      "files": [],
      "changed_paths": ["src/App.jsx", "src/pages/Home.jsx"],
    },
  )

  assert "no website files were generated" not in message.lower()
  assert "2 updated file" in message.lower()


def test_generation_message_uses_clarification_question() -> None:
  message = build_generation_conversation_message(
    artifact_response={
      "clarification_question": "Which dashboard widget should show the new chart?",
      "files": [],
    }
  )

  assert message == "Which dashboard widget should show the new chart?"


def test_enrich_artifact_response_copies_runtime_changed_paths() -> None:
  artifact = enrich_artifact_response_from_runtime(
    {
      "artifact_response": {"summary": "done", "files": []},
      "runtime": {"changed_paths": ["src/App.jsx"], "output_text": "done"},
    }
  )

  assert artifact["changed_paths"] == ["src/App.jsx"]
  assert artifact["runtime"]["changed_paths"] == ["src/App.jsx"]


def test_structured_update_requirement_skips_clarification() -> None:
  question = check_streaming_update_clarification(
    "Update the CRM with these requirements:\n1) Add deals page\n2) Add dark navbar\n3) Improve dashboard analytics",
    intent="website_update",
    project_files=EXISTING_PROJECT_FILES,
    scoped_targets=[],
  )

  assert question is None


def test_heuristic_update_preflight_uses_scoped_targets_when_no_direct_mentions() -> None:
  analysis = build_heuristic_update_analysis(
    "Improve the dashboard analytics cards and layout",
    EXISTING_PROJECT_FILES,
  )

  assert analysis["update_mode"] != "needs_clarification"
  assert analysis["candidate_files"]


def test_requirement_rebuild_stays_generation_on_existing_project() -> None:
  prompt = "Regenerate the complete CRM website based on my requirements with auth, onboarding, and dashboard modules"
  result = apply_existing_project_routing_bias(
    {
      "intent": "website_generation",
      "next_action": "generate_website",
      "next_tool": "analyze_prompt",
      "reason": "model",
    },
    prompt=prompt,
    project_files=EXISTING_PROJECT_FILES,
  )

  assert result["intent"] == "website_generation"


def test_structured_generation_prompt_matches_deterministic_route() -> None:
  prompt = """
  Generate the website for CRM with below requirement
  1) Auth
  2) onboarding
  3) dashboard with analytics
  4) modules: leads, deals, sales
  """
  assert looks_like_website_generation_request(prompt.strip().lower()) is True
