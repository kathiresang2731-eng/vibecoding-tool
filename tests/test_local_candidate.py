from __future__ import annotations

from types import SimpleNamespace

from backend.agents.streaming.local_candidate import materialize_local_candidate, restore_local_candidate


class CandidateStore:
  def __init__(self, local_path: str) -> None:
    self.local_path = local_path

  def get_project(self, project_id, user):
    return {"id": project_id, "local_path": self.local_path}


def test_local_candidate_is_immediate_and_recoverable(tmp_path):
  root = tmp_path / "linked"
  source = root / "src" / "App.jsx"
  source.parent.mkdir(parents=True)
  source.write_text("export default function App(){return <p>working</p>}")
  context = SimpleNamespace(
    store=CandidateStore(str(root)),
    settings=SimpleNamespace(app_root=tmp_path, local_workspace_roots=[tmp_path]),
  )
  user = SimpleNamespace(id="user-1")

  candidate = materialize_local_candidate(
    tool_context=context,
    user=user,
    project_id="project-1",
    files=[{"path": "src/App.jsx", "content": "export default function App(){return <p>candidate</p>}"}],
  )

  assert candidate is not None
  assert "candidate" in source.read_text()
  assert restore_local_candidate(candidate) is True
  assert "working" in source.read_text()
