from __future__ import annotations

import os

os.environ.setdefault("ENABLE_UNIFIED_UPDATE_ENGINE", "true")
os.environ.setdefault("ENABLE_CODE_INDEX", "true")
os.environ.setdefault("ENABLE_LEGACY_PARALLEL_UPDATES", "false")

from backend.agents.streaming.file_agent import _format_scope_enrichment_block
from backend.agents.streaming.update_write_guard import allowed_change_fraction, is_predominantly_handler_state_diff
from backend.agents.update_engine.scope_engine import resolve_update_scope
from backend.agents.update_engine.scope_enrichment import (
  PROFILE_INTERACTION_WIRING,
  PROFILE_STYLE_REFERENCE,
  apply_scope_enrichment,
  build_scope_enrichment_snippets,
  resolve_enrichment_profile,
)


MARKETPLACE_FILE = {
  "path": "src/pages/Marketplace.jsx",
  "content": (
    "import React, { useState } from 'react';\n"
    "export default function Marketplace() {\n"
    "  const [cart, setCart] = useState([]);\n"
    "  const handleAddToCart = (product) => setCart((items) => [...items, product]);\n"
    "  return <button onClick={() => handleAddToCart('item')}>Add to cart</button>;\n"
    "}\n"
  ),
}

NAVBAR_FILE = {
  "path": "src/components/Navbar.jsx",
  "content": (
    "export function Navbar() {\n"
    "  return <button onClick={() => window.location.hash = '#/cart'}>Cart</button>;\n"
    "}\n"
  ),
}

DASHBOARD_FILE = {
  "path": "src/pages/Dashboard.jsx",
  "content": "export default function Dashboard() { return <div className='bg-emerald-600 text-white'>Dashboard</div>; }",
}

AUTH_FILE = {
  "path": "src/pages/Auth.jsx",
  "content": "export default function Auth() { return <div className='bg-slate-900'>Login</div>; }",
}

SAMPLE_FILES = [MARKETPLACE_FILE, NAVBAR_FILE, AUTH_FILE, DASHBOARD_FILE]


def test_interaction_profile_requires_llm_contract_not_prompt_keywords() -> None:
  prompt = "add to cart button is not working on marketplace page"
  analysis = {"update_mode": "bug_fix", "request_kind": "bug_fix", "candidate_files": ["src/pages/Marketplace.jsx"]}
  profile = resolve_enrichment_profile(prompt=prompt, analysis=analysis)
  assert profile == "general_scoped"

  analysis["interaction"] = {
    "component": "Add to cart button",
    "trigger": "click",
    "expected": "add the selected item to cart",
    "source_page": "Marketplace",
    "confidence": 0.94,
  }
  profile = resolve_enrichment_profile(prompt=prompt, analysis=analysis)
  assert profile == PROFILE_INTERACTION_WIRING


def test_build_snippets_extract_onclick_handlers() -> None:
  files_map = {item["path"]: item["content"] for item in [MARKETPLACE_FILE, NAVBAR_FILE]}
  snippets = build_scope_enrichment_snippets(
    files_map=files_map,
    candidate_files=["src/pages/Marketplace.jsx", "src/components/Navbar.jsx"],
    reference_files=[],
    prompt="fix header cart button not working",
    profile=PROFILE_INTERACTION_WIRING,
  )
  assert snippets
  joined = "\n".join(str(item.get("snippet") or "") for item in snippets).lower()
  assert "handleaddtocart" in joined or "onclick" in joined


def test_scope_engine_includes_enrichment_for_cart_prompt() -> None:
  scope = resolve_update_scope(
    prompt="add to cart button is not working",
    project_files=SAMPLE_FILES,
    control_provider=None,
  )
  assert scope.scope_enrichment_snippets
  assert scope.enrichment_profile in {PROFILE_INTERACTION_WIRING, "general_scoped"}
  assert any("Marketplace" in str(item.get("path") or "") for item in scope.scope_enrichment_snippets)


def test_style_reference_still_populates_style_snippets() -> None:
  enriched = apply_scope_enrichment(
    {
      "update_mode": "feature_patch",
      "request_kind": "style_reference_update",
      "candidate_files": ["src/pages/Auth.jsx"],
      "target_files": ["src/pages/Auth.jsx"],
      "reference_files": ["src/pages/Dashboard.jsx"],
      "style_reference_snippets": [{"path": "src/pages/Dashboard.jsx", "snippet": "bg-emerald-600"}],
    },
    prompt="change auth page colors to same like dashboard",
    project_files=SAMPLE_FILES,
  )
  assert enriched.get("enrichment_profile") == PROFILE_STYLE_REFERENCE
  kinds = {str(item.get("kind") or "") for item in enriched.get("scope_enrichment_snippets") or []}
  assert "style" in kinds or enriched.get("style_reference_snippets")


def test_apply_scope_enrichment_sets_interaction_request_kind() -> None:
  enriched = apply_scope_enrichment(
    {
      "update_mode": "bug_fix",
      "request_kind": "other",
      "candidate_files": ["src/pages/Marketplace.jsx", "src/components/Navbar.jsx"],
      "interaction": {
        "component": "header cart button",
        "trigger": "click",
        "expected": "open the cart",
        "source_page": "Marketplace",
        "target_page_or_route": "/cart",
        "confidence": 0.92,
      },
    },
    prompt="header cart button not working",
    project_files=SAMPLE_FILES,
  )
  assert enriched.get("request_kind") == "interaction_wiring_update"
  assert enriched.get("interaction_summary")
  assert enriched.get("scope_enrichment_snippets")


def test_format_scope_enrichment_block_for_interaction() -> None:
  block = _format_scope_enrichment_block(
    scoped_target_paths=["src/pages/Marketplace.jsx"],
    scope_enrichment_snippets=[{"path": "src/pages/Marketplace.jsx", "snippet": "onClick={() => handleAddToCart()}"}],
    enrichment_profile=PROFILE_INTERACTION_WIRING,
    interaction_summary="Cart button should add items",
    scope_rationale="Marketplace cart handler",
  )
  assert "Pre-loaded handler/UI context" in block
  assert "handleAddToCart" in block or "onClick" in block


def test_handler_diff_allows_broader_fraction_for_interaction_kind() -> None:
  previous = "const [cart, setCart] = useState([]);\nexport default function X() { return <button>Cart</button>; }"
  candidate = (
    "const [cart, setCart] = useState([]);\n"
    "const handleAddToCart = () => setCart((items) => [...items, 'x']);\n"
    "export default function X() { return <button onClick={handleAddToCart}>Cart</button>; }"
  )
  assert is_predominantly_handler_state_diff("src/pages/Marketplace.jsx", previous, candidate)
  limit = allowed_change_fraction(
    request_kind="interaction_wiring_update",
    path="src/pages/Marketplace.jsx",
    previous=previous,
    candidate=candidate,
  )
  assert limit >= 0.65
