from backend.agents.platform_file_locks import (
  LOCKED_PLATFORM_UPDATE_PATHS,
  filter_locked_platform_writes,
  guard_locked_platform_write,
  is_locked_platform_update_path,
)
from backend.agents.streaming.update_write_guard import (
  filter_streaming_write_payload,
  guard_streaming_file_write,
)


def test_locked_paths_include_user_six_files():
  expected = {
    "index.html",
    "package.json",
    "package-lock.json",
    "src/index.css",
    "tailwind.config.js",
    "vite.config.js",
  }
  assert expected == set(LOCKED_PLATFORM_UPDATE_PATHS)


def test_is_locked_platform_update_path_matches_variants():
  assert is_locked_platform_update_path("index.html")
  assert is_locked_platform_update_path("vite.config.ts")
  assert is_locked_platform_update_path("tailwind.config.cjs")
  assert not is_locked_platform_update_path("src/App.jsx")


def test_guard_blocks_existing_locked_file_on_update():
  blocked = guard_locked_platform_write(
    "package.json",
    intent="website_update",
    previous_content='{"name":"demo"}',
  )
  assert blocked is not None
  assert blocked.get("locked_platform_file") is True


def test_guard_allows_scaffold_injection_reason():
  blocked = guard_locked_platform_write(
    "package.json",
    intent="website_update",
    persist_reason="platform_vite_scaffold",
    previous_content='{"name":"demo"}',
  )
  assert blocked is None


def test_filter_locked_platform_writes_drops_existing_locked_files():
  before = {"vite.config.js": "export default {}"}
  payload = [{"path": "vite.config.js", "content": "export default { plugins: [] }"}]
  accepted, rejected = filter_locked_platform_writes(
    payload,
    files_before_map=before,
    intent="website_update",
  )
  assert accepted == []
  assert rejected[0]["path"] == "vite.config.js"


def test_guard_streaming_file_write_blocks_locked_path():
  blocked = guard_streaming_file_write(
    "index.html",
    "<html><head><title>New</title></head></html>",
    "<html><head><title>Old</title></head></html>",
    intent="website_update",
  )
  assert blocked is not None
  assert blocked.get("locked_platform_file") is True


def test_filter_streaming_write_payload_blocks_locked_before_rewrite_guard():
  before = {"tailwind.config.js": "module.exports = {}"}
  payload = [
    {"path": "tailwind.config.js", "content": "module.exports = { content: ['./src/**/*.{js,jsx}'] }"},
    {"path": "src/pages/About.jsx", "content": "export default function About() { return null; }"},
  ]
  accepted, rejected = filter_streaming_write_payload(before, payload, intent="website_update")
  assert len(rejected) == 1
  assert rejected[0]["path"] == "tailwind.config.js"
  assert len(accepted) == 1
  assert accepted[0]["path"] == "src/pages/About.jsx"
