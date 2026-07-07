import os
from unittest.mock import MagicMock, patch

import pytest

from backend.agents.memory.episode_embeddings import (
  build_episode_embedding_text,
  embed_episode_text,
)
from backend.agents.memory.episode_retrieval import rank_episodic_memories_with_vector
from backend.agents.memory.episode_vector_store import (
  InMemoryEpisodeVectorStore,
  delete_episode_vector,
  episode_vector_health,
  index_episode_vector,
  reset_episode_vector_store_for_tests,
  search_episode_vectors,
  episodic_vector_memory_fallback_enabled,
)
from backend.agents.memory.episode_vector_sync import remove_episode_vector, sync_episode_vector_from_row
from backend.agents.memory.episodic import build_episodic_context_block


@pytest.fixture(autouse=True)
def _reset_vector_store():
  reset_episode_vector_store_for_tests()
  yield
  reset_episode_vector_store_for_tests()


def test_build_episode_embedding_text_includes_summary_paths_and_prompt():
  text = build_episode_embedding_text(
    searchable_summary="Adjusted navbar spacing",
    intent="website_update",
    outcome="completed",
    changed_paths=["src/components/Navbar.jsx"],
    prompt="fix navbar spacing",
  )
  assert "Adjusted navbar spacing" in text
  assert "intent:website_update" in text
  assert "paths:src/components/Navbar.jsx" in text
  assert "prompt:fix navbar spacing" in text


def test_embed_episode_text_uses_local_hash_without_api_key():
  with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
    vector = embed_episode_text("navbar spacing layout")
  assert isinstance(vector, list)
  assert len(vector) >= 32
  assert pytest.approx(sum(value * value for value in vector), rel=1e-3) == 1.0


def test_production_disables_implicit_process_local_vector_fallback():
  with patch.dict(
    os.environ,
    {
      "WORKTUAL_ENV": "production",
      "WORKTUAL_QDRANT_URL": "",
    },
    clear=False,
  ):
    os.environ.pop("ENABLE_EPISODIC_VECTOR_MEMORY_FALLBACK", None)
    assert episodic_vector_memory_fallback_enabled() is False


def test_vector_health_warns_when_process_local_fallback_is_active():
  with patch.dict(
    os.environ,
    {
      "WORKTUAL_ENV": "development",
      "WORKTUAL_QDRANT_URL": "",
      "ENABLE_EPISODIC_VECTOR_SEARCH": "true",
      "ENABLE_EPISODIC_VECTOR_MEMORY_FALLBACK": "true",
    },
    clear=False,
  ):
    health = episode_vector_health()

  assert health["engine"] == "memory"
  assert health["durable"] is False
  assert health["healthy"] is False
  assert any("process-local memory fallback" in warning for warning in health["warnings"])


def test_vector_health_warns_when_fallback_forced_on_in_production():
  with patch.dict(
    os.environ,
    {
      "WORKTUAL_ENV": "production",
      "WORKTUAL_QDRANT_URL": "",
      "ENABLE_EPISODIC_VECTOR_SEARCH": "true",
      "ENABLE_EPISODIC_VECTOR_MEMORY_FALLBACK": "true",
    },
    clear=False,
  ):
    health = episode_vector_health()

  assert health["engine"] == "memory"
  assert health["production_ready"] is False
  assert any("production-like environment" in warning for warning in health["warnings"])


def test_vector_health_is_production_ready_with_qdrant():
  with patch.dict(
    os.environ,
    {
      "WORKTUAL_ENV": "production",
      "WORKTUAL_QDRANT_URL": "http://localhost:6333",
      "ENABLE_EPISODIC_VECTOR_SEARCH": "true",
      "ENABLE_EPISODIC_VECTOR_MEMORY_FALLBACK": "false",
    },
    clear=False,
  ):
    health = episode_vector_health()

  assert health["engine"] == "qdrant"
  assert health["durable"] is True
  assert health["production_ready"] is True
  assert health["healthy"] is True
  assert health["warnings"] == []


def test_in_memory_vector_store_scopes_search_to_session():
  store = InMemoryEpisodeVectorStore()
  store.upsert_episode(
    episode_id="ep-1",
    user_id="user-1",
    project_id="project-1",
    chat_session_id="session-a",
    searchable_summary="Navbar spacing fix",
    intent="website_update",
    changed_paths=["src/Navbar.jsx"],
    prompt="fix navbar spacing",
  )
  store.upsert_episode(
    episode_id="ep-2",
    user_id="user-1",
    project_id="project-1",
    chat_session_id="session-b",
    searchable_summary="Navbar spacing fix",
    intent="website_update",
    changed_paths=["src/Navbar.jsx"],
    prompt="fix navbar spacing",
  )

  hits = store.search(
    query="fix navbar spacing",
    user_id="user-1",
    project_id="project-1",
    chat_session_id="session-a",
    limit=5,
  )
  assert len(hits) == 1
  assert hits[0]["episode_id"] == "ep-1"
  assert hits[0]["engine"] == "memory_vector"


def test_index_search_and_delete_episode_vectors_with_memory_fallback():
  env = {
    "WORKTUAL_QDRANT_URL": "",
    "ENABLE_EPISODIC_VECTOR_SEARCH": "true",
    "ENABLE_EPISODIC_VECTOR_MEMORY_FALLBACK": "true",
  }
  with patch.dict(os.environ, env, clear=False):
    indexed = index_episode_vector(
      episode_id="ep-navbar",
      user_id="user-1",
      project_id="project-1",
      chat_session_id="session-1",
      searchable_summary="Tightened navbar spacing and alignment",
      intent="website_update",
      changed_paths=["src/components/Navbar.jsx"],
      prompt="fix navbar spacing",
    )
    assert indexed is True

    hits = search_episode_vectors(
      query="navbar spacing alignment",
      user_id="user-1",
      project_id="project-1",
      chat_session_id="session-1",
      limit=3,
    )
    assert hits
    assert hits[0]["episode_id"] == "ep-navbar"

    deleted = delete_episode_vector(episode_id="ep-navbar")
    assert deleted is True
    assert search_episode_vectors(
      query="navbar spacing alignment",
      user_id="user-1",
      project_id="project-1",
      chat_session_id="session-1",
      limit=3,
    ) == []


def test_sync_episode_vector_from_row_indexes_metadata_fields():
  env = {
    "WORKTUAL_QDRANT_URL": "",
    "ENABLE_EPISODIC_VECTOR_SEARCH": "true",
    "ENABLE_EPISODIC_VECTOR_MEMORY_FALLBACK": "true",
  }
  row = {
    "id": "ep-sync",
    "searchable_summary": "Footer copyright year update",
    "outcome": "completed",
    "metadata_json": {
      "intent": "website_update",
      "prompt": "update footer copyright",
      "changed_paths": ["src/Footer.jsx"],
    },
  }
  with patch.dict(os.environ, env, clear=False):
    assert sync_episode_vector_from_row(
      row,
      user_id="user-1",
      project_id="project-1",
      chat_session_id="session-1",
    )
    hits = search_episode_vectors(
      query="footer copyright year",
      user_id="user-1",
      project_id="project-1",
      chat_session_id="session-1",
      limit=3,
    )
    assert hits[0]["episode_id"] == "ep-sync"
    assert remove_episode_vector(episode_id="ep-sync")


def test_vector_ranking_boosts_semantically_aligned_episode():
  navbar = {
    "id": "ep-navbar",
    "content": "Intent: website_update\nUser request: navbar spacing",
    "metadata_json": {"changed_paths": ["src/Navbar.jsx"], "intent": "website_update"},
    "updated_at": "2026-06-27T12:00:00Z",
  }
  footer = {
    "id": "ep-footer",
    "content": "Intent: website_update\nUser request: footer copyright",
    "metadata_json": {"changed_paths": ["src/Footer.jsx"], "intent": "website_update"},
    "updated_at": "2026-06-27T12:00:00Z",
  }
  ranked = rank_episodic_memories_with_vector(
    [footer, navbar],
    prompt="fix navbar spacing",
    vector_scores={"ep-navbar": 0.95, "ep-footer": 0.05},
  )
  assert ranked[0]["id"] == "ep-navbar"


def test_context_block_preserves_existing_vector_ranking():
  vector_first = {
    "id": "ep-vector-first",
    "key": "vector-first",
    "content": "Semantically selected checkout repair",
    "metadata_json": {"intent": "website_update"},
  }
  lexical_second = {
    "id": "ep-lexical-second",
    "key": "lexical-second",
    "content": "navbar navbar navbar spacing",
    "metadata_json": {"intent": "website_update"},
  }

  block = build_episodic_context_block(
    [vector_first, lexical_second],
    prompt="navbar spacing",
    already_ranked=True,
  )

  assert block.index("vector-first") < block.index("lexical-second")


def test_qdrant_store_search_maps_hits(monkeypatch):
  from backend.agents.memory import episode_vector_store as vector_module

  mock_client = MagicMock()
  mock_client.collection_exists.return_value = True
  hit = MagicMock()
  hit.id = "ep-qdrant"
  hit.score = 0.88
  hit.payload = {"episode_id": "ep-qdrant"}
  mock_client.search.return_value = [hit]

  store = vector_module.QdrantEpisodeVectorStore(url="http://localhost:6333")
  monkeypatch.setattr(store, "_get_client", lambda: mock_client)

  results = store.search(
    query="navbar spacing",
    user_id="user-1",
    project_id="project-1",
    chat_session_id="session-1",
    limit=3,
  )
  assert results == [{"episode_id": "ep-qdrant", "score": 0.88, "engine": "qdrant"}]
  mock_client.search.assert_called_once()
