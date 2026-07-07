from __future__ import annotations

from backend.agents.memory.dedup import blocks_are_redundant, dedupe_memory_blocks


def test_blocks_are_redundant_detects_overlap() -> None:
  primary = "update navbar spacing in src/components/Navbar.jsx for dark mode header"
  secondary = "website_update update navbar spacing dark mode header Navbar component"
  assert blocks_are_redundant(primary, secondary, threshold=0.45) is True


def test_dedupe_memory_blocks_drops_repeat() -> None:
  repeated = "update navbar spacing dark mode header Navbar.jsx component styling"
  blocks = [
    f"Session summary: {repeated}",
    f"Episodic memory: {repeated}",
    "Platform learning pattern for unrelated ecommerce checkout flow only",
  ]
  deduped = dedupe_memory_blocks(blocks, threshold=0.45)
  assert len(deduped) == 2
