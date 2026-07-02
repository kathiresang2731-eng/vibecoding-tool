from __future__ import annotations

import os

os.environ.setdefault("ENABLE_UNIFIED_UPDATE_ENGINE", "true")
os.environ.setdefault("ENABLE_CODE_INDEX", "true")

from backend.agents.update_engine.scope_engine import _minimal_code_search_fallback, resolve_update_scope


SAMPLE_FILES = [
  {
    "path": "src/components/Navbar.jsx",
    "content": "export function Navbar() { const [cart, setCart] = useState([]); return <button onClick={addToCart}>Cart</button>; }",
  },
  {
    "path": "src/pages/Marketplace.jsx",
    "content": "export default function Marketplace() { return <div>Products</div>; }",
  },
  {
    "path": "src/App.jsx",
    "content": "import { BrowserRouter } from 'react-router-dom'; export default function App() { return <BrowserRouter />; }",
  },
]


def test_minimal_code_search_fallback_finds_cart_files():
  result = _minimal_code_search_fallback("fix header cart button", SAMPLE_FILES, max_candidates=4)
  candidates = result.get("candidate_files") or []
  assert candidates
  assert any("Navbar" in path or "Marketplace" in path or "cart" in path.lower() for path in candidates)
  assert result.get("preflight_source") == "scope_engine_code_search_fallback"


def test_resolve_update_scope_without_provider_uses_fallback():
  scope = resolve_update_scope(
    prompt="fix header cart button",
    project_files=SAMPLE_FILES,
    control_provider=None,
    project_id="proj-1",
  )
  assert scope.candidate_files
  assert scope.preflight_source in {"legacy_fallback", "scope_engine_code_search_fallback"}


def test_resolve_update_scope_emits_progress_events():
  events: list[tuple[str, str]] = []

  def emit(step: str, message: str, **_kwargs):
    events.append((step, message))

  resolve_update_scope(
    prompt="wire add to cart on marketplace page",
    project_files=SAMPLE_FILES,
    control_provider=None,
    emit_progress=emit,
  )
  assert any(step == "scope.resolved" for step, _ in events)
