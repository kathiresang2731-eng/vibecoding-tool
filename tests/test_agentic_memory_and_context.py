from backend.agents.agent_runtime.compaction import select_update_files_for_prompt
from backend.agents.agent_runtime.memory import build_project_state_memory
from backend.agents.agent_runtime.state import initial_runtime_state, refresh_conversation_requirement
from backend.agents.budget_config import AGENT_BUDGETS


def test_update_context_selector_uses_candidate_files_and_budget():
  large_unrelated = "const unrelated = true;\n" * 2000
  files = [
    {"path": "src/App.jsx", "content": "export default function App(){ return <Navbar/>; }\n"},
    {"path": "src/components/Navbar.jsx", "content": "export function Navbar(){ return <header>Old</header>; }\n"},
    {"path": "src/pages/Reports.jsx", "content": large_unrelated},
  ]

  selected, budget = select_update_files_for_prompt(
    files,
    prompt="fix navbar spacing",
    update_analysis={"update_mode": "bug_fix", "candidate_files": ["src/components/Navbar.jsx"]},
  )

  assert budget["max_files"] == AGENT_BUDGETS.targeted_update_files
  assert budget["selected_chars"] <= budget["max_chars"]
  assert selected[0]["path"] == "src/components/Navbar.jsx"
  assert all(item["path"] != "src/pages/Reports.jsx" or item["truncated"] for item in selected)


def test_conversation_requirement_trace_flows_into_project_state_memory():
  state = initial_runtime_state(
    project_id="project-1",
    prompt="fix mobile header overlap and remember this requirement",
    routing_result={"intent": "website_update", "reason": "Existing website update"},
  )
  refresh_conversation_requirement(
    state,
    update_analysis={
      "summary": "Fix mobile header overlap.",
      "update_mode": "bug_fix",
      "execution_strategy": "scoped_model_patch",
      "request_kind": "bug_fix",
      "candidate_files": ["src/components/Header.jsx"],
      "reason": "Header is the bounded target.",
    },
  )
  state.update(
    {
      "generated_website": {"title": "Demo"},
      "read_result": {"files": [{"path": "src/components/Header.jsx", "content": "old"}]},
      "candidate_files": [{"path": "src/components/Header.jsx", "content": "new"}],
      "changed_file_paths": ["src/components/Header.jsx"],
      "validation_result": {"status": "valid"},
      "visual_qa_result": {"status": "passed"},
      "committed": True,
    }
  )

  memory = build_project_state_memory(state, project_id="project-1")

  assert memory["requirement_trace"]["original_user_message"] == "fix mobile header overlap and remember this requirement"
  assert memory["selected_files"] == ["src/components/Header.jsx"]
  assert memory["validation_status"] == "valid"
  assert memory["visual_qa_status"] == "passed"
