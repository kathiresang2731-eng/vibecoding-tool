from __future__ import annotations

from backend.agents.streaming.parallel_file_workers import (
  _build_worker_prompt,
  _clone_artifact_provider,
  _load_memory_context_block,
)
from backend.agents.streaming.shared_work_memory import SharedWorkMemory
from backend.agents.streaming.task_planner import (
  _resolve_wave_path_overlaps,
  plan_file_work,
)
from backend.storage import UserContext


class _PlannerLLMProvider:
  def __init__(self, payload):
    self.payload = payload
    self.calls = []

  def generate_json(self, prompt, **kwargs):
    self.calls.append({"prompt": prompt, **kwargs})
    return self.payload


def test_plan_greenfield_ccaas_infers_pages_and_parallel_waves() -> None:
  plan = plan_file_work(
    "Build AI CCaaS with auth onboarding dashboard copilot and channels",
    intent="website_generation",
    project_files=[],
  )
  assert plan["greenfield"] is True
  assert plan["use_parallel_workers"] is True
  assert plan["task_count"] == 3
  assert plan["wave_count"] == 1
  assert len(plan["waves"][0]) == 3
  page_paths = {
    path
    for task in plan["tasks"]
    for path in task.get("paths") or []
    if path.startswith("src/pages/")
  }
  assert "src/pages/Auth.jsx" in page_paths
  assert "src/pages/Onboarding.jsx" in page_paths
  assert "src/pages/Dashboard.jsx" in page_paths
  assert plan["parallel_waves"] >= 1
  app_shell = next(task for task in plan["tasks"] if task["id"] == "greenfield-integration")
  assert "src/App.jsx" in app_shell["paths"]
  assert plan["coordination_contract"]["website_type"] == "ccaas"
  assert plan["coordination_contract"]["worker_protocol"] == "worktual-three-worker-v1"


def test_greenfield_crm_plan_assigns_file_contracts_for_co_workers() -> None:
  plan = plan_file_work(
    "Build a CRM workspace with dashboard, leads, channels, settings and auth",
    intent="website_generation",
    project_files=[],
  )
  assert plan["website_type"] == "crm"
  paths = {path for task in plan["tasks"] for path in task.get("paths") or []}
  assert "src/pages/Leads.jsx" in paths
  assert "src/components/Sidebar.jsx" in paths
  contract = plan["coordination_contract"]
  assert contract["main_coding_agent"].startswith("The integration worker")
  task_contracts = {item["task_id"]: item for item in contract["task_contracts"]}
  assert len(task_contracts) == 3
  assert "src/App.jsx" in task_contracts["greenfield-integration"]["allowed_paths"]
  leads_owner = next(item for item in task_contracts.values() if "src/pages/Leads.jsx" in item["allowed_paths"])
  assert leads_owner["exports"]["src/pages/Leads.jsx"]["export_name"] == "Leads"


def test_rich_crm_generation_from_standalone_code_project_plans_full_app() -> None:
  prompt = """
  Generate the website for CRM with below requirement
  1) Auth
  2) After auth provide the onboarding process
  3) once onboarding done provide the dashboard with 4 types report and analytics
  4) modules: Leads & contact, deals, sales, project, product, main ai chat
  brandguidlines primary black secondary purple others white and grey shadow
  """
  plan = plan_file_work(
    prompt,
    intent="website_generation",
    project_files=[{"path": "NeonNumber.java", "content": "public class NeonNumber {}"}],
  )

  paths = {path for task in plan["tasks"] for path in task.get("paths") or []}

  assert plan["greenfield"] is True
  assert plan["website_type"] == "crm"
  assert plan["use_parallel_workers"] is True
  assert "src/pages/Auth.jsx" in paths
  assert "src/pages/Onboarding.jsx" in paths
  assert "src/pages/Dashboard.jsx" in paths
  assert "src/pages/Leads.jsx" in paths
  assert "src/pages/Deals.jsx" in paths
  assert "src/pages/Sales.jsx" in paths
  assert "src/pages/Projects.jsx" in paths
  assert "src/pages/Products.jsx" in paths
  assert "src/pages/AiChat.jsx" in paths
  assert "src/data/mockData.js" in paths
  assert "src/App.jsx" in paths


def test_crm_rebuild_request_with_partial_frontend_replans_full_app() -> None:
  files = [
    {"path": "package.json", "content": '{"dependencies":{"react":"^18.0.0","vite":"^5.0.0"}}'},
    {"path": "index.html", "content": "<div id='root'></div>"},
    {"path": "src/App.jsx", "content": "export default function App(){return <div>Dashboard</div>}"},
    {"path": "src/pages/Dashboard.jsx", "content": "export default function Dashboard(){return <main>Chart Placeholder</main>}"},
  ]
  prompt = (
    "The generated CRM website is a single static page and missing modules. "
    "Regenerate based on requirement: auth onboarding dashboard analytics leads contacts "
    "deals sales project product and main ai chat."
  )
  plan = plan_file_work(prompt, intent="website_generation", project_files=files)
  paths = {path for task in plan["tasks"] for path in task.get("paths") or []}

  assert plan["greenfield"] is True
  assert "src/pages/Onboarding.jsx" in paths
  assert "src/pages/Deals.jsx" in paths
  assert "src/pages/Products.jsx" in paths
  assert "src/pages/AiChat.jsx" in paths


def test_plan_file_work_splits_multiple_mentioned_files() -> None:
  files = [
    {"path": "src/pages/Home.jsx", "content": "export default function Home(){}"},
    {"path": "src/pages/About.jsx", "content": "export default function About(){}"},
    {"path": "src/components/Navbar.jsx", "content": "export default function Navbar(){}"},
  ]
  plan = plan_file_work(
    "Update Home.jsx hero and About.jsx copy",
    intent="website_update",
    project_files=files,
  )
  assert plan["use_parallel_workers"] is True
  assert plan["task_count"] >= 2
  assert plan["wave_count"] >= 1


def test_plan_file_work_single_file_sections_are_sequential() -> None:
  files = [{"path": "src/pages/Home.jsx", "content": "export default function Home(){}"}]
  plan = plan_file_work(
    "Update hero and footer in Home.jsx",
    intent="website_update",
    project_files=files,
  )
  assert plan["task_count"] >= 2
  hero_task = plan["tasks"][0]
  footer_task = plan["tasks"][1]
  assert footer_task["depends_on"] == [hero_task["id"]]
  assert plan["use_parallel_workers"] is False


def test_shared_work_memory_a2a_context() -> None:
  memory = SharedWorkMemory(project_id="p1", files={"src/App.jsx": "export default function App(){}"})
  memory.publish_completion(
    task_id="t1",
    agent_label="File Worker t1",
    paths=["src/App.jsx"],
    summary="Updated App shell",
  )
  context = memory.context_for_task(task_id="t2", depends_on=["t1"])
  assert "File Worker t1" in context
  assert "Updated App shell" in context


def test_shared_work_memory_staged_a2a() -> None:
  memory = SharedWorkMemory(project_id="p1", files={"src/pages/Leads.jsx": "export default function Leads(){}"})
  memory.publish_staged(
    task_id="file-src-pages-leads-jsx",
    agent_label="File Worker file-src-pages-leads-jsx",
    path="src/pages/Leads.jsx",
    note="staged nav update",
  )
  assert memory.messages[-1]["status"] == "in_progress"
  assert memory.messages[-1]["paths_changed"] == ["src/pages/Leads.jsx"]


def test_plan_single_file_does_not_force_parallel() -> None:
  files = [{"path": "src/pages/Home.jsx", "content": "export default function Home(){}"}]
  plan = plan_file_work("Change hero text on Home.jsx", intent="website_update", project_files=files)
  assert plan["use_parallel_workers"] is False


def test_plan_brand_rename_targets_title_files() -> None:
  files = [
    {"path": "index.html", "content": "<title>Old CRM</title>"},
    {"path": "package.json", "content": '{"name":"old-crm"}'},
    {"path": "src/components/Navbar.jsx", "content": "export default function Navbar(){ return <div>Old CRM</div>; }"},
    {"path": "src/pages/Dashboard.jsx", "content": "export default function Dashboard(){}"},
  ]
  plan = plan_file_work(
    "change the website name to worktual Ai CRM",
    intent="website_update",
    project_files=files,
  )
  planned_paths = {task["paths"][0] for task in plan["tasks"]}
  assert "index.html" in planned_paths
  assert "src/components/Navbar.jsx" in planned_paths
  assert plan["use_parallel_workers"] is True


def test_plan_data_update_uses_parallel_when_multiple_tasks() -> None:
  files = [
    {"path": "src/data/mockData.js", "content": "export const leads = [{ status: 'Open' }]"},
    {"path": "src/pages/Leads.jsx", "content": "negotiation pipeline leads list"},
    {"path": "src/pages/Dashboard.jsx", "content": "dashboard overview"},
    {"path": "src/components/Copilot.jsx", "content": "export default function Copilot(){}"},
  ]
  plan = plan_file_work(
    "add 4 new leads in negotiation status",
    intent="website_update",
    project_files=files,
  )
  planned_paths = {task["paths"][0] for task in plan["tasks"]}
  assert "src/data/mockData.js" in planned_paths
  assert plan["use_parallel_workers"] is True
  assert plan["task_count"] >= 2


def test_plan_scoped_module_update_single_file_stays_sequential() -> None:
  files = [
    {"path": "src/pages/Finance.jsx", "content": "export default function Finance(){ return <button>Terminate instance</button>; }"},
    {"path": "src/pages/Dashboard.jsx", "content": "export default function Dashboard(){}"},
    {"path": "src/App.jsx", "content": "import Finance from './pages/Finance';"},
  ]
  plan = plan_file_work(
    "Update Finance.jsx modal for Terminate instance button",
    intent="website_update",
    project_files=files,
  )
  assert plan["task_count"] >= 1
  assert plan["tasks"][0]["paths"] == ["src/pages/Finance.jsx"]
  assert plan["use_parallel_workers"] is False


def test_plan_content_match_finds_relevant_page() -> None:
  files = [
    {"path": "src/pages/Finance.jsx", "content": "Terminate instance button handler modal popup"},
    {"path": "src/pages/Dashboard.jsx", "content": "dashboard overview"},
  ]
  plan = plan_file_work(
    "provide the modal not as pop up for Terminate instance button",
    intent="website_update",
    project_files=files,
  )
  planned_paths = {task["paths"][0] for task in plan["tasks"]}
  assert "src/pages/Finance.jsx" in planned_paths
  assert plan["use_parallel_workers"] is False


def test_plan_leads_contact_module_parallel_wave() -> None:
  files = [
    {"path": "src/pages/Leads.jsx", "content": "export default function Leads(){ return <div>leads list call email sms history</div>; }"},
    {"path": "src/pages/Contacts.jsx", "content": "export default function Contacts(){ return <div>contacts module</div>; }"},
    {"path": "src/data/mockData.js", "content": "export const leads = []; export const callHistory = [];"},
    {"path": "src/App.jsx", "content": "import Leads from './pages/Leads'; import Contacts from './pages/Contacts'; routes nav"},
    {"path": "postcss.config.js", "content": "module.exports = { plugins: {} }"},
  ]
  prompt = (
    "in leads & contact module we want to provide the secondary nav bar and provide the "
    "detailed history for the call, email, sms as initial sub modules."
  )
  plan = plan_file_work(prompt, intent="website_update", project_files=files)
  planned_paths = {task["paths"][0] for task in plan["tasks"]}
  assert "src/pages/Leads.jsx" in planned_paths
  assert "src/pages/Contacts.jsx" in planned_paths
  assert "postcss.config.js" not in planned_paths
  assert plan["use_parallel_workers"] is True
  assert plan["task_count"] >= 2
  assert len(plan["waves"][0]) == plan["task_count"]


def test_plan_file_work_prefers_llm_file_plan_over_keyword_fallbacks() -> None:
  files = [
    {"path": "src/App.jsx", "content": "import Auth from './pages/Auth';"},
    {"path": "src/pages/Auth.jsx", "content": "export default function Auth(){}"},
    {"path": "src/pages/Onboarding.jsx", "content": "export default function Onboarding(){}"},
    {"path": "src/pages/Dashboard.jsx", "content": "export default function Dashboard(){}"},
    {"path": "src/index.css", "content": "body { color: black; }"},
  ]
  provider = _PlannerLLMProvider(
    {
      "tasks": [
        {
          "id": "entry-journey-repair",
          "kind": "file_group",
          "paths": ["src/App.jsx", "src/pages/Auth.jsx", "src/pages/Onboarding.jsx"],
          "scope": "Implement the requested entry journey before the workspace loads.",
          "depends_on": [],
        }
      ],
      "use_parallel_workers": False,
      "greenfield": False,
      "reason": "The request is about navigation/journey behavior, so route and entry pages must be grouped.",
    }
  )

  plan = plan_file_work(
    "make the entry experience follow the planned journey before the workspace opens",
    intent="website_update",
    project_files=files,
    artifact_provider=provider,
  )

  assert provider.calls
  assert plan["planning_source"] == "llm_file_work_planner"
  assert plan["task_count"] == 1
  assert plan["tasks"][0]["paths"] == ["src/App.jsx", "src/pages/Auth.jsx", "src/pages/Onboarding.jsx"]
  assert "src/index.css" not in plan["tasks"][0]["paths"]


def test_plan_file_work_rejects_invalid_llm_paths_and_falls_back_safely() -> None:
  files = [
    {"path": "src/pages/Home.jsx", "content": "export default function Home(){return <main/>}"},
  ]
  provider = _PlannerLLMProvider(
    {
      "tasks": [
        {
          "id": "unsafe",
          "kind": "file",
          "paths": ["../outside.jsx", "src/pages/Missing.jsx"],
          "scope": "Unsafe paths must not be accepted.",
        }
      ],
      "reason": "bad plan",
    }
  )

  plan = plan_file_work(
    "adjust the home experience",
    intent="website_update",
    project_files=files,
    artifact_provider=provider,
  )

  assert provider.calls
  assert plan["planning_source"] == "deterministic_file_planner"
  assert all("../" not in path for task in plan["tasks"] for path in task.get("paths") or [])


def test_resolve_wave_path_overlaps_splits_conflicting_tasks() -> None:
  tasks = {
    "task-a": {"id": "task-a", "paths": ["src/App.jsx"]},
    "task-b": {"id": "task-b", "paths": ["src/pages/Home.jsx"]},
    "task-c": {"id": "task-c", "paths": ["src/App.jsx"]},
  }
  waves = _resolve_wave_path_overlaps([["task-a", "task-b", "task-c"]], tasks)
  assert len(waves) >= 2
  for wave in waves:
    if len(wave) > 1:
      paths: set[str] = set()
      for task_id in wave:
        paths.update(tasks[task_id]["paths"])
      assert len(paths) == sum(len(tasks[tid]["paths"]) for tid in wave)


def test_build_worker_prompt_includes_memory_context_block() -> None:
  memory = SharedWorkMemory(project_id="p1", files={})
  prompt = _build_worker_prompt(
    user_prompt="Update navbar",
    task={"id": "t1", "kind": "file", "paths": ["src/components/Navbar.jsx"], "scope": "nav"},
    shared_memory=memory,
    memory_context_block="Chat session continuity memory:\n- Updates in this session: 2",
  )
  assert "Chat session continuity memory" in prompt
  assert "Parallel worker assignment" in prompt


def test_build_worker_prompt_includes_main_coding_agent_contract() -> None:
  memory = SharedWorkMemory(project_id="p1", files={"src/pages/Leads.jsx": ""})
  task = {
    "id": "greenfield-page-src-pages-leads-jsx",
    "kind": "greenfield_page",
    "paths": ["src/pages/Leads.jsx"],
    "scope": "Create leads page",
  }
  prompt = _build_worker_prompt(
    user_prompt="Build CRM",
    task=task,
    shared_memory=memory,
    coordination_contract={
      "website_type": "crm",
      "main_coding_agent": "Owns integration contract, route wiring, and final merge.",
      "communication_rules": ["Every co-worker writes only allowed_paths."],
      "task_contracts": [
        {
          "task_id": "greenfield-page-src-pages-leads-jsx",
          "kind": "greenfield_page",
          "allowed_paths": ["src/pages/Leads.jsx"],
          "depends_on": [],
          "export_name": "Leads",
          "export_type": "default",
          "import_path_from_app": "./pages/Leads",
          "acceptance": "Standalone page.",
        },
        {
          "task_id": "greenfield-app-shell",
          "kind": "greenfield_app_shell",
          "allowed_paths": ["src/App.jsx"],
          "depends_on": ["greenfield-page-src-pages-leads-jsx"],
          "export_name": "App",
          "export_type": "default",
          "import_path_from_app": "./App",
          "acceptance": "Import completed outputs only.",
        },
      ],
    },
  )
  assert "Main Coding Agent coordination contract" in prompt
  assert "Co-worker output map" in prompt
  assert "greenfield-app-shell" in prompt
  assert "Export: default Leads" in prompt


def test_clone_artifact_provider_returns_distinct_instances() -> None:
  class _FakeProvider:
    model = "gemini-test"

  first = _clone_artifact_provider(_FakeProvider())
  second = _clone_artifact_provider(_FakeProvider())
  assert first is not second


class _MemoryStoreStub:
  def get_memory_chat_session_state(self, user, *, chat_session_id):
    return {
      "update_count": 2,
      "rolling_summary": "Prior navbar update completed.",
    }

  def list_memory_items(self, user, *, project_id, namespace, kind, limit):
    return []

  def list_memory_episodes(self, user, *, project_id, chat_session_id, scope, limit):
    return []

  def list_memory_platform_patterns(self, **kwargs):
    return []


class _ToolContextStub:
  store = _MemoryStoreStub()


def test_load_memory_context_block_for_parallel_workers() -> None:
  user = UserContext(id="user-1", email="u@example.com", role="user")
  block = _load_memory_context_block(
    tool_context=_ToolContextStub(),
    user=user,
    project_id="project-1",
    prompt="update navbar spacing",
    chat_session_id="session-1",
    project_name="Demo",
    files=[{"path": "src/components/Navbar.jsx", "content": "export default function Navbar(){}"}],
    ideology_only=False,
  )
  assert "Chat session continuity memory" in block
  assert "Updates in this session: 2" in block
