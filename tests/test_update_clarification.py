from __future__ import annotations

from backend.agents.streaming.update_clarification import check_streaming_update_clarification


def test_vague_update_requires_clarification() -> None:
  question = check_streaming_update_clarification(
    "make it better",
    intent="website_update",
    project_files=[{"path": "src/pages/Home.jsx", "content": "export default function Home(){}"}],
    scoped_targets=[],
  )
  assert question
  assert "which" in question.lower()


def test_specific_update_does_not_require_clarification() -> None:
  question = check_streaming_update_clarification(
    "Update the navbar in src/components/Navbar.jsx to dark mode",
    intent="website_update",
    project_files=[{"path": "src/components/Navbar.jsx", "content": "export default function Navbar(){}"}],
    scoped_targets=["src/components/Navbar.jsx"],
  )
  assert question is None


def test_conversation_context_allows_short_referential_update() -> None:
  question = check_streaming_update_clarification(
    "change it to dark mode",
    intent="website_update",
    project_files=[{"path": "src/pages/Home.jsx", "content": "export default function Home(){}"}],
    scoped_targets=[],
    has_conversation_context=True,
  )
  assert question is None


def test_generation_intent_skips_clarification() -> None:
  assert check_streaming_update_clarification("make it better", intent="website_generation") is None
