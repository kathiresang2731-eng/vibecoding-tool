from __future__ import annotations

import os

os.environ.setdefault("ENABLE_UNIFIED_UPDATE_ENGINE", "true")
os.environ.setdefault("ENABLE_CODE_INDEX", "true")

from backend.agents.update_engine.scope_engine import _apply_theme_color_scope, _minimal_code_search_fallback, resolve_update_scope


SAMPLE_FILES = [
  {
    "path": "src/components/Navbar.jsx",
    "content": "export function Navbar() { const [cart, setCart] = useState([]); return <button onClick={addToCart}>Cart</button>; }",
  },
  {
    "path": "src/pages/Marketplace.jsx",
    "content": "export default function Marketplace() { return <div>Products</div>; }",
  },
  {
    "path": "src/App.jsx",
    "content": "import { BrowserRouter } from 'react-router-dom'; export default function App() { return <BrowserRouter />; }",
  },
]


def test_minimal_code_search_fallback_finds_cart_files():
  result = _minimal_code_search_fallback("fix header cart button", SAMPLE_FILES, max_candidates=4)
  candidates = result.get("candidate_files") or []
  assert candidates
  assert any("Navbar" in path or "Marketplace" in path or "cart" in path.lower() for path in candidates)
  assert result.get("preflight_source") == "scope_engine_code_search_fallback"


def test_resolve_update_scope_without_provider_uses_fallback():
  scope = resolve_update_scope(
    prompt="fix header cart button",
    project_files=SAMPLE_FILES,
    control_provider=None,
    project_id="proj-1",
  )
  assert scope.candidate_files
  assert scope.preflight_source in {"legacy_fallback", "scope_engine_code_search_fallback"}


def test_resolve_update_scope_emits_progress_events():
  events: list[tuple[str, str]] = []

  def emit(step: str, message: str, **_kwargs):
    events.append((step, message))

  resolve_update_scope(
    prompt="wire add to cart on marketplace page",
    project_files=SAMPLE_FILES,
    control_provider=None,
    emit_progress=emit,
  )
  assert any(step == "scope.resolved" for step, _ in events)


def test_theme_color_scope_prefers_tokens_and_global_style_files():
  project_files = [
    {"path": "src/theme/tokens.js", "content": "export const TOKENS = {};"},
    {"path": "src/index.css", "content": "body { background: white; }"},
    {"path": "src/App.jsx", "content": "export default function App() { return null; }"},
    {
      "path": "src/pages/Dashboard.jsx",
      "content": "export default function Dashboard() { return <main className='bg-indigo-950 text-white'>Dashboard</main>; }",
    },
    {"path": "src/data/mockData.js", "content": "export const rows = [];"},
    {"path": "tailwind.config.js", "content": "export default {};"},
  ]
  analysis = {
    "request_kind": "theme_color_update",
    "summary": "Update theme to red and black",
    "candidate_files": ["src/data/mockData.js", "src/index.css", "tailwind.config.js"],
    "target_files": ["src/data/mockData.js", "src/index.css", "tailwind.config.js"],
  }

  scoped = _apply_theme_color_scope(analysis, project_files=project_files)

  assert scoped["execution_strategy"] == "scoped_model_patch"
  assert scoped["candidate_files"][0] in {"src/theme/tokens.js", "src/index.css"}
  assert "src/theme/tokens.js" in scoped["candidate_files"]
  assert "src/index.css" in scoped["candidate_files"]
  assert "tailwind.config.js" in scoped["candidate_files"]
  assert "src/App.jsx" not in scoped["candidate_files"]
  assert "src/pages/Dashboard.jsx" not in scoped["candidate_files"]
  assert "src/data/mockData.js" not in scoped["target_files"]
  task_paths = [path for task in scoped["scoped_update_tasks"] for path in task["candidate_files"]]
  assert task_paths == scoped["candidate_files"]
  assert all(len(task["candidate_files"]) <= 5 for task in scoped["scoped_update_tasks"])
  assert len(scoped["scoped_update_tasks"]) <= 3


def test_theme_color_scope_respects_agent_selected_page_without_prompt_keyword_routing():
  project_files = [
    {"path": "src/index.css", "content": "body { background: white; color: #111; }"},
    {
      "path": "src/pages/Deals.jsx",
      "content": "export default function Deals() { return <main className='bg-indigo-950 text-white'>Manage Your Deals & Opportunities</main>; }",
    },
    {
      "path": "src/pages/Dashboard.jsx",
      "content": "export default function Dashboard() { return <main className='bg-indigo-950 text-white'>Welcome Back Command Center</main>; }",
    },
    {
      "path": "src/pages/Reports.jsx",
      "content": "export default function Reports() { return <main className='bg-indigo-950 text-white'>Reports</main>; }",
    },
  ]
  analysis = {
    "request_kind": "theme_color_update",
    "summary": "Update the named page theme from the selected scope",
    "candidate_files": ["src/pages/Deals.jsx", "src/index.css"],
    "target_files": ["src/pages/Deals.jsx", "src/index.css"],
  }

  scoped = _apply_theme_color_scope(
    analysis,
    project_files=project_files,
    prompt="change the below page theme and color to red and black Manage Your Deals & Opportunities",
  )

  assert "src/index.css" in scoped["candidate_files"]
  assert "src/pages/Deals.jsx" in scoped["candidate_files"]
  assert "src/pages/Dashboard.jsx" not in scoped["target_files"]
  assert "src/pages/Reports.jsx" not in scoped["target_files"]
  task_paths = [path for task in scoped["scoped_update_tasks"] for path in task["candidate_files"]]
  assert task_paths == scoped["candidate_files"]


def test_theme_color_scope_does_not_infer_visual_intent_from_prompt_keywords():
  project_files = [
    {"path": "src/index.css", "content": "body { background: white; color: #111; }"},
    {
      "path": "src/pages/Deals.jsx",
      "content": "export default function Deals() { return <main>Manage Your Deals & Opportunities</main>; }",
    },
  ]
  analysis = {
    "request_kind": "other",
    "summary": "LLM did not classify this as a style update",
    "candidate_files": ["src/pages/Deals.jsx"],
    "target_files": ["src/pages/Deals.jsx"],
  }

  scoped = _apply_theme_color_scope(
    analysis,
    project_files=project_files,
    prompt="theme color red black entire website",
  )

  assert scoped == analysis


def test_flow_patch_existing_files_override_invented_candidate_new_files(monkeypatch):
  project_files = [
    {"path": "src/App.jsx", "content": "import Auth from './pages/Auth'; export default function App() { return <Auth />; }"},
    {"path": "src/pages/Auth.jsx", "content": "export default function Auth() { return <button>Sign in</button>; }"},
    {"path": "src/pages/Onboarding.jsx", "content": "export default function Onboarding() { return <button>Finish</button>; }"},
    {"path": "src/pages/Dashboard.jsx", "content": "export default function Dashboard() { return <main>Dashboard</main>; }"},
    {"path": "src/index.css", "content": "body { color: black; }"},
  ]

  def fake_llm_scope(**_kwargs):
    return {
      "update_mode": "feature_patch",
      "request_kind": "flow_patch",
      "summary": "Add auth and onboarding gate before dashboard.",
      "candidate_files": ["src/pages/Auth.jsx", "src/index.css"],
      "target_files": ["src/pages/Auth.jsx"],
      "reference_files": ["src/index.css"],
      "candidate_new_files": ["src/components/AuthAndOnboardingFlow.jsx"],
      "new_file_requirements": {
        "needed": True,
        "planned_files": [{"path": "src/components/AuthAndOnboardingFlow.jsx"}],
      },
    }

  monkeypatch.setattr("backend.agents.update_engine.scope_engine._run_llm_scope_analysis", fake_llm_scope)

  scope = resolve_update_scope(
    prompt=(
      "before reaching the dashboard user must do signin and after that onboarding "
      "then only dashboard, and theme is red and black"
    ),
    project_files=project_files,
    control_provider=object(),
  )

  assert scope.request_kind == "flow_patch"
  assert scope.candidate_new_files == []
  assert "src/App.jsx" in scope.candidate_files
  assert "src/pages/Auth.jsx" in scope.candidate_files
  assert "src/pages/Onboarding.jsx" in scope.candidate_files
  assert "src/pages/Dashboard.jsx" in scope.candidate_files
  analysis = scope.to_update_analysis()
  assert analysis["new_file_requirements"]["needed"] is False
  assert analysis["scoped_update_tasks"][0]["candidate_new_files"] == []


def test_interaction_scope_prefers_real_action_plan_anchor_over_llm_deals_guess(monkeypatch):
  project_files = [
    {
      "path": "src/App.jsx",
      "content": (
        "import Analytics from './pages/Analytics';\n"
        "import Deals from './pages/Deals';\n"
        "export default function App() { return <Routes><Route path='/analytics' element={<Analytics />} />"
        "<Route path='/deals' element={<Deals />} /></Routes>; }"
      ),
    },
    {
      "path": "src/pages/Analytics.jsx",
      "content": (
        "export default function Analytics() {\n"
        "  const createActionPlan = () => window.alert('Create action plan');\n"
        "  return <button onClick={createActionPlan}>Create Action Plan</button>;\n"
        "}\n"
      ),
    },
    {
      "path": "src/pages/Deals.jsx",
      "content": "export default function Deals() { return <main>Deals pipeline</main>; }\n",
    },
    {
      "path": "src/components/CopilotPanel.jsx",
      "content": "export default function CopilotPanel() { return <aside>Assistant</aside>; }\n",
    },
  ]

  def fake_llm_scope(**_kwargs):
    return {
      "update_mode": "feature_patch",
      "request_kind": "interaction_wiring_update",
      "summary": "Show Create Action Plan as a modal instead of popup.",
      "candidate_files": [
        "src/pages/Deals.jsx",
        "src/components/CopilotPanel.jsx",
        "src/pages/Analytics.jsx",
      ],
      "target_files": [
        "src/pages/Deals.jsx",
        "src/components/CopilotPanel.jsx",
        "src/pages/Analytics.jsx",
      ],
      "candidate_new_files": ["src/components/Deals.jsx"],
      "scope_rationale": "LLM guessed the deals section owns action plan behavior.",
    }

  def fake_code_matches(*_args, **_kwargs):
    return [
      {
        "path": "src/pages/Analytics.jsx",
        "matched_terms": ["create", "action", "plan", "button", "modal", "popup"],
        "snippets": [
          "const createActionPlan = () => window.alert('Create action plan'); "
          "return <button onClick={createActionPlan}>Create Action Plan</button>;"
        ],
      },
      {
        "path": "src/pages/Deals.jsx",
        "matched_terms": ["deals"],
        "snippets": ["export default function Deals() { return <main>Deals pipeline</main>; }"],
      },
    ]

  monkeypatch.setattr("backend.agents.update_engine.scope_engine._run_llm_scope_analysis", fake_llm_scope)
  monkeypatch.setattr("backend.agents.update_engine.scope_engine._build_code_matches", fake_code_matches)

  scope = resolve_update_scope(
    prompt=(
      "while click the create action plan button we want to provide as a modal "
      "not as popup messsage so update the code for that"
    ),
    project_files=project_files,
    control_provider=object(),
  )

  assert scope.request_kind == "interaction_wiring_update"
  assert scope.candidate_files[0] == "src/pages/Analytics.jsx"
  assert "src/pages/Analytics.jsx" in scope.target_files
  assert scope.candidate_new_files == []
  assert scope.raw_analysis["new_file_requirements"]["needed"] is False
  assert scope.scoped_update_tasks[0]["candidate_new_files"] == []
