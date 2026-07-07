from backend.agents.chat_history import merge_update_prompt_with_chat_context
from backend.agents.streaming.file_agent import is_auth_flow_update_prompt, select_system_instruction
from backend.agents.streaming.task_planner import (
  _auth_onboarding_flow_paths,
  is_auth_onboarding_flow_repair_prompt,
  resolve_scoped_target_paths,
)
from backend.agents.update_engine.scope_engine import resolve_update_scope


def test_auth_flow_detects_login_then_onboarding_request() -> None:
  prompt = (
    "first user want to login in this website then only we want to redirect to the onboarding page "
    "so first provide the auth & onboarding process then landing to the dashbaord"
  )
  assert is_auth_onboarding_flow_repair_prompt(prompt)
  assert is_auth_flow_update_prompt(prompt)


def test_auth_flow_detects_follow_up_still_landing_on_home() -> None:
  prompt = "still it's directly landing in the home page"
  assert is_auth_onboarding_flow_repair_prompt(prompt)


def test_auth_flow_paths_include_app_and_auth_pages() -> None:
  prompt = "first login then onboarding then dashboard"
  paths = [
    "src/App.jsx",
    "src/pages/Home.jsx",
    "src/pages/Auth.jsx",
    "src/pages/Onboarding.jsx",
    "src/pages/Dashboard.jsx",
  ]
  files_map = {path: f"content for {path}" for path in paths}
  selected = _auth_onboarding_flow_paths(prompt, paths, files_map, max_paths=4)
  assert "src/App.jsx" in selected
  assert any("auth" in path.lower() for path in selected)


def test_resolve_scoped_targets_prefers_auth_flow_paths_legacy(monkeypatch) -> None:
  monkeypatch.setenv("ENABLE_LEGACY_PARALLEL_UPDATES", "true")
  prompt = "user must login before onboarding and dashboard"
  paths = ["src/App.jsx", "src/pages/Auth.jsx", "src/pages/Dashboard.jsx"]
  files_map = {path: "export default function X(){ return null; }" for path in paths}
  targets = resolve_scoped_target_paths(prompt, paths=paths, files_map=files_map)
  assert "src/App.jsx" in targets


def test_resolve_scoped_targets_unified_uses_code_search_not_auth_heuristic() -> None:
  prompt = "user must login before onboarding and dashboard"
  paths = ["src/App.jsx", "src/pages/Auth.jsx", "src/pages/Dashboard.jsx"]
  files_map = {
    "src/App.jsx": "import Auth from './pages/Auth'; export default function App() { return <Auth />; }",
    "src/pages/Auth.jsx": "export default function Auth() { return <div>Login</div>; }",
    "src/pages/Dashboard.jsx": "export default function Dashboard() { return <div>Dashboard</div>; }",
  }
  targets = resolve_scoped_target_paths(prompt, paths=paths, files_map=files_map)
  assert targets
  assert any(path.endswith(("Auth.jsx", "App.jsx", "Dashboard.jsx")) for path in targets)


def test_legacy_merge_update_prompt_includes_prior_user_turn(monkeypatch) -> None:
  monkeypatch.setenv("ENABLE_LEGACY_UPDATE_CHAT_CONTINUITY", "true")
  merged = merge_update_prompt_with_chat_context(
    "still it's directly landing in the home page",
    [
      {"role": "user", "content": "first login then onboarding then dashboard"},
      {"role": "model", "content": "I will update routing."},
    ],
  )
  assert "still it's directly landing" in merged
  assert "first login then onboarding" in merged


def test_auth_flow_system_instruction_mentions_app_routes_legacy(monkeypatch) -> None:
  monkeypatch.setenv("ENABLE_LEGACY_PARALLEL_UPDATES", "true")
  instruction = select_system_instruction(
    intent="website_update",
    prompt="first login then onboarding then dashboard",
  )
  assert "src/App.jsx" in instruction
  assert "auth" in instruction.lower()


def test_auth_flow_system_instruction_unified_is_generic() -> None:
  instruction = select_system_instruction(
    intent="website_update",
    prompt="first login then onboarding then dashboard",
  )
  assert "auth/login" not in instruction.lower()
  assert "DIRECT PROJECT UPDATE" in instruction
  assert "str_replace" in instruction


def test_unified_scope_keeps_auth_onboarding_dashboard_files_together() -> None:
  files = [
    {"path": "src/App.jsx", "content": "export default function App() { return null; }"},
    {"path": "src/pages/Auth.jsx", "content": "export default function Auth() { return null; }"},
    {"path": "src/pages/Onboarding.jsx", "content": "export default function Onboarding() { return null; }"},
    {"path": "src/pages/Dashboard.jsx", "content": "export default function Dashboard() { return null; }"},
    {"path": "src/pages/Home.jsx", "content": "export default function Home() { return null; }"},
  ]
  scope = resolve_update_scope(
    prompt="first user must sign in then onboarding then dashboard",
    project_files=files,
    control_provider=None,
  )
  assert scope.request_kind == "flow_patch"
  assert "src/App.jsx" in scope.candidate_files
  assert "src/pages/Auth.jsx" in scope.candidate_files
  assert "src/pages/Onboarding.jsx" in scope.candidate_files
  assert "src/pages/Dashboard.jsx" in scope.candidate_files
