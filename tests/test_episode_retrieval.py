import os
from unittest.mock import patch

from backend.agents.memory.episode_retrieval import (
  rank_episodic_memories_hybrid,
  score_episodic_hybrid,
  score_episodic_semantic,
)
from backend.agents.memory.episodic import rank_episodic_memories, score_episodic_relevance


def _memory(*, content: str, paths: list[str] | None = None, intent: str = "website_update") -> dict:
  return {
    "content": content,
    "metadata_json": {
      "intent": intent,
      "changed_paths": paths or [],
      "prompt": content,
    },
    "updated_at": "2026-06-27T12:00:00Z",
  }


def test_semantic_score_matches_path_stems_when_prompt_uses_component_name():
  memory = _memory(
    content="Intent: website_update\nUser request: adjust top navigation spacing",
    paths=["src/components/Navbar.jsx"],
  )
  score = score_episodic_semantic(memory, "fix the navbar layout")
  assert score > 0.2


def test_hybrid_ranking_prefers_path_aligned_memory():
  navbar_memory = _memory(
    content="Intent: website_update\nUser request: tighten navbar spacing",
    paths=["src/components/Navbar.jsx"],
  )
  footer_memory = _memory(
    content="Intent: website_update\nUser request: update footer copyright",
    paths=["src/components/Footer.jsx"],
  )
  ranked = rank_episodic_memories_hybrid([footer_memory, navbar_memory], prompt="fix navbar spacing")
  assert ranked[0]["metadata_json"]["changed_paths"] == ["src/components/Navbar.jsx"]


def test_hybrid_combines_semantic_and_token_signals():
  memory = _memory(
    content="Intent: website_update\nUser request: adjust top navigation spacing",
    paths=[],
  )
  token_only = score_episodic_relevance(memory, "top navigation spacing")
  hybrid = score_episodic_hybrid(memory, "top navigation spacing")
  assert token_only > 0
  assert hybrid > 0
  assert hybrid >= token_only * 0.4


def test_rank_episodic_memories_uses_hybrid_when_enabled():
  memories = [
    _memory(content="Intent: website_update\nUser request: footer legal links", paths=["src/Footer.jsx"]),
    _memory(content="Intent: website_update\nUser request: navbar spacing", paths=["src/Navbar.jsx"]),
  ]
  with patch.dict(os.environ, {"ENABLE_EPISODIC_HYBRID_RETRIEVAL": "true"}, clear=False):
    ranked = rank_episodic_memories(memories, prompt="fix navbar spacing")
  assert "Navbar.jsx" in ranked[0]["metadata_json"]["changed_paths"][0]
