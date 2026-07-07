from backend.agents.orchestration.artifact_response import build_update_conversation_message
from backend.agents.streaming.file_agent import (
  _format_scope_enrichment_block,
  is_ui_interaction_repair_prompt,
  select_system_instruction,
)
from backend.agents.streaming.task_planner import _cart_interaction_paths, resolve_scoped_target_paths


def test_cart_button_prompt_detected() -> None:
  prompt = (
    "if i add any product to add to cart mean then it's added in the second cart button "
    "that button is not working so remove the white cart button and provide the functionalities "
    "for the header cart button"
  )
  assert is_ui_interaction_repair_prompt(prompt)


def test_cart_paths_target_navbar_and_marketplace() -> None:
  prompt = "header cart button not working on marketplace page"
  paths = [
    "src/components/Navbar.jsx",
    "src/pages/Marketplace.jsx",
    "src/pages/Auth.jsx",
    "src/pages/Onboarding.jsx",
    "package.json",
  ]
  files_map = {
    "src/components/Navbar.jsx": "export default function Navbar(){ return <button>Cart</button>; }",
    "src/pages/Marketplace.jsx": "const [cart, setCart] = useState([]); function handleAddToCart(){}",
    "src/pages/Auth.jsx": "export default function Auth(){}",
  }
  selected = _cart_interaction_paths(prompt, paths, files_map)
  assert "src/components/Navbar.jsx" in selected
  assert "src/pages/Marketplace.jsx" in selected
  assert "src/pages/Auth.jsx" not in selected


def test_resolve_scoped_targets_prefers_cart_over_merged_auth_context(monkeypatch) -> None:
  monkeypatch.setenv("ENABLE_LEGACY_PARALLEL_UPDATES", "true")
  monkeypatch.setenv("ENABLE_UNIFIED_UPDATE_ENGINE", "false")
  merged = (
    "header cart button not working\n\n"
    "Conversation continuity — earlier chat in this session still applies unless the latest message explicitly replaces it:\n\n"
    "Earlier user requirements:\n"
    "- first login then onboarding then dashboard"
  )
  paths = ["src/App.jsx", "src/pages/Auth.jsx", "src/pages/Marketplace.jsx", "src/components/Navbar.jsx"]
  files_map = {
    "src/App.jsx": "export default function App() { return null; }",
    "src/pages/Auth.jsx": "export default function Auth() { return <div>Login</div>; }",
    "src/pages/Marketplace.jsx": "const [cart, setCart] = useState([]); function handleAddToCart() {}",
    "src/components/Navbar.jsx": "export function Navbar() { return <button>Cart</button>; }",
  }
  targets = resolve_scoped_target_paths(merged, paths=paths, files_map=files_map)
  assert "src/components/Navbar.jsx" in targets or "src/pages/Marketplace.jsx" in targets
  assert "src/pages/Auth.jsx" not in targets


def test_ui_interaction_instruction_mentions_navbar_legacy(monkeypatch) -> None:
  monkeypatch.setenv("ENABLE_LEGACY_PARALLEL_UPDATES", "true")
  instruction = select_system_instruction(
    intent="website_update",
    prompt="cart button in header not working",
  )
  assert "Navbar" in instruction
  assert "cart" in instruction.lower()


def test_ui_interaction_instruction_unified_is_generic() -> None:
  instruction = select_system_instruction(
    intent="website_update",
    prompt="cart button in header not working",
  )
  assert "marketplace/product/cart page first" not in instruction.lower()
  assert "DIRECT PROJECT UPDATE" in instruction
  assert "str_replace" in instruction


def test_locked_file_rejection_message() -> None:
  message = build_update_conversation_message(
    artifact_response={
      "summary": "Updated project files from your prompt.",
      "changed_paths": [],
      "runtime": {
        "rejected_writes": [
          {"path": "package.json", "reason": "locked_platform_file"},
          {"path": "tailwind.config.js", "reason": "locked_platform_file"},
        ],
      },
    }
  )
  assert "locked platform files" in message.lower()
  assert "no code changes were applied" not in message.lower()


def test_file_agent_enrichment_block_for_cart() -> None:
  block = _format_scope_enrichment_block(
    scoped_target_paths=["src/components/Navbar.jsx", "src/pages/Marketplace.jsx"],
    scope_enrichment_snippets=[
      {"path": "src/pages/Marketplace.jsx", "snippet": "const handleAddToCart = () => setCart(...)"},
    ],
    enrichment_profile="interaction_wiring",
    interaction_summary="Header cart button should add products",
    scope_rationale="Navbar and Marketplace cart wiring",
  )
  assert "Pre-loaded handler/UI context" in block
  assert "Priority files from project memory/search" in block
  assert "handleAddToCart" in block
  assert "Navbar.jsx" in block or "Marketplace.jsx" in block
