"""Legacy cart/auth routing prompts — imported only when ENABLE_LEGACY_PARALLEL_UPDATES=true."""

from __future__ import annotations


def _update_base_instruction() -> str:
  from .file_agent import UPDATE_SYSTEM_INSTRUCTION

  return UPDATE_SYSTEM_INSTRUCTION


def auth_flow_update_system_instruction() -> str:
  return (
    f"{_update_base_instruction()} "
    "The user wants auth/login BEFORE onboarding and dashboard access. Work across src/App.jsx plus the "
    "auth/login/onboarding page files already in the project. Use react-router-dom: default route or / "
    "must land on auth/login, successful login navigates to onboarding, onboarding completion navigates "
    "to dashboard/home. Add minimal local state (useState) or sessionStorage flags if needed. "
    "Read src/App.jsx first, then auth/onboarding pages. Apply small balanced str_replace edits — "
    "every JSX file must keep matching braces/parentheses or the save will be blocked."
  )


def ui_interaction_repair_system_instruction() -> str:
  return (
    f"{_update_base_instruction()} "
    "The user is reporting broken buttons, cart behavior, or click handlers. Read src/components/Navbar.jsx "
    "(or Header.jsx) and the marketplace/product/cart page first. Wire shared cart state (useState, context, "
    "or lifting state to App.jsx), implement handleAddToCart/onClick handlers, and remove duplicate or dead "
    "cart buttons. Never edit locked platform files (package.json, tailwind.config.js, index.html, src/index.css). "
    "Never edit Auth.jsx or Onboarding.jsx unless the latest message explicitly asks for auth/onboarding changes."
  )


def select_legacy_system_instruction(*, prompt: str) -> str:
  from .file_agent import ERROR_REPAIR_SYSTEM_INSTRUCTION, UPDATE_SYSTEM_INSTRUCTION
  from .file_agent import is_auth_flow_update_prompt, is_error_repair_prompt, is_ui_interaction_repair_prompt

  if is_ui_interaction_repair_prompt(prompt):
    return ui_interaction_repair_system_instruction()
  if is_error_repair_prompt(prompt):
    return ERROR_REPAIR_SYSTEM_INSTRUCTION
  if is_auth_flow_update_prompt(prompt):
    return auth_flow_update_system_instruction()
  return UPDATE_SYSTEM_INSTRUCTION


def legacy_ui_interaction_user_message_block() -> str:
  return (
    "Fix the reported cart/button interaction in Navbar/Header and the marketplace or product page. "
    "Use str_replace to wire onClick handlers and shared cart state. "
    "Do not edit Auth.jsx, Onboarding.jsx, or locked platform config files.\n\n"
  )
