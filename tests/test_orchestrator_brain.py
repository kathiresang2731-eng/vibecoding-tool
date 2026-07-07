from __future__ import annotations

from backend.agents.orchestration.brain import build_orchestrator_brain


def test_orchestrator_brain_profiles_agentic_platform_knowledge() -> None:
  brain = build_orchestrator_brain(
    prompt="Explain this project",
    routing_result={"intent": "project_info"},
    adaptive_route={"route": "conversation"},
    project_files=[{"path": "src/App.jsx", "content": ""}],
  )

  knowledge = brain["agentic_platform_knowledge"]
  assert {"codex", "cursor", "claude"}.issubset(set(knowledge))
  assert "workspace-aware code edits" in knowledge["codex"]["strengths"]
  assert "current-file and multi-file context" in knowledge["cursor"]["strengths"]
  assert "large-context reasoning" in knowledge["claude"]["strengths"]
  assert brain["query_policy"]["query_class"] == "conversation"
  assert brain["execution_plan"]["primary_path"] == "conversation_response"
  assert brain["execution_plan"]["mutation_allowed"] is False
  assert "read_only_answering" in brain["selected_capabilities"]


def test_orchestrator_brain_selects_scoped_interaction_update_capabilities() -> None:
  brain = build_orchestrator_brain(
    prompt="Remove the create action plan popup and show it as a modal when the button is clicked",
    routing_result={
      "intent": "website_update",
      "target_resolution": {
        "resolved_page": "Deals",
        "resolved_route": "/deals",
        "resolved_files": ["src/pages/Deals.jsx"],
        "resolved_button": "Create Action Plan",
        "confidence": 0.91,
        "source": "current_prompt_button",
      },
    },
    adaptive_route={"route": "feature_update"},
    project_files=[
      {"path": "src/App.jsx", "content": ""},
      {"path": "src/pages/Deals.jsx", "content": ""},
    ],
  )

  assert brain["query_policy"]["query_class"] == "website_update"
  assert brain["execution_plan"]["primary_path"] == "local_first_direct_update"
  assert brain["execution_plan"]["model_use"] == "skip_for_safe_local_interaction_patch"
  assert brain["execution_plan"]["qa_policy"] == "save_first_post_update_qa_advisory"
  assert brain["target_resolution"]["resolved_files"] == ["src/pages/Deals.jsx"]
  assert brain["execution_plan"]["target_resolution"]["resolved_button"] == "Create Action Plan"
  assert "direct_project_update_planning" in brain["selected_capabilities"]
  assert "interaction_contract_reasoning" in brain["selected_capabilities"]
  assert "multi_agent_file_group_planning" in brain["selected_capabilities"]
  assert brain["project_context"]["sample_paths"] == ["src/App.jsx", "src/pages/Deals.jsx"]


def test_orchestrator_brain_selects_contextual_project_info_capabilities() -> None:
  brain = build_orchestrator_brain(
    prompt="what are the buttons are there in that page total count",
    routing_result={"intent": "project_info"},
    adaptive_route={"route": "conversation"},
    project_files=[{"path": "src/pages/Operations.jsx", "content": ""}],
  )

  assert "read_only_answering" in brain["selected_capabilities"]
  assert "project_context_inspection" in brain["selected_capabilities"]
  assert "context_reference_resolution" in brain["selected_capabilities"]
  assert "exact_ui_fact_counting" in brain["selected_capabilities"]
  assert brain["execution_plan"]["query_class"] == "answer_only"
