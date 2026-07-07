from backend.agents.runtime_config import build_gate_rollback_on_failure
from backend.agents.streaming.commit_policy import (
  build_gate_failure_detail,
  build_gate_failure_user_message,
  should_rollback_after_build_gate,
)
from backend.agents.streaming.syntax_guard import find_syntax_issues_in_payload


def test_build_gate_rollback_disabled_by_default() -> None:
  assert build_gate_rollback_on_failure() is False


def test_should_not_rollback_when_policy_disabled() -> None:
  assert should_rollback_after_build_gate({"status": "failed"}) is False


def test_build_gate_failure_message_when_files_stay_committed() -> None:
  message = build_gate_failure_user_message(rolled_back=False)
  assert "saved locally" in message.lower()
  assert "no files were committed" not in message.lower()


def test_build_gate_failure_detail_marks_files_committed() -> None:
  detail = build_gate_failure_detail(build_gate_result={"status": "failed"}, rolled_back=False)
  assert detail["files_committed"] is True
  assert detail["rolled_back"] is False


def test_syntax_blocks_commit_payload() -> None:
  issues = find_syntax_issues_in_payload(
    [{"path": "src/App.jsx", "content": "export default function App() { return <div>;\n"}]
  )
  assert issues
