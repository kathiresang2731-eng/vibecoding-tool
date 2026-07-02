from __future__ import annotations

from backend.agents.streaming.update_write_guard import (
  STYLE_REFERENCE_CHANGE_FRACTION,
  allowed_change_fraction,
  filter_streaming_write_payload,
  is_predominantly_classname_style_diff,
)
from backend.agents.update_engine.commit_pipeline import build_commit_user_message


AUTH_BEFORE = """export default function Auth() {
  return (
    <div className="bg-slate-900 text-white min-h-screen p-8">
      <h1 className="text-2xl">Login</h1>
    </div>
  );
}
"""

AUTH_AFTER_CLASSNAME = """export default function Auth() {
  return (
    <div className="bg-emerald-600 text-white min-h-screen p-8">
      <h1 className="text-2xl">Login</h1>
    </div>
  );
}
"""


def test_classname_style_diff_detected() -> None:
  assert is_predominantly_classname_style_diff("src/pages/Auth.jsx", AUTH_BEFORE, AUTH_AFTER_CLASSNAME)


def test_style_reference_request_kind_allows_higher_fraction() -> None:
  limit = allowed_change_fraction(
    request_kind="style_reference_update",
    path="src/pages/Auth.jsx",
    previous=AUTH_BEFORE,
    candidate=AUTH_AFTER_CLASSNAME,
  )
  assert limit == STYLE_REFERENCE_CHANGE_FRACTION


def test_feature_patch_uses_broad_fraction() -> None:
  limit = allowed_change_fraction(update_mode="feature_patch")
  assert limit >= 0.8


def test_classname_patch_passes_filter_for_style_reference() -> None:
  payload = [{"path": "src/pages/Auth.jsx", "content": AUTH_AFTER_CLASSNAME}]
  before = {"src/pages/Auth.jsx": AUTH_BEFORE}
  accepted, rejected = filter_streaming_write_payload(
    before,
    payload,
    request_kind="style_reference_update",
    update_mode="feature_patch",
  )
  assert accepted
  assert not rejected


def test_handler_patch_passes_filter_for_interaction_wiring() -> None:
  before = (
    "export default function Marketplace() {\n"
    "  const [cart, setCart] = useState([]);\n"
    "  return <button>Cart</button>;\n"
    "}\n"
  )
  after = (
    "export default function Marketplace() {\n"
    "  const [cart, setCart] = useState([]);\n"
    "  const handleAddToCart = () => setCart((items) => [...items, 'item']);\n"
    "  return <button onClick={handleAddToCart}>Cart</button>;\n"
    "}\n"
  )
  accepted, rejected = filter_streaming_write_payload(
    {"src/pages/Marketplace.jsx": before},
    [{"path": "src/pages/Marketplace.jsx", "content": after}],
    request_kind="interaction_wiring_update",
    update_mode="bug_fix",
  )
  assert accepted
  assert not rejected


def test_rewrite_rejection_message_is_specific() -> None:
  message = build_commit_user_message(
    saved_paths=[],
    rejected_writes=[
      {
        "path": "src/pages/Auth.jsx",
        "reason": "rewrite_exceeds_safe_fraction",
        "change_fraction": 0.62,
        "allowed_fraction": 0.45,
      }
    ],
    agent_summary="",
    rejection_gate="rewrite_guard",
  )
  assert "Auth.jsx" in message
  assert "no code changes were applied" not in message.lower()


def test_precommit_rejection_message() -> None:
  message = build_commit_user_message(
    saved_paths=[],
    rejected_writes=[],
    agent_summary="",
    rejection_gate="precommit",
  )
  assert "visual qa" in message.lower() or "build" in message.lower()
