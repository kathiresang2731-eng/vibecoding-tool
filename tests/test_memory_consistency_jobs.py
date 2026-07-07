from backend.agents.memory.consistency_worker import process_due_consistency_jobs
from backend.agents.memory.consistency_service import run_consistency_cycle
from backend.agents.memory.session_monitor import persist_generation_memory_checkpoint
from backend.storage.bootstrap import BOOTSTRAP_STATEMENTS
from backend.storage.consistency_jobs import ConsistencyJobStoreMixin
from backend.storage.user import UserContext


class _RetryStore:
  def __init__(self, jobs):
    self.jobs = jobs
    self.processing: list[str] = []
    self.completed: list[str] = []
    self.failed: list[tuple[str, str, int]] = []
    self.memory_items: list[dict] = []
    self.recovered = 0
    self.users: dict[str, UserContext] = {}

  def list_due_consistency_jobs(self, *, limit, user_id=None):
    return [
      job
      for job in self.jobs
      if not user_id or not job.get("user_id") or job.get("user_id") == user_id
    ][:limit]

  def mark_consistency_job_processing(self, *, job_id):
    self.processing.append(job_id)
    return True

  def complete_consistency_job(self, *, job_id):
    self.completed.append(job_id)
    return True

  def fail_consistency_job(self, *, job_id, error, retry_seconds):
    self.failed.append((job_id, error, retry_seconds))
    return True

  def list_files(self, project_id, user):
    return [
      {
        "path": "src/App.jsx",
        "content": "export default function App(){return <button>Retry</button>}",
      }
    ]

  def upsert_memory_item(self, user, **payload):
    row = {"id": "memory-1", **payload}
    self.memory_items.append(row)
    return row

  def recover_stale_consistency_jobs(self, *, lock_timeout_seconds):
    self.recovered += 1
    return 1

  def get_user_by_id(self, user_id):
    return self.users.get(user_id)


def test_consistency_schema_is_additive_and_indexed() -> None:
  schema = "\n".join(BOOTSTRAP_STATEMENTS)
  assert "create table if not exists project_consistency_jobs" in schema
  assert "alter table memory_episodes add column if not exists vector_status" in schema
  assert "idx_consistency_jobs_pending" in schema
  assert "idx_memory_snapshots_run" in schema
  assert "create table if not exists memory_checkpoint_commits" in schema
  assert "idx_memory_snapshots_unique_run_kind" in schema
  assert "fk_memory_episodes_session_scope" in schema


def test_consistency_worker_completes_ui_knowledge_retry() -> None:
  user = UserContext(id="user-1", email="u@example.com", role="editor")
  store = _RetryStore(
    [
      {
        "id": "job-1",
        "project_id": "project-1",
        "user_id": user.id,
        "job_type": "project_ui_knowledge_refresh",
        "payload_json": {},
      }
    ]
  )

  result = process_due_consistency_jobs(store, user)

  assert result == {"seen": 1, "completed": 1, "failed": 0, "skipped": 0}
  assert store.completed == ["job-1"]
  assert store.memory_items


def test_consistency_worker_records_retryable_failure() -> None:
  user = UserContext(id="user-1", email="u@example.com", role="editor")
  store = _RetryStore(
    [
      {
        "id": "job-unsupported",
        "project_id": "project-1",
        "user_id": user.id,
        "job_type": "unknown",
        "attempt_count": 1,
        "payload_json": {},
      }
    ]
  )

  result = process_due_consistency_jobs(store, user)

  assert result["failed"] == 1
  assert store.failed[0][0] == "job-unsupported"
  assert store.failed[0][2] == 60


def test_background_cycle_recovers_locks_and_processes_users() -> None:
  user = UserContext(id="user-1", email="u@example.com", role="editor")
  store = _RetryStore(
    [
      {
        "id": "job-1",
        "project_id": "project-1",
        "user_id": user.id,
        "job_type": "project_ui_knowledge_refresh",
        "payload_json": {},
      }
    ]
  )
  store.users[user.id] = user

  result = run_consistency_cycle(store, batch_size=10, lock_timeout_seconds=60)

  assert result["recovered"] == 1
  assert result["users"] == 1
  assert result["completed"] == 1


def test_generation_checkpoint_is_idempotent_by_run_id() -> None:
  class _Store:
    def find_memory_session_snapshot_by_run_id(self, user, **kwargs):
      return {"id": "snapshot-existing"}

    def insert_memory_session_snapshot(self, *args, **kwargs):
      raise AssertionError("duplicate checkpoint must not write")

  result = persist_generation_memory_checkpoint(
    _Store(),
    UserContext(id="user-1", email="u@example.com", role="editor"),
    project_id="project-1",
    chat_session_id="session-1",
    generation_run_id="run-1",
    prompt="Update navbar",
    intent="website_update",
    outcome="completed",
    changed_paths=["src/App.jsx"],
  )

  assert result["status"] == "existing"
  assert result["snapshot_id"] == "snapshot-existing"


def test_generation_checkpoint_respects_concurrent_claim() -> None:
  class _Store:
    def find_memory_session_snapshot_by_run_id(self, user, **kwargs):
      return None

    def claim_memory_checkpoint(self, user, **kwargs):
      return False

    def get_memory_checkpoint_commit(self, *, generation_run_id):
      return {"status": "processing", "snapshot_id": None, "episode_id": None}

    def insert_memory_session_snapshot(self, *args, **kwargs):
      raise AssertionError("unclaimed checkpoint must not write")

  result = persist_generation_memory_checkpoint(
    _Store(),
    UserContext(id="user-1", email="u@example.com", role="editor"),
    project_id="project-1",
    chat_session_id="session-1",
    generation_run_id="run-1",
    prompt="Update navbar",
    intent="website_update",
    outcome="completed",
    changed_paths=["src/App.jsx"],
  )

  assert result["status"] == "processing"
  assert result["reason"] == "generation_run_checkpoint_already_claimed"


def test_memory_health_reports_unvalidated_scope_constraints() -> None:
  class Cursor:
    def __init__(self):
      self.calls = 0

    def __enter__(self):
      return self

    def __exit__(self, *_args):
      return False

    def execute(self, _query, _params=None):
      self.calls += 1

    def fetchall(self):
      if self.calls == 1:
        return [{"status": "completed", "count": 2}]
      if self.calls == 2:
        return [{"vector_status": "ready", "count": 3}]
      if self.calls == 4:
        return [{"status": "completed", "count": 1}]
      if self.calls == 14:
        return [
          {
            "table_name": "memory_episodes",
            "constraint_name": "fk_memory_episodes_session_scope",
          }
        ]
      return []

    def fetchone(self):
      if self.calls == 3:
        return {"age_seconds": 0, "stuck_processing": 0}
      if self.calls == 5:
        return {"count": 0}
      return {"count": 0}

  cursor = Cursor()

  class Connection:
    def __enter__(self):
      return self

    def __exit__(self, *_args):
      return False

    def cursor(self):
      return cursor

  class Store(ConsistencyJobStoreMixin):
    def connect(self):
      return Connection()

  health = Store().get_memory_health()

  assert health["unvalidated_constraints"] == [
    {
      "table": "memory_episodes",
      "constraint": "fk_memory_episodes_session_scope",
    }
  ]
  assert health["healthy"] is False


def test_validate_memory_scope_constraints_blocks_when_mismatches_exist() -> None:
  class Store(ConsistencyJobStoreMixin):
    def audit_memory_scope_mismatches(self):
      return {"episodes": 1, "total": 1}

    def list_unvalidated_memory_constraints(self):
      return [
        {
          "table": "memory_episodes",
          "constraint": "fk_memory_episodes_session_scope",
        }
      ]

  result = Store().validate_memory_scope_constraints(dry_run=False)

  assert result["status"] == "blocked"
  assert result["validated_constraints"] == []
  assert result["scope_mismatches"]["total"] == 1


def test_validate_memory_scope_constraints_dry_run_reports_ready() -> None:
  class Store(ConsistencyJobStoreMixin):
    def audit_memory_scope_mismatches(self):
      return {"total": 0}

    def list_unvalidated_memory_constraints(self):
      return [
        {
          "table": "memory_episodes",
          "constraint": "fk_memory_episodes_session_scope",
        }
      ]

  result = Store().validate_memory_scope_constraints()

  assert result["status"] == "ready"
  assert result["dry_run"] is True
  assert result["would_validate_constraints"] == [
    {
      "table": "memory_episodes",
      "constraint": "fk_memory_episodes_session_scope",
    }
  ]


def test_validate_memory_scope_constraints_executes_whitelisted_validation() -> None:
  executed: list[str] = []
  calls = {"list": 0}

  class Cursor:
    def __enter__(self):
      return self

    def __exit__(self, *_args):
      return False

    def execute(self, query, _params=None):
      executed.append(query)

  class Connection:
    def __enter__(self):
      return self

    def __exit__(self, *_args):
      return False

    def cursor(self):
      return Cursor()

  class Store(ConsistencyJobStoreMixin):
    def connect(self):
      return Connection()

    def audit_memory_scope_mismatches(self):
      return {"total": 0}

    def list_unvalidated_memory_constraints(self):
      calls["list"] += 1
      if calls["list"] == 1:
        return [
          {
            "table": "memory_episodes",
            "constraint": "fk_memory_episodes_session_scope",
          }
        ]
      return []

  result = Store().validate_memory_scope_constraints(dry_run=False)

  assert result["status"] == "validated"
  assert executed == ["alter table memory_episodes validate constraint fk_memory_episodes_session_scope"]
  assert result["validated_constraints"] == [
    {
      "table": "memory_episodes",
      "constraint": "fk_memory_episodes_session_scope",
    }
  ]
