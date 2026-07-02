from __future__ import annotations

from backend.agents.streaming.update_validation import (
  extract_rename_target,
  is_brand_rename_prompt,
  validate_brand_rename,
)


def test_is_brand_rename_prompt() -> None:
  assert is_brand_rename_prompt("change the website name to worktual Ai CRM")
  assert not is_brand_rename_prompt("change hero text on Home.jsx")
  assert not is_brand_rename_prompt(
    "provide the function for add to cart button\n\n"
    "Conversation continuity — earlier chat in this session still applies unless the latest message explicitly replaces it:\n\n"
    "Earlier user requirements:\n"
    "- change the website name to AgriGrow Marketplace"
  )


def test_extract_rename_target_ignores_continuity_block() -> None:
  merged = (
    "provide the function for add to cart button\n\n"
    "Conversation continuity — earlier chat in this session still applies unless the latest message explicitly replaces it:\n\n"
    "Earlier user requirements:\n"
    "- change the website name to AgriGrow Marketplace"
  )
  assert extract_rename_target(merged) is None
  assert validate_brand_rename(
    merged,
    files_before={"src/components/Navbar.jsx": "Old"},
    files_after={"src/components/Navbar.jsx": "Old"},
    changed_paths=[],
  ) is None


def test_extract_rename_target() -> None:
  assert extract_rename_target("change the website name to worktual Ai CRM") == "worktual Ai CRM"


def test_validate_brand_rename_detects_missing_change() -> None:
  prompt = "change the website name to worktual Ai CRM"
  before = {
    "index.html": "<title>Old CRM</title>",
    "src/components/Navbar.jsx": "Old CRM",
  }
  after = dict(before)
  result = validate_brand_rename(
    prompt,
    files_before=before,
    files_after=after,
    changed_paths=[],
  )
  assert result is not None
  assert result["applied"] is False
  assert result["expected"] == "worktual Ai CRM"


def test_validate_brand_rename_detects_applied_change() -> None:
  prompt = "change the website name to worktual Ai CRM"
  before = {
    "index.html": "<title>Old CRM</title>",
    "src/components/Navbar.jsx": "Old CRM",
  }
  after = {
    "index.html": "<title>Old CRM</title>",
    "src/components/Navbar.jsx": "worktual Ai CRM",
  }
  result = validate_brand_rename(
    prompt,
    files_before=before,
    files_after=after,
    changed_paths=["src/components/Navbar.jsx"],
  )
  assert result is not None
  assert result["applied"] is True


def test_apply_brand_rename_fallback_updates_navbar_not_locked_files() -> None:
  from backend.agents.streaming.update_validation import apply_brand_rename_fallback

  files = {
    "index.html": "<html><head><title>Old CRM</title></head></html>",
    "package.json": '{"name":"old-crm","version":"1.0.0"}',
    "src/components/Navbar.jsx": "export default function Navbar(){ return <div>Old CRM</div>; }",
  }
  payload, paths = apply_brand_rename_fallback(files, target_name="worktual Ai CRM")
  assert "index.html" not in paths
  assert "package.json" not in paths
  navbar_item = next(item for item in payload if item["path"] == "src/components/Navbar.jsx")
  assert "worktual Ai CRM" in navbar_item["content"]
