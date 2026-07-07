from backend.agents.agent_runtime.scaffolding import ensure_vite_scaffold_files, is_valid_scaffold_file_content
from backend.agents.project_workspace import is_greenfield_generation, is_vite_scaffold_complete, needs_vite_scaffold_repair
from backend.agents.streaming.task_planner import plan_greenfield_parallel_tasks


def test_empty_placeholder_files_are_not_scaffold_complete() -> None:
  files = [
    {"path": "package.json", "content": ""},
    {"path": "index.html", "content": ""},
    {"path": "vite.config.js", "content": ""},
    {"path": "src/main.jsx", "content": ""},
    {"path": "src/App.jsx", "content": ""},
  ]
  assert not is_vite_scaffold_complete(files)
  assert needs_vite_scaffold_repair(files)
  assert is_greenfield_generation(intent="website_generation", files=files)


def test_standalone_code_does_not_request_vite_scaffold_repair() -> None:
  files = [{"path": "NeonNumber.java", "content": "public class NeonNumber {}"}]

  assert not is_vite_scaffold_complete(files)
  assert not needs_vite_scaffold_repair(files)
  assert not is_greenfield_generation(intent="website_generation", files=files)


def test_ensure_vite_scaffold_replaces_empty_runtime_files() -> None:
  files = [
    {"path": "package.json", "content": ""},
    {"path": "index.html", "content": ""},
    {"path": "src/components/Layout.jsx", "content": "export default function Layout() { return null; }"},
  ]
  scaffolded, touched = ensure_vite_scaffold_files(files, title="Campaign Site")
  by_path = {item["path"]: item["content"] for item in scaffolded}
  assert "package.json" in touched
  assert "index.html" in touched
  assert "vite.config.js" in touched
  assert is_valid_scaffold_file_content("package.json", by_path["package.json"])
  assert is_valid_scaffold_file_content("index.html", by_path["index.html"])
  assert "Campaign Site" in by_path["index.html"]
  assert by_path["src/components/Layout.jsx"].startswith("export default")


def test_greenfield_plan_uses_platform_scaffold_not_llm_scaffold_worker() -> None:
  plan = plan_greenfield_parallel_tasks("Build an AI native campaign management website")
  task_ids = [task["id"] for task in plan["tasks"]]
  assert "greenfield-scaffold" not in task_ids
  assert task_ids == [
    "greenfield-integration",
    "greenfield-pages-primary",
    "greenfield-features-secondary",
  ]


def test_placeholder_app_shell_is_replaced_when_pages_exist() -> None:
  files = [
    {
      "path": "src/App.jsx",
      "content": (
        'import React from "react";\n'
        "export default function App(){\n"
        "  return <main><h1>Your site is being generated</h1><p>Page modules will replace this shell.</p></main>;\n"
        "}\n"
      ),
    },
    {"path": "src/pages/Dashboard.jsx", "content": "export default function Dashboard(){ return <section>Dashboard</section>; }\n"},
    {"path": "src/pages/Auth.jsx", "content": "export default function Auth(){ return <section>Auth</section>; }\n"},
  ]

  scaffolded, touched = ensure_vite_scaffold_files(files, title="CRM")
  by_path = {item["path"]: item["content"] for item in scaffolded}

  assert "src/App.jsx" in touched
  assert 'import Dashboard from "./pages/Dashboard.jsx";' in by_path["src/App.jsx"]
  assert 'import Auth from "./pages/Auth.jsx";' in by_path["src/App.jsx"]
  assert "<BrowserRouter>" in by_path["src/App.jsx"]
  assert 'Navigate to="/dashboard"' in by_path["src/App.jsx"]
