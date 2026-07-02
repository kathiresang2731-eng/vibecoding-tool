from __future__ import annotations

from backend.agents.streaming.module_contracts import (
  module_exports,
  normalize_relative_import_export_contracts,
)


def test_module_exports_does_not_treat_default_function_as_named_export() -> None:
  has_default, named = module_exports("export default function AiChat(){ return null; }")

  assert has_default is True
  assert "AiChat" not in named


def test_normalize_named_import_to_default_when_target_only_exports_default() -> None:
  files = [
    {"path": "src/App.jsx", "content": 'import { AiChat } from "./pages/AiChat";\nexport default AiChat;'},
    {"path": "src/pages/AiChat.jsx", "content": "export default function AiChat(){ return null; }"},
  ]

  normalized, changed_paths, repairs = normalize_relative_import_export_contracts(files)
  app = next(item for item in normalized if item["path"] == "src/App.jsx")

  assert 'import AiChat from "./pages/AiChat";' in app["content"]
  assert changed_paths == ["src/App.jsx"]
  assert repairs[0]["repair"] == "named_to_default"
  assert repairs[0]["target"] == "src/pages/AiChat.jsx"


def test_normalize_default_import_to_named_when_target_only_exports_named_symbol() -> None:
  files = [
    {"path": "src/App.jsx", "content": 'import Layout from "./components/Layout";\nexport default Layout;'},
    {"path": "src/components/Layout.jsx", "content": "export function Layout(){ return null; }"},
  ]

  normalized, changed_paths, repairs = normalize_relative_import_export_contracts(files)
  app = next(item for item in normalized if item["path"] == "src/App.jsx")

  assert 'import { Layout } from "./components/Layout";' in app["content"]
  assert changed_paths == ["src/App.jsx"]
  assert repairs[0]["repair"] == "default_to_named"
  assert repairs[0]["target"] == "src/components/Layout.jsx"
