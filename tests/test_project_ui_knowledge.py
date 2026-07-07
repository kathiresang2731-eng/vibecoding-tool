from __future__ import annotations

from backend.agents.agent_runtime.scoped_update.generation import (
  deterministic_navigation_interaction_fix_changes,
)
from backend.agents.agent_runtime.update_analysis import normalize_update_analysis
from backend.agents.memory.project_knowledge import (
  build_project_ui_knowledge_context,
  extract_project_ui_knowledge,
  persist_project_ui_knowledge,
  project_ui_matches_as_code_context,
  select_project_ui_knowledge,
)
from backend.agents.update_engine.scope_engine import (
  _normalize_flow_patch_existing_file_scope,
)


PROJECT_FILES = [
  {
    "path": "src/App.jsx",
    "content": (
      "import Analytics from './pages/Analytics.jsx';\n"
      "import Onboarding from './pages/Onboarding.jsx';\n"
      "export default function App() { return <Routes>"
      "<Route path=\"/analytics\" element={<Analytics />} />"
      "<Route path=\"/onboarding\" element={<Onboarding />} />"
      "</Routes>; }\n"
    ),
  },
  {
    "path": "src/pages/Analytics.jsx",
    "content": (
      "export default function Analytics() {\n"
      "  return <main><h1>Advanced Analytics Portal</h1>"
      "<button type=\"button\">Start Onboarding Walkthrough</button></main>;\n"
      "}\n"
    ),
  },
  {
    "path": "src/pages/Onboarding.jsx",
    "content": "export default function Onboarding() { return <main><h1>Onboarding</h1></main>; }\n",
  },
  {
    "path": "src/pages/Auth.jsx",
    "content": "export default function Auth() { return <main><h1>Sign in</h1></main>; }\n",
  },
  {
    "path": "src/pages/Dashboard.jsx",
    "content": "export default function Dashboard() { return <main><h1>Dashboard</h1></main>; }\n",
  },
]


class _MemoryStore:
  def __init__(self) -> None:
    self.rows: list[dict] = []

  def upsert_memory_item(self, user, **payload):
    row = {
      "id": "memory-1",
      **payload,
      "metadata_json": payload.get("metadata") or {},
    }
    self.rows = [row]
    return row

  def list_memory_items(self, user, **kwargs):
    return list(self.rows)


class _User:
  id = "user-1"


def test_project_ui_knowledge_maps_visible_text_to_owner_and_route() -> None:
  knowledge = extract_project_ui_knowledge(PROJECT_FILES)
  button = next(
    item
    for item in knowledge["elements"]
    if item["text"] == "Start Onboarding Walkthrough"
  )

  assert button["path"] == "src/pages/Analytics.jsx"
  assert button["component"] == "Analytics"
  assert button["route"] == "/analytics"
  assert button["element_kind"] == "button"
  assert button["purpose"] == "Rendered button content"


def test_project_ui_knowledge_persists_and_retrieves_exact_visible_text() -> None:
  store = _MemoryStore()
  persisted = persist_project_ui_knowledge(
    store,
    _User(),
    project_id="project-1",
    files=PROJECT_FILES,
    chat_session_id="session-1",
    chat_topic_id="topic-1",
  )
  matches = select_project_ui_knowledge(
    prompt=(
      "in Advanced Analytics Portal page Start Onboarding Walkthrough button "
      "not working to redirect to the onboarding page"
    ),
    files=PROJECT_FILES,
    store=store,
    user=_User(),
    project_id="project-1",
  )

  assert persisted["status"] == "stored"
  assert matches[0]["path"] == "src/pages/Analytics.jsx"
  assert matches[0]["text"] == "Start Onboarding Walkthrough"
  context = build_project_ui_knowledge_context(matches)
  assert "kind=button" in context
  assert "src/pages/Analytics.jsx" in context


def test_semantic_owner_precedes_broad_llm_candidates_for_interaction_contract() -> None:
  matches = select_project_ui_knowledge(
    prompt="Start Onboarding Walkthrough should redirect to onboarding",
    files=PROJECT_FILES,
    project_id="project-1",
  )
  code_context = project_ui_matches_as_code_context(matches)
  analysis = normalize_update_analysis(
    {
      "update_mode": "bug_fix",
      "request_kind": "bug_fix",
      "execution_strategy": "scoped_model_patch",
      "scope": "small",
      "summary": "Repair the walkthrough navigation.",
      "candidate_files": [
        "src/App.jsx",
        "src/pages/Onboarding.jsx",
        "src/pages/Dashboard.jsx",
        "src/pages/Auth.jsx",
      ],
      "interaction": {
        "component": "Start Onboarding Walkthrough button",
        "trigger": "click",
        "expected": "redirect to onboarding page",
        "source_page": "Advanced Analytics Portal",
        "target_page_or_route": "Onboarding",
        "confidence": 0.95,
      },
    },
    existing_paths=[item["path"] for item in PROJECT_FILES],
    code_search_matches=code_context,
    user_prompt="Start Onboarding Walkthrough should redirect to onboarding",
  )

  assert analysis["request_kind"] == "interaction_wiring_update"
  assert analysis["candidate_files"][0] == "src/pages/Analytics.jsx"
  assert analysis["target_files"][0] == "src/pages/Analytics.jsx"


def test_ui_knowledge_promotes_generic_bug_fix_to_interaction_owner() -> None:
  matches = select_project_ui_knowledge(
    prompt="on that page Start Onboarding Walkthrough button failed to redirect to the onboarding page",
    files=PROJECT_FILES,
    project_id="project-1",
  )
  code_context = project_ui_matches_as_code_context(matches)
  analysis = normalize_update_analysis(
    {
      "update_mode": "bug_fix",
      "request_kind": "bug_fix",
      "execution_strategy": "scoped_model_patch",
      "scope": "small",
      "summary": "Fix the broken redirect.",
      "candidate_files": [
        "src/pages/Onboarding.jsx",
        "src/pages/Dashboard.jsx",
        "src/App.jsx",
      ],
    },
    existing_paths=[item["path"] for item in PROJECT_FILES],
    code_search_matches=code_context,
    user_prompt="on that page Start Onboarding Walkthrough button failed to redirect to the onboarding page",
  )

  assert analysis["request_kind"] == "interaction_wiring_update"
  assert analysis["candidate_files"][0] == "src/pages/Analytics.jsx"
  assert analysis["interaction"]["component"].startswith("Start Onboarding Walkthrough")
  assert analysis["interaction"]["target_page_or_route"].lower() == "onboarding"
  assert analysis["project_ui_match_count"] >= 1
  assert analysis["matched_ui_elements"][0]["element_kind"] == "button"


def test_destination_page_mention_does_not_expand_into_auth_flow() -> None:
  analysis = {
    "update_mode": "bug_fix",
    "request_kind": "interaction_wiring_update",
    "candidate_files": ["src/pages/Analytics.jsx", "src/App.jsx", "src/pages/Onboarding.jsx"],
    "target_files": ["src/pages/Analytics.jsx"],
  }

  normalized = _normalize_flow_patch_existing_file_scope(
    analysis,
    prompt="Start Onboarding Walkthrough should redirect to onboarding",
    project_files=PROJECT_FILES,
  )

  assert normalized == analysis
  assert "src/pages/Auth.jsx" not in normalized["candidate_files"]
  assert "src/pages/Dashboard.jsx" not in normalized["candidate_files"]


def test_no_patch_recovery_wires_analytics_button_to_existing_onboarding_route() -> None:
  changes = deterministic_navigation_interaction_fix_changes(
    prompt="Start Onboarding Walkthrough should redirect to onboarding",
    update_analysis={
      "request_kind": "interaction_wiring_update",
      "enrichment_profile": "interaction_wiring",
      "candidate_files": [
        "src/pages/Analytics.jsx",
        "src/App.jsx",
        "src/pages/Onboarding.jsx",
      ],
      "interaction": {
        "component": "Start Onboarding Walkthrough button",
        "trigger": "click",
        "expected": "redirect to onboarding page",
        "source_page": "Advanced Analytics Portal",
        "target_page_or_route": "Onboarding",
        "confidence": 0.95,
      },
    },
    existing_files=PROJECT_FILES,
  )

  assert [item["path"] for item in changes] == ["src/pages/Analytics.jsx"]
  assert "useNavigate" in changes[0]["content"]
  assert "navigate('/onboarding')" in changes[0]["content"]
