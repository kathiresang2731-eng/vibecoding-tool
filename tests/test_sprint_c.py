from backend.agents.chat_history import apply_chat_context_budget
from backend.context.search import search_project_codebase
from backend.execution.gates import run_validation_gates
from backend.platform.repair_routing import failure_repair_route
from backend.skills.agents_md import build_project_agents_md_block


def test_run_validation_gates_passes_valid_artifact():
  summary = run_validation_gates(
    validation_result={"status": "valid", "file_count": 2, "paths": ["src/App.jsx"]},
    candidate_files=[{"path": "src/App.jsx", "content": "export default function App() { return null; }\n"}],
  )
  assert summary["status"] == "passed"
  assert summary["failed_count"] == 0


def test_run_validation_gates_fails_invalid_json():
  summary = run_validation_gates(
    validation_result={"status": "valid", "file_count": 1},
    candidate_files=[{"path": "package.json", "content": "{not-json"}],
  )
  assert summary["status"] == "failed"
  assert summary["failed_gate"]["gate"] == "syntax_lint"


def test_search_project_codebase_finds_line_match():
  files = [{"path": "src/App.jsx", "content": "export default function App() {\n  return <main>Farm</main>;\n}\n"}]
  result = search_project_codebase(files, query="Farm", limit=5)
  assert result["match_count"] == 1
  assert result["matches"][0]["path"] == "src/App.jsx"


def test_build_project_agents_md_block_bootstraps_when_missing():
  block, meta = build_project_agents_md_block([{"path": "src/App.jsx", "content": "x"}])
  assert meta["bootstrapped"] is True
  assert "patch-first" in block.lower()


def test_build_project_agents_md_block_uses_existing_file():
  block, meta = build_project_agents_md_block(
    [{"path": ".worktual/AGENTS.md", "content": "# Custom rules\nUse tabs.\n"}]
  )
  assert meta["bootstrapped"] is False
  assert "Custom rules" in block


def test_apply_chat_context_budget_compacts_large_history():
  messages = [
    {"role": "user", "content": "x" * 20000},
    {"role": "model", "content": "y" * 20000},
    {"role": "user", "content": "latest"},
    {"role": "model", "content": "ack"},
  ]
  compacted, meta = apply_chat_context_budget(messages, budget_chars=10000)
  assert meta["compacted"] is True
  assert len(compacted) <= len(messages)


def test_failure_repair_route_for_gate_failure():
  route = failure_repair_route(category="gate_failure", code="syntax_error", raw_error="gate failed")
  assert route["route_agent"] == "Repair Agent"
  assert route["retry_model"] is True
