from __future__ import annotations

from backend.agents.agent_runtime.update_analysis import (
  format_interaction_summary,
  normalize_interaction_intent,
)
from backend.agents.streaming.file_agent import _format_scope_enrichment_block
from backend.agents.update_engine.scope_enrichment import apply_scope_enrichment


def test_normalize_interaction_intent_structured() -> None:
  interaction = normalize_interaction_intent(
    {
      "component": "cart button",
      "trigger": "click",
      "expected": "add item and open cart details",
    }
  )
  assert interaction["component"] == "cart button"
  assert interaction["trigger"] == "click"
  assert "cart details" in interaction["expected"]


def test_format_interaction_summary_structured() -> None:
  summary = format_interaction_summary(
    {
      "component": "cart button",
      "trigger": "click",
      "expected": "add item and open cart details",
    }
  )
  assert "cart button" in summary
  assert "click" in summary
  assert "cart details" in summary


def test_apply_scope_enrichment_preserves_structured_interaction() -> None:
  enriched = apply_scope_enrichment(
    {
      "update_mode": "bug_fix",
      "request_kind": "interaction_wiring_update",
      "candidate_files": ["src/pages/Marketplace.jsx"],
      "interaction": {
        "component": "cart button",
        "trigger": "click",
        "expected": "add item and open cart details",
      },
    },
    prompt="cart button not working",
    project_files=[
      {
        "path": "src/pages/Marketplace.jsx",
        "content": "const handleAddToCart = () => {}; return <button onClick={handleAddToCart}>Add</button>;",
      }
    ],
  )
  assert enriched["interaction"]["component"] == "cart button"
  assert enriched["interaction"]["trigger"] == "click"
  assert "cart details" in enriched["interaction_summary"]


def test_format_scope_enrichment_block_uses_structured_interaction() -> None:
  block = _format_scope_enrichment_block(
    scoped_target_paths=["src/pages/Marketplace.jsx"],
    scope_enrichment_snippets=[{"path": "src/pages/Marketplace.jsx", "snippet": "onClick={handleAddToCart}"}],
    enrichment_profile="interaction_wiring",
    interaction_summary="",
    scope_rationale="",
    interaction={
      "component": "cart button",
      "trigger": "click",
      "expected": "add item and open cart details",
    },
  )
  assert "cart button" in block
  assert "click" in block
  assert "cart details" in block
