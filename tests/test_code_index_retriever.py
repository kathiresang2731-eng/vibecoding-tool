from __future__ import annotations

import os

os.environ.setdefault("ENABLE_CODE_INDEX", "true")

from backend.agents.code_index.indexer import chunk_file, chunk_project_files
from backend.agents.code_index.retriever import index_files, retrieve_code_context
from backend.agents.code_index.store import get_project_chunks, set_project_chunks


SAMPLE_FILES = [
  {
    "path": "src/pages/Marketplace.jsx",
    "content": (
      "import React, { useState } from 'react';\n"
      "export default function Marketplace() {\n"
      "  const [cart, setCart] = useState([]);\n"
      "  const handleAddToCart = () => setCart((items) => [...items, 'item']);\n"
      "  return <button onClick={handleAddToCart}>Add to cart</button>;\n"
      "}\n"
    ),
  },
  {
    "path": "src/components/Navbar.jsx",
    "content": "export function Navbar() { return <nav>Shop</nav>; }",
  },
]


def test_chunk_file_splits_on_export_boundaries():
  chunks = chunk_file(SAMPLE_FILES[0]["path"], SAMPLE_FILES[0]["content"])
  assert chunks
  assert all(chunk.get("path") == SAMPLE_FILES[0]["path"] for chunk in chunks)


def test_retrieve_code_context_ranks_cart_query():
  index_files("test-project", SAMPLE_FILES)
  matches = retrieve_code_context(
    "add to cart button marketplace",
    SAMPLE_FILES,
    project_id="test-project",
    limit=4,
  )
  assert matches
  top_path = str(matches[0].get("path") or "")
  assert "Marketplace" in top_path or "Navbar" in top_path


def test_build_update_code_search_matches_imports_under_backend_package():
  """Regression: nested update_analysis must not fall back to top-level agents."""
  from backend.agents.agent_runtime.update_analysis import build_update_code_search_matches

  matches = build_update_code_search_matches("add to cart button marketplace", SAMPLE_FILES)
  assert matches
  assert any("Marketplace" in str(match.get("path") or "") for match in matches)


def test_retrieve_code_context_hydrates_persisted_chunks_after_cache_reset():
  project_id = "persisted-index-project"
  persisted = chunk_project_files(SAMPLE_FILES, project_id=project_id)
  files = [
    {
      **item,
      "content_hash": next(
        chunk["file_content_hash"]
        for chunk in persisted
        if chunk["path"] == item["path"]
      ),
      "code_index_chunks": [
        {**chunk, "embedding": []}
        for chunk in persisted
        if chunk["path"] == item["path"]
      ],
    }
    for item in SAMPLE_FILES
  ]
  set_project_chunks(project_id, [])

  matches = retrieve_code_context(
    "add to cart marketplace",
    files,
    project_id=project_id,
    limit=4,
  )

  assert matches
  assert matches[0]["path"] == "src/pages/Marketplace.jsx"
  assert get_project_chunks(project_id)


def test_retrieve_code_context_rejects_stale_persisted_chunks():
  project_id = "stale-persisted-index-project"
  old_chunks = chunk_project_files(SAMPLE_FILES, project_id=project_id)
  changed_files = [
    {
      **SAMPLE_FILES[0],
      "content": "export default function Marketplace() { return <button>New checkout flow</button>; }",
      "code_index_chunks": [
        {**chunk, "embedding": []}
        for chunk in old_chunks
        if chunk["path"] == SAMPLE_FILES[0]["path"]
      ],
    },
    {
      **SAMPLE_FILES[1],
      "code_index_chunks": [
        {**chunk, "embedding": []}
        for chunk in old_chunks
        if chunk["path"] == SAMPLE_FILES[1]["path"]
      ],
    },
  ]
  set_project_chunks(project_id, [])

  matches = retrieve_code_context(
    "new checkout flow",
    changed_files,
    project_id=project_id,
    limit=4,
  )

  assert matches
  assert matches[0]["path"] == "src/pages/Marketplace.jsx"
  assert any("New checkout flow" in str(chunk.get("content") or "") for chunk in get_project_chunks(project_id))
