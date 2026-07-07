from __future__ import annotations

from backend.agents.streaming.file_agent import (
  _collect_error_repair_diagnosis,
  _format_error_diagnosis_block,
  build_project_context_block,
  derive_error_repair_scope_paths,
  is_error_repair_prompt,
  is_runtime_shim_path,
  select_system_instruction,
)
from backend.storage import UserContext


def test_is_runtime_shim_path_detects_worktual_shims() -> None:
  assert is_runtime_shim_path("src/worktual-recharts-shim.jsx")
  assert is_runtime_shim_path("src/worktual-router-shim.jsx")
  assert not is_runtime_shim_path("src/pages/Dashboard.jsx")


def test_is_error_repair_prompt_detects_fix_requests() -> None:
  assert is_error_repair_prompt("fix the build error in dashboard")
  assert is_error_repair_prompt("ReferenceError: levels is not defined")
  assert is_error_repair_prompt("fix this issue")
  assert is_error_repair_prompt(
    "When a user clicks Guest Trial there is no action is happening on the auth page"
  )
  assert not is_error_repair_prompt("add a pricing page with three tiers")


def test_streaming_file_agent_step_limit_allows_enough_update_steps(monkeypatch) -> None:
  from backend.agents.streaming.file_agent import streaming_file_agent_step_limit

  monkeypatch.delenv("STREAMING_FILE_AGENT_UPDATE_MAX_STEPS", raising=False)
  monkeypatch.delenv("STREAMING_FILE_AGENT_MAX_STEPS", raising=False)
  scoped_limit = streaming_file_agent_step_limit(
    intent="website_update",
    prompt="change the hero headline text",
  )
  repair_limit = streaming_file_agent_step_limit(
    intent="website_update",
    prompt="Guest Trial button has no action when clicked",
  )
  assert scoped_limit >= 6
  assert repair_limit >= scoped_limit


def test_streaming_file_agent_step_limit_clamps_undersized_theme_update_env(monkeypatch) -> None:
  from backend.agents.streaming.file_agent import streaming_file_agent_step_limit

  monkeypatch.setenv("ENABLE_UNIFIED_UPDATE_ENGINE", "true")
  monkeypatch.setenv("ENABLE_LEGACY_PARALLEL_UPDATES", "false")
  monkeypatch.setenv("STREAMING_FILE_AGENT_UPDATE_MAX_STEPS", "2")

  limit = streaming_file_agent_step_limit(
    intent="website_update",
    prompt="then change this page theme and color to red & black - Advanced Analytics Portal",
    request_kind="theme_color_update",
  )

  assert limit >= 8


def test_streaming_file_agent_step_limit_clamps_undersized_general_update_env(monkeypatch) -> None:
  from backend.agents.streaming.file_agent import streaming_file_agent_step_limit

  monkeypatch.setenv("ENABLE_UNIFIED_UPDATE_ENGINE", "true")
  monkeypatch.setenv("ENABLE_LEGACY_PARALLEL_UPDATES", "false")
  monkeypatch.setenv("STREAMING_FILE_AGENT_UPDATE_MAX_STEPS", "2")

  limit = streaming_file_agent_step_limit(
    intent="website_update",
    prompt="change the hero headline text",
  )

  assert limit >= 6


def test_select_system_instruction_uses_error_repair_mode() -> None:
  instruction = select_system_instruction(intent="website_update", prompt="fix vite build error")
  assert "DIRECT PROJECT UPDATE" in instruction
  assert "project memory" in instruction
  assert "worktual-*-shim" in instruction


def test_update_instruction_and_context_use_direct_project_update_language(monkeypatch) -> None:
  monkeypatch.setenv("ENABLE_UNIFIED_UPDATE_ENGINE", "true")
  instruction = select_system_instruction(intent="website_update", prompt="change dashboard headline")
  assert "DIRECT PROJECT UPDATE" in instruction
  assert "SCOPED UPDATE" not in instruction
  assert "priority starting points, not as a hard edit cage" in instruction

  class Store:
    def list_files(self, project_id, user):
      _ = project_id, user
      return [
        {"path": "src/App.jsx", "content": "export default function App(){ return null; }"},
        {"path": "src/pages/Dashboard.jsx", "content": "export default function Dashboard(){ return <h1>Old</h1>; }"},
        {"path": "src/pages/Reports.jsx", "content": "export default function Reports(){ return null; }"},
      ]

  class Context:
    store = Store()

  block = build_project_context_block(
    project_id="project-1",
    tool_context=Context(),
    user=UserContext(id="user-1", email="user@example.com", role="user"),
    prompt="change dashboard headline",
    intent="website_update",
    scoped_priority_paths=["src/pages/Dashboard.jsx"],
  )

  assert "Priority update files: src/pages/Dashboard.jsx" in block
  assert "not a hard scope" in block
  assert "Scoped update targets" not in block


def test_error_diagnosis_prioritizes_app_files_not_shims() -> None:
  files = [
    {"path": "src/worktual-recharts-shim.jsx", "content": "const levels = [];\nexport function RadarChart(){}"},
    {"path": "src/pages/Dashboard.jsx", "content": "import { RadarChart } from '../worktual-recharts-shim.jsx';\nconst levels = [];\n"},
    {"path": "src/App.jsx", "content": "export default function App(){ return null; }"},
  ]
  payload = _collect_error_repair_diagnosis(prompt="ReferenceError: levels is not defined in Dashboard", files=files)
  block = _format_error_diagnosis_block(payload)
  candidates = payload["diagnosis"].get("candidate_files") or []
  assert all(not is_runtime_shim_path(path) for path in candidates)
  assert "Candidate files" in block
  assert "worktual-recharts-shim" not in ", ".join(candidates)


def test_derive_error_repair_scope_paths_prefers_build_error_paths() -> None:
  files = [
    {
      "path": "src/App.jsx",
      "content": (
        'import { AiChat } from "./pages/AiChat";\n'
        'import Layout from "./components/Layout";\n'
        "export default function App(){ return <Layout><AiChat /></Layout>; }\n"
      ),
    },
    {"path": "src/pages/AiChat.jsx", "content": "export default function AiChat(){ return null; }\n"},
    {"path": "src/components/Layout.jsx", "content": "export function Layout({ children }){ return children; }\n"},
    {"path": "src/worktual-router-shim.jsx", "content": "export const RouterShim = null;\n"},
  ]
  build_log = (
    "Uncaught SyntaxError: The requested module '/src/pages/AiChat.jsx' does not provide an export named 'AiChat' "
    "(at App.jsx:11:10)\n"
    'src/App.jsx (16:9): "Layout" is not exported by "src/components/Layout.jsx", imported by "src/App.jsx".'
  )

  scoped = derive_error_repair_scope_paths(
    prompt="fix the import error",
    files=files,
    build_log=build_log,
  )

  assert set(scoped) == {"src/pages/AiChat.jsx", "src/App.jsx", "src/components/Layout.jsx"}


def test_derive_error_repair_scope_paths_falls_back_to_diagnosis() -> None:
  files = [
    {"path": "src/worktual-recharts-shim.jsx", "content": "export function RadarChart(){}\n"},
    {"path": "src/pages/Dashboard.jsx", "content": "const levels = undefined;\nexport default function Dashboard(){ return levels.name; }\n"},
    {"path": "src/App.jsx", "content": 'import Dashboard from "./pages/Dashboard";\nexport default function App(){ return <Dashboard />; }\n'},
  ]

  scoped = derive_error_repair_scope_paths(
    prompt="fix ReferenceError levels is not defined in Dashboard",
    files=files,
    build_log="",
  )

  assert "src/pages/Dashboard.jsx" in scoped
  assert all(not is_runtime_shim_path(path) for path in scoped)
