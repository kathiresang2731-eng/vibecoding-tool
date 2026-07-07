from backend.agents.project_workspace import (
  is_greenfield_codebase,
  is_greenfield_generation,
  is_meaningful_project_source_path,
  is_standalone_code_project,
  is_vite_scaffold_complete,
  meaningful_project_source_files,
  needs_vite_scaffold_repair,
  standalone_code_source_files,
)
from backend.agents.streaming.task_planner import build_greenfield_streaming_prompt, plan_file_work


def test_meaningful_project_source_files_ignore_hidden_and_skills():
  files = [
    {"path": ".worktual/skills/foo/SKILL.md", "content": "skill"},
    {"path": "src/pages/Home.jsx", "content": "export default function Home(){}"},
  ]
  meaningful = meaningful_project_source_files(files)
  assert len(meaningful) == 1
  assert meaningful[0]["path"] == "src/pages/Home.jsx"
  assert is_greenfield_codebase(files) is False
  assert is_greenfield_codebase([files[0]]) is True


def test_greenfield_planner_uses_parallel_waves():
  plan = plan_file_work(
    "Build an AI CCaaS platform with pages, components, features, onboarding, and dashboard modules",
    intent="website_generation",
    project_files=[],
  )
  assert plan.get("greenfield") is True
  assert plan.get("planning_source") == "three_worker_greenfield_planner"
  assert plan.get("task_count") == 3
  assert plan.get("use_parallel_workers") is True
  assert plan.get("wave_count") == 1
  wave1 = plan["waves"][0]
  assert wave1 == [
    "greenfield-integration",
    "greenfield-pages-primary",
    "greenfield-features-secondary",
  ]
  task_ids = {task["id"] for task in plan["tasks"]}
  assert "greenfield-scaffold" not in task_ids
  assert "greenfield-integration" in task_ids


def test_greenfield_streaming_prompt_includes_blueprint_without_parallel_workers():
  prompt = build_greenfield_streaming_prompt(
    "Generate the website with below requirement\n"
    "1) Auth\n"
    "2) Onboarding\n"
    "3) Dashboard with analytics\n"
    "4) modules: leads, deals, sales"
  )
  assert "Greenfield build blueprint" in prompt
  assert "src/pages/Auth.jsx" in prompt
  assert "src/pages/Dashboard.jsx" in prompt
  assert "src/App.jsx" in prompt
  assert "consistent default exports" in prompt


def test_onboarding_flow_plans_parallel_sidebar_and_page():
  files = [
    {"path": "src/pages/Onboarding.jsx", "content": "export default function Onboarding(){ return <div>steps welcome</div>; }"},
    {"path": "src/components/Sidebar.jsx", "content": "export default function Sidebar(){ return <nav>onboarding modal skip button</nav>; }"},
    {"path": "src/App.jsx", "content": "import Sidebar from './components/Sidebar'; export default function App(){ return <Sidebar/>; }"},
  ]
  prompt = "add skip button to the main onboarding process and remove the new small modal onboarding process"
  plan = plan_file_work(prompt, intent="website_update", project_files=files)
  planned_paths = {task["paths"][0] for task in plan["tasks"]}
  assert "src/components/Sidebar.jsx" in planned_paths
  assert "src/pages/Onboarding.jsx" in planned_paths
  assert plan["use_parallel_workers"] is True
  assert plan["task_count"] >= 2


def test_onboarding_flow_scoped_targets_include_modal_host(monkeypatch):
  monkeypatch.setenv("ENABLE_LEGACY_PARALLEL_UPDATES", "true")
  monkeypatch.setenv("ENABLE_UNIFIED_UPDATE_ENGINE", "false")
  from backend.agents.streaming.task_planner import resolve_scoped_target_paths

  files = [
    {"path": "src/pages/Onboarding.jsx", "content": "export default function Onboarding(){ return <div>steps</div>; }"},
    {"path": "src/components/Sidebar.jsx", "content": "modal onboarding skip small popup"},
    {"path": "src/App.jsx", "content": "routes"},
  ]
  paths = [item["path"] for item in files]
  files_map = {item["path"]: item["content"] for item in files}
  prompt = "add skip button to onboarding and remove modal onboarding popup"
  scoped = resolve_scoped_target_paths(prompt, paths=paths, files_map=files_map)
  assert "src/components/Sidebar.jsx" in scoped
  assert "src/pages/Onboarding.jsx" in scoped


def test_existing_project_still_plans_folder_tasks_when_files_present():
  files = [{"path": "src/pages/Dashboard.jsx", "content": "export default function Dashboard(){}"}]
  plan = plan_file_work(
    "Update dashboard components and pages styling",
    intent="website_update",
    project_files=files,
  )
  assert plan.get("greenfield") is False
  assert plan.get("task_count", 0) >= 1


def test_is_greenfield_generation():
  assert is_greenfield_generation(intent="website_generation", files=[]) is True
  assert is_greenfield_generation(intent="website_update", files=[]) is False
  empty_scaffold = [
    {"path": "package.json", "content": ""},
    {"path": "index.html", "content": ""},
    {"path": "vite.config.js", "content": ""},
    {"path": "tailwind.config.js", "content": ""},
    {"path": "postcss.config.js", "content": ""},
    {"path": "src/main.jsx", "content": ""},
    {"path": "src/index.css", "content": ""},
    {"path": "src/App.jsx", "content": ""},
  ]
  assert is_greenfield_generation(intent="website_generation", files=empty_scaffold) is True
  assert is_meaningful_project_source_path("package.json") is True
  assert is_meaningful_project_source_path(".worktual/AGENTS.md") is False


def test_standalone_code_project_is_not_greenfield_website() -> None:
  files = [{"path": "NeonNumber.java", "content": "public class NeonNumber {}"}]

  assert standalone_code_source_files(files) == files
  assert is_standalone_code_project(files) is True
  assert is_greenfield_codebase(files) is False
  assert is_greenfield_generation(intent="website_generation", files=files) is False
  assert needs_vite_scaffold_repair(files) is False


def test_placeholder_app_shell_with_generated_pages_requires_repair() -> None:
  files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"},"dependencies":{"react":"latest","vite":"latest"}}'},
    {"path": "index.html", "content": '<div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "vite.config.js", "content": "export default {};\n"},
    {"path": "tailwind.config.js", "content": "module.exports = {};\n"},
    {"path": "postcss.config.js", "content": "module.exports = {};\n"},
    {"path": "src/main.jsx", "content": 'import { createRoot } from "react-dom/client";\ncreateRoot(document.getElementById("root")).render(null);\n'},
    {"path": "src/index.css", "content": "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n"},
    {
      "path": "src/App.jsx",
      "content": (
        'import React from "react";\n'
        "export default function App(){ return <main><h1>Your site is being generated</h1><p>Page modules will replace this shell.</p></main>; }\n"
      ),
    },
    {"path": "src/pages/Dashboard.jsx", "content": "export default function Dashboard(){ return <section>Dashboard</section>; }\n"},
  ]

  assert is_vite_scaffold_complete(files) is False
  assert needs_vite_scaffold_repair(files) is True
