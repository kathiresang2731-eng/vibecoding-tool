from __future__ import annotations

from backend.agents.streaming.file_agent import (
  _collect_error_repair_diagnosis,
  _format_error_diagnosis_block,
  derive_error_repair_scope_paths,
  is_error_repair_prompt,
  is_runtime_shim_path,
  select_system_instruction,
)


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


def test_streaming_file_agent_step_limit_allows_enough_update_steps() -> None:
  from backend.agents.streaming.file_agent import streaming_file_agent_step_limit

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


def test_select_system_instruction_uses_error_repair_mode() -> None:
  instruction = select_system_instruction(intent="website_update", prompt="fix vite build error")
  assert "Do NOT list or read every page file" in instruction
  assert "worktual-*-shim" in instruction


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
