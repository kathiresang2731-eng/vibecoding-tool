from __future__ import annotations

from backend.storage import UserContext


class _HealthyMemoryStore:
  def get_memory_health(self):
    return {
      "healthy": True,
      "consistency_jobs": {},
      "episode_vectors": {},
      "checkpoint_commits": {},
      "scope_mismatches": {"total": 0},
      "unvalidated_constraints": [],
    }

  def validate_memory_scope_constraints(self, *, dry_run=True):
    return {
      "status": "ready" if dry_run else "validated",
      "dry_run": dry_run,
      "scope_mismatches": {"total": 0},
      "unvalidated_constraints": [],
      "validated_constraints": [],
    }


class _Settings:
  memory_consistency_worker_enabled = True


class _Context:
  store = _HealthyMemoryStore()
  settings = _Settings()


def test_memory_health_fails_in_production_without_durable_vectors(monkeypatch) -> None:
  from backend import main as backend_main

  monkeypatch.setattr(backend_main, "get_context", lambda: _Context())
  monkeypatch.setenv("WORKTUAL_ENV", "production")
  monkeypatch.setenv("WORKTUAL_QDRANT_URL", "")
  monkeypatch.setenv("ENABLE_EPISODIC_VECTOR_SEARCH", "true")
  monkeypatch.setenv("ENABLE_EPISODIC_VECTOR_MEMORY_FALLBACK", "false")

  payload = backend_main.memory_health(UserContext(id="admin", email="a@example.com", role="admin"))

  assert payload["ok"] is False
  assert payload["memory"]["healthy"] is True
  assert payload["vector_retrieval"]["healthy"] is False
  assert payload["vector_retrieval"]["production_ready"] is False
  assert any("WORKTUAL_QDRANT_URL" in warning for warning in payload["vector_retrieval"]["warnings"])


def test_memory_health_passes_vector_gate_when_qdrant_configured(monkeypatch) -> None:
  from backend import main as backend_main

  monkeypatch.setattr(backend_main, "get_context", lambda: _Context())
  monkeypatch.setenv("WORKTUAL_ENV", "production")
  monkeypatch.setenv("WORKTUAL_QDRANT_URL", "http://localhost:6333")
  monkeypatch.setenv("ENABLE_EPISODIC_VECTOR_SEARCH", "true")
  monkeypatch.setenv("ENABLE_EPISODIC_VECTOR_MEMORY_FALLBACK", "false")

  payload = backend_main.memory_health(UserContext(id="admin", email="a@example.com", role="admin"))

  assert payload["ok"] is True
  assert payload["vector_retrieval"]["engine"] == "qdrant"
  assert payload["vector_retrieval"]["durable"] is True
  assert payload["vector_retrieval"]["production_ready"] is True


def test_validate_memory_constraints_endpoint_defaults_to_dry_run(monkeypatch) -> None:
  from backend import main as backend_main

  monkeypatch.setattr(backend_main, "get_context", lambda: _Context())

  payload = backend_main.validate_memory_constraints(
    _admin=UserContext(id="admin", email="a@example.com", role="admin")
  )

  assert payload["status"] == "ready"
  assert payload["dry_run"] is True


def test_validate_memory_constraints_endpoint_can_execute(monkeypatch) -> None:
  from backend import main as backend_main

  monkeypatch.setattr(backend_main, "get_context", lambda: _Context())

  payload = backend_main.validate_memory_constraints(
    dry_run=False,
    _admin=UserContext(id="admin", email="a@example.com", role="admin"),
  )

  assert payload["status"] == "validated"
  assert payload["dry_run"] is False
