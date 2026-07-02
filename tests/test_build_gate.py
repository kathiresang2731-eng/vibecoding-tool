from __future__ import annotations

from backend.agents.streaming.build_gate import (
  apply_deterministic_build_repair,
  build_repair_prompt,
  build_targeted_repair_prompt,
  normalize_files_before_build,
  parse_build_error_locations,
  parse_build_error_paths,
  post_update_build_gate_enabled,
)


def test_parse_build_error_paths_from_vite_log() -> None:
  log = (
    "vite v7.3.5 building client environment for production...\n"
    "src/pages/Leads.jsx:142:7: ERROR: Unexpected token\n"
    "src/App.jsx:12:5: ERROR: Expected '}' but found EOF"
  )
  paths = parse_build_error_paths(log)
  assert "src/pages/Leads.jsx" in paths
  assert "src/App.jsx" in paths


def test_parse_build_error_paths_from_browser_module_error() -> None:
  log = (
    "Uncaught SyntaxError: The requested module "
    "'/src/pages/AiChat.jsx' does not provide an export named 'AiChat' "
    "(at App.jsx:11:10)\n"
    'src/App.jsx (16:9): "Layout" is not exported by "src/components/Layout.jsx", '
    'imported by "src/App.jsx".'
  )

  paths = parse_build_error_paths(log)

  assert "src/pages/AiChat.jsx" in paths
  assert "src/App.jsx" in paths
  assert "src/components/Layout.jsx" in paths


def test_build_repair_prompt_includes_failure_markers() -> None:
  prompt = build_repair_prompt(
    original_prompt="Add secondary nav to leads module",
    build_log="src/pages/Leads.jsx:10:1: ERROR: Unexpected token",
    repair_reason="ERROR: Unexpected token",
  )
  assert "Build error" in prompt
  assert "Leads.jsx" in prompt
  assert "secondary nav" in prompt


def test_normalize_files_before_build_adds_vite_scaffold_when_missing() -> None:
  files = [{"path": "src/App.jsx", "content": "export default function App(){ return <div />; }"}]
  normalized, touched = normalize_files_before_build(files, title="Demo CRM")
  paths = {item["path"] for item in normalized}
  assert "index.html" in paths
  assert touched


def test_normalize_files_before_build_repairs_local_import_export_contracts() -> None:
  files = [
    {"path": "index.html", "content": '<div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "src/main.jsx", "content": 'import App from "./App";'},
    {
      "path": "src/App.jsx",
      "content": (
        'import { AiChat } from "./pages/AiChat";\n'
        'import Layout from "./components/Layout";\n'
        "export default function App(){ return <Layout><AiChat /></Layout>; }"
      ),
    },
    {"path": "src/pages/AiChat.jsx", "content": "export default function AiChat(){ return null; }"},
    {"path": "src/components/Layout.jsx", "content": "export function Layout({children}){ return children; }"},
  ]

  normalized, touched = normalize_files_before_build(files, title="Demo CRM")
  app = next(item for item in normalized if item["path"] == "src/App.jsx")

  assert 'import AiChat from "./pages/AiChat";' in app["content"]
  assert 'import { Layout } from "./components/Layout";' in app["content"]
  assert "src/App.jsx" in touched


def test_deterministic_repair_missing_index_html() -> None:
  files = [{"path": "src/App.jsx", "content": "export default function App(){ return <div />; }"}]
  reason = 'Could not resolve entry module "index.html"'
  repaired, paths, strategy = apply_deterministic_build_repair(files, reason, title="Demo")
  assert strategy == "vite_scaffold"
  assert "index.html" in {item["path"] for item in repaired}
  assert paths


def test_deterministic_repair_module_contracts() -> None:
  files = [
    {"path": "src/App.jsx", "content": 'import { AiChat } from "./pages/AiChat";\nexport default AiChat;'},
    {"path": "src/pages/AiChat.jsx", "content": "export default function AiChat(){ return null; }"},
  ]
  reason = "The requested module '/src/pages/AiChat.jsx' does not provide an export named 'AiChat'"

  repaired, paths, strategy = apply_deterministic_build_repair(files, reason, title="Demo")
  app = next(item for item in repaired if item["path"] == "src/App.jsx")

  assert strategy == "module_contracts"
  assert paths == ["src/App.jsx"]
  assert 'import AiChat from "./pages/AiChat";' in app["content"]


def test_post_update_build_gate_enabled_by_default() -> None:
  assert post_update_build_gate_enabled() is True


def test_parse_build_error_locations() -> None:
  log = "src/pages/Onboarding.jsx:142:7: ERROR: Unexpected token\n"
  locations = parse_build_error_locations(log)
  assert len(locations) == 1
  assert locations[0]["path"] == "src/pages/Onboarding.jsx"
  assert locations[0]["line"] == 142


def test_build_targeted_repair_prompt_includes_snippet() -> None:
  files_map = {
    "src/pages/Onboarding.jsx": "\n".join(f"line {index}" for index in range(1, 200)),
  }
  log = "src/pages/Onboarding.jsx:142:7: ERROR: Unexpected token"
  prompt, paths = build_targeted_repair_prompt(
    original_prompt="Fix onboarding",
    build_log=log,
    repair_reason="Unexpected token",
    files_map=files_map,
  )
  assert paths == ["src/pages/Onboarding.jsx"]
  assert "line 142" in prompt
  assert "Unexpected token" in prompt
