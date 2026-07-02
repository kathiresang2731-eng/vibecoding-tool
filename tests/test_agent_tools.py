import pytest

from backend.agent_tools import ToolExecutionError, ToolRuntimeContext, execute_website_tool, website_tool_schemas
from backend.config import Settings
from backend.local_workspace import (
  LocalWorkspaceError,
  normalize_project_file_path,
  read_local_project_files,
  validate_complete_project_import,
  write_local_project_files,
)


def valid_generated_website():
  return {
    "title": "CRM Website",
    "headline": "Pipeline clarity for every team",
    "subheadline": "A practical CRM landing page.",
    "primary_cta": "Start trial",
    "secondary_cta": "View demo",
    "preview_html": "",
    "theme": {
      "colors": {
        "primary": "#000000",
        "secondary": "#7c3aed",
        "accent": "#111827",
        "background": "#ffffff",
        "text": "#111827",
      }
    },
    "sections": [
      {
        "name": "Hero",
        "purpose": "Introduce the CRM.",
        "content": "Clear hero content.",
        "items": ["Headline", "CTA"],
      }
    ],
    "files": [
      {
        "path": "src/App.jsx",
        "purpose": "Generated app.",
        "code": "export default function App() { return <main />; }",
      }
    ],
  }


def test_website_tool_schemas_are_openai_compatible_function_tools():
  schemas = website_tool_schemas()
  by_name = {schema["name"]: schema for schema in schemas}

  assert "READ_PROJECT_FILES" in by_name
  assert "LOAD_PROJECT_MEMORY" in by_name
  assert "PERSIST_PROJECT_MEMORY" in by_name
  assert "WRITE_PROJECT_FILES" in by_name
  assert "VALIDATE_PROJECT_ARTIFACT" in by_name
  assert "BUILD_STAGED_PROJECT_PREVIEW" in by_name
  assert "RUN_PREVIEW_VISUAL_QA" in by_name
  assert "BUILD_PROJECT_PREVIEW" in by_name
  assert "SYNC_LOCAL_PROJECT" in by_name
  assert all(schema["type"] == "function" for schema in schemas)
  assert by_name["WRITE_PROJECT_FILES"]["parameters"]["required"] == ["project_id", "files"]


def test_execute_validate_project_artifact_tool_returns_compact_result():
  result = execute_website_tool(
    "VALIDATE_PROJECT_ARTIFACT",
    ToolRuntimeContext(store=None, settings=None),
    type("User", (), {"id": "user-1"})(),
    {"generated_website": valid_generated_website()},
  )

  assert result == {
    "status": "valid",
    "title": "CRM Website",
    "section_count": 1,
    "file_count": 1,
    "paths": ["src/App.jsx"],
  }


def test_execute_validate_project_artifact_tool_rejects_unsafe_paths():
  artifact = valid_generated_website()
  artifact["files"][0]["path"] = "../secret.txt"

  with pytest.raises(ToolExecutionError, match="file path is not allowed"):
    execute_website_tool(
      "VALIDATE_PROJECT_ARTIFACT",
      ToolRuntimeContext(store=None, settings=None),
      type("User", (), {"id": "user-1"})(),
      {"generated_website": artifact},
    )


def test_write_project_files_rejects_empty_list_without_rollback_flag():
  class FakeStore:
    def replace_project_files(self, *args, **kwargs):
      raise AssertionError("replace_project_files should not be called")

  with pytest.raises(ToolExecutionError, match="allow_empty"):
    execute_website_tool(
      "WRITE_PROJECT_FILES",
      ToolRuntimeContext(store=FakeStore(), settings=None),
      type("User", (), {"id": "user-1"})(),
      {"project_id": "project-1", "files": []},
    )


def test_write_project_files_allows_empty_list_for_explicit_rollback():
  class FakeStore:
    def __init__(self):
      self.files = None

    def replace_project_files(self, project_id, user, files, **kwargs):
      self.files = files

    def get_project(self, project_id, user):
      return {"id": project_id, "local_path": None}

  store = FakeStore()
  result = execute_website_tool(
    "WRITE_PROJECT_FILES",
    ToolRuntimeContext(store=store, settings=None),
    type("User", (), {"id": "user-1"})(),
    {
      "project_id": "project-1",
      "files": [],
      "allow_empty": True,
      "mode": "replace_all",
      "allow_prune_missing": True,
      "reason": "rollback_restore",
    },
  )

  assert store.files == []
  assert result["file_count"] == 0


def test_persist_project_memory_tool_uses_store_upsert():
  class FakeStore:
    def __init__(self):
      self.memory = None

    def upsert_memory_item(self, user, **kwargs):
      self.memory = kwargs
      return {"id": "memory-1", **kwargs}

  store = FakeStore()
  result = execute_website_tool(
    "PERSIST_PROJECT_MEMORY",
    ToolRuntimeContext(store=store, settings=None),
    type("User", (), {"id": "user-1"})(),
    {
      "project_id": "project-1",
      "namespace": "agent",
      "key": "latest_generation_summary",
      "kind": "generation_summary",
      "content": "Generated CRM website.",
    },
  )

  assert result["status"] == "persisted"
  assert result["memory_id"] == "memory-1"
  assert store.memory["key"] == "latest_generation_summary"
  assert store.memory["content"] == "Generated CRM website."


def test_preview_visual_qa_tool_allows_skipped_browser_render():
  result = execute_website_tool(
    "RUN_PREVIEW_VISUAL_QA",
    ToolRuntimeContext(store=None, settings=None),
    type("User", (), {"id": "user-1"})(),
    {
      "project_id": "project-1",
      "status": "ready",
      "preview_url": "/api/previews/project-1/v1/",
      "build_log": "built in 800ms",
    },
  )

  assert result["status"] == "passed"
  assert result["browser_rendered"] is False
  assert result["browser"]["status"] == "skipped"
  assert any(check["name"] == "browser_render_nonblocking" for check in result["checks"])


def test_preview_visual_qa_tool_allows_failed_browser_render(tmp_path):
  browser_path = tmp_path / "failing-browser"
  browser_path.write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
  browser_path.chmod(0o755)
  settings = Settings(
    database_url="postgres://example",
    frontend_origins=[],
    dev_user_email="dev@example.com",
    gemini_api_key="",
    gemini_model="gemini-test",
    app_root=tmp_path,
    local_workspace_roots=[tmp_path],
    backend_public_base_url="http://localhost:8787",
    visual_qa_browser_command=str(browser_path),
  )

  result = execute_website_tool(
    "RUN_PREVIEW_VISUAL_QA",
    ToolRuntimeContext(store=None, settings=settings),
    type("User", (), {"id": "user-1"})(),
    {
      "project_id": "project-1",
      "status": "ready",
      "preview_url": "/api/previews/project-1/v1/",
      "build_log": "built in 800ms",
    },
  )

  assert result["status"] == "passed"
  assert result["browser_rendered"] is False
  assert result["browser"]["status"] == "failed"
  assert "Browser-render QA did not pass" in result["warnings"][0]


def test_preview_visual_qa_tool_rejects_browser_runtime_errors(monkeypatch):
  def fake_browser_qa(**kwargs):
    return {
      "project_id": kwargs["project_id"],
      "status": "failed",
      "failure_kind": "runtime_error",
      "browser_rendered": False,
      "checks": [{"name": "browser_runtime_errors", "status": "failed", "detail": "React is not defined"}],
      "warnings": ["Uncaught ReferenceError: React is not defined"],
    }

  monkeypatch.setattr("backend.agent_tools.run_browser_preview_qa", fake_browser_qa)

  with pytest.raises(ToolExecutionError, match="Preview runtime QA failed"):
    execute_website_tool(
      "RUN_PREVIEW_VISUAL_QA",
      ToolRuntimeContext(store=None, settings=None),
      type("User", (), {"id": "user-1"})(),
      {
        "project_id": "project-1",
        "status": "ready",
        "preview_url": "/api/previews/project-1/v1/",
        "build_log": "built in 800ms",
      },
    )


def test_preview_visual_qa_tool_returns_structured_layout_failure(monkeypatch):
  def fake_browser_qa(**kwargs):
    return {
      "project_id": kwargs["project_id"],
      "status": "failed",
      "mode": "browser_rendered_preview",
      "browser_rendered": True,
      "checks": [{"name": "layout_probe", "status": "failed", "detail": "1 viewport failed"}],
      "warnings": [],
      "layout_checked": True,
      "viewport_results": [
        {
          "name": "mobile",
          "width": 390,
          "height": 844,
          "status": "failed",
          "severity": "high",
          "issues": [{"type": "overlap", "severity": "high"}],
        }
      ],
      "layout_issues": [{"type": "overlap", "severity": "high", "viewport": "mobile"}],
      "severity": "high",
    }

  monkeypatch.setattr("backend.agent_tools.run_browser_preview_qa", fake_browser_qa)

  result = execute_website_tool(
    "RUN_PREVIEW_VISUAL_QA",
    ToolRuntimeContext(store=None, settings=None),
    type("User", (), {"id": "user-1"})(),
    {
      "project_id": "project-1",
      "status": "ready",
      "preview_url": "/api/previews/project-1/v1/",
      "build_log": "built in 800ms",
    },
  )

  assert result["status"] == "failed"
  assert result["mode"] == "layout_qa_failed"
  assert result["layout_checked"] is True
  assert result["severity"] == "high"
  assert result["layout_issues"][0]["type"] == "overlap"


def test_preview_visual_qa_tool_rejects_failed_preview_status():
  with pytest.raises(ToolExecutionError, match="ready staged preview"):
    execute_website_tool(
      "RUN_PREVIEW_VISUAL_QA",
      ToolRuntimeContext(store=None, settings=None),
      type("User", (), {"id": "user-1"})(),
      {"project_id": "project-1", "status": "failed", "build_log": "Syntax error"},
    )


def test_read_project_files_pulls_linked_local_workspace_before_agent_updates(tmp_path):
  local_root = tmp_path / "existing-site"
  (local_root / "src" / "components").mkdir(parents=True)
  (local_root / "src" / "data").mkdir(parents=True)
  (local_root / "index.html").write_text("<div id=\"root\"></div>", encoding="utf-8")
  (local_root / "package.json").write_text('{"scripts":{"build":"vite"}}', encoding="utf-8")
  (local_root / "package-lock.json").write_text('{"lockfileVersion":3}', encoding="utf-8")
  (local_root / "tsconfig.json").write_text('{"compilerOptions":{}}', encoding="utf-8")
  (local_root / "jsconfig.json").write_text('{"compilerOptions":{}}', encoding="utf-8")
  (local_root / "tailwind.config.cjs").write_text("module.exports = {}", encoding="utf-8")
  (local_root / "postcss.config.cjs").write_text("module.exports = {}", encoding="utf-8")
  (local_root / "src" / "data" / "settings.json").write_text('{"theme":"local"}', encoding="utf-8")
  (local_root / "src" / "App.jsx").write_text(
    "export default function App() { return <main>local current code</main>; }",
    encoding="utf-8",
  )
  (local_root / "src" / "components" / "Header.jsx").write_text(
    "export function Header() { return <header>Imported site</header>; }",
    encoding="utf-8",
  )

  class FakeStore:
    def __init__(self):
      self.replaced_files = None
      self.event_payload = None

    def get_project(self, project_id, user):
      return {"id": project_id, "local_path": str(local_root)}

    def replace_project_files(self, project_id, user, files, **kwargs):
      self.replaced_files = files
      self.event_payload = kwargs

    def list_files(self, project_id, user):
      raise AssertionError("linked local reads should refresh from disk instead of stale DB files")

  settings = Settings(
    database_url="postgres://example",
    frontend_origins=[],
    dev_user_email="dev@example.com",
    gemini_api_key="",
    gemini_model="gemini-test",
    app_root=tmp_path,
    local_workspace_roots=[tmp_path],
  )
  store = FakeStore()

  result = execute_website_tool(
    "READ_PROJECT_FILES",
    ToolRuntimeContext(store=store, settings=settings),
    type("User", (), {"id": "user-1"})(),
    {"project_id": "project-1"},
  )

  by_path = {file_item["path"]: file_item["content"] for file_item in result["files"]}
  assert by_path["index.html"] == "<div id=\"root\"></div>"
  assert by_path["package.json"] == '{"scripts":{"build":"vite"}}'
  assert by_path["package-lock.json"] == '{"lockfileVersion":3}'
  assert by_path["tsconfig.json"] == '{"compilerOptions":{}}'
  assert by_path["jsconfig.json"] == '{"compilerOptions":{}}'
  assert by_path["tailwind.config.cjs"] == "module.exports = {}"
  assert by_path["postcss.config.cjs"] == "module.exports = {}"
  assert by_path["src/data/settings.json"] == '{"theme":"local"}'
  assert by_path["src/App.jsx"] == "export default function App() { return <main>local current code</main>; }"
  assert by_path["src/components/Header.jsx"] == "export function Header() { return <header>Imported site</header>; }"
  assert result["local_sync"]["direction"] == "pull"
  assert result["local_sync"]["file_count"] == 10
  assert store.replaced_files == result["files"]
  assert store.event_payload["event_type"] == "local.pulled"
  assert store.event_payload["event_payload"]["source"] == "read_project_files"


def test_write_project_files_pushes_agent_updates_to_linked_local_workspace(tmp_path):
  local_root = tmp_path / "linked-site"
  local_root.mkdir()
  (local_root / "src").mkdir()
  (local_root / "src" / "Old.jsx").write_text("export function Old() { return null; }", encoding="utf-8")
  (local_root / ".env").write_text("SECRET=kept", encoding="utf-8")

  class FakeStore:
    def __init__(self):
      self.upserted_files = None
      self.events = []

    def upsert_project_files(self, project_id, user, files, **kwargs):
      self.upserted_files = files
      return len(files)

    def get_project(self, project_id, user):
      return {"id": project_id, "local_path": str(local_root)}

    def add_event(self, project_id, user_id, event_type, payload):
      self.events.append({"type": event_type, "payload": payload})

  settings = Settings(
    database_url="postgres://example",
    frontend_origins=[],
    dev_user_email="dev@example.com",
    gemini_api_key="",
    gemini_model="gemini-test",
    app_root=tmp_path,
    local_workspace_roots=[tmp_path],
  )
  files = [
    {"path": "index.html", "content": '<div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "package.json", "content": '{"scripts":{"build":"vite"}}'},
    {"path": "tsconfig.json", "content": '{"compilerOptions":{"jsx":"react-jsx"}}'},
    {"path": "src/App.jsx", "content": "export default function App() { return <main>updated local code</main>; }"},
  ]
  store = FakeStore()

  result = execute_website_tool(
    "WRITE_PROJECT_FILES",
    ToolRuntimeContext(store=store, settings=settings),
    type("User", (), {"id": "user-1"})(),
    {"project_id": "project-1", "files": files},
  )

  assert store.upserted_files == files
  assert result["local_sync"]["direction"] == "push"
  assert result["mode"] == "upsert"
  assert result["local_sync"]["count"] == 4
  assert (local_root / "index.html").read_text(encoding="utf-8") == files[0]["content"]
  assert (local_root / "package.json").read_text(encoding="utf-8") == files[1]["content"]
  assert (local_root / "tsconfig.json").read_text(encoding="utf-8") == files[2]["content"]
  assert (local_root / "src" / "App.jsx").read_text(encoding="utf-8") == files[3]["content"]
  assert (local_root / "src" / "Old.jsx").exists()
  assert (local_root / ".env").read_text(encoding="utf-8") == "SECRET=kept"
  assert store.events == [{"type": "local.files.written", "payload": {"path": str(local_root), "count": 4, "mode": "upsert"}}]


def test_write_project_files_does_not_update_store_when_linked_local_sync_fails(tmp_path):
  outside_root = tmp_path.parent / "outside-linked-site"

  class FakeStore:
    def __init__(self):
      self.replaced_files = None
      self.events = []

    def replace_project_files(self, project_id, user, files, **kwargs):
      self.replaced_files = files

    def get_project(self, project_id, user):
      return {"id": project_id, "local_path": str(outside_root)}

    def add_event(self, project_id, user_id, event_type, payload):
      self.events.append({"type": event_type, "payload": payload})

  settings = Settings(
    database_url="postgres://example",
    frontend_origins=[],
    dev_user_email="dev@example.com",
    gemini_api_key="",
    gemini_model="gemini-test",
    app_root=tmp_path,
    local_workspace_roots=[tmp_path],
  )
  store = FakeStore()

  with pytest.raises(ToolExecutionError, match="outside the allowed workspace roots"):
    execute_website_tool(
      "WRITE_PROJECT_FILES",
      ToolRuntimeContext(store=store, settings=settings),
      type("User", (), {"id": "user-1"})(),
      {
        "project_id": "project-1",
        "files": [
          {"path": "index.html", "content": '<div id="root"></div>'},
          {"path": "src/App.jsx", "content": "export default function App() { return <main />; }"},
        ],
      },
    )

  assert store.replaced_files is None
  assert store.events == []


def test_complete_project_import_allows_static_root_project_before_replace():
  files = [
    {"path": "index.html", "content": '<link rel="stylesheet" href="./style.css"><script src="./script.js"></script>'},
    {"path": "style.css", "content": "body { margin: 0; }"},
    {"path": "script.js", "content": "console.log('static site');"},
  ]

  validate_complete_project_import(files, source_label="Browser directory import")


def test_complete_project_import_rejects_folder_without_index_entry():
  files = [
    {"path": "script.js", "content": "console.log('no entry');"},
    {"path": "style.css", "content": "body { margin: 0; }"},
  ]

  with pytest.raises(LocalWorkspaceError, match="static website folder containing index.html"):
    validate_complete_project_import(files, source_label="Local workspace pull")


def test_browser_directory_import_allows_partial_files_without_index_entry():
  files = [
    {"path": "script.js", "content": "console.log('no entry');"},
    {"path": "style.css", "content": "body { margin: 0; }"},
  ]

  validate_complete_project_import(
    files,
    source_label="Browser directory import",
    require_complete=False,
  )


def test_read_local_project_files_keeps_full_safe_project_tree(tmp_path):
  local_root = tmp_path / "site"
  (local_root / "src" / "components").mkdir(parents=True)
  (local_root / "docs").mkdir(parents=True)
  (local_root / "index.html").write_text("<div id=\"root\"></div>", encoding="utf-8")
  (local_root / "package.json").write_text('{"scripts":{"build":"vite"}}', encoding="utf-8")
  (local_root / "postcss.config.js").write_text("export default {};", encoding="utf-8")
  (local_root / "src" / "App.jsx").write_text("export default function App() { return <main />; }", encoding="utf-8")
  (local_root / "src" / "components" / "Card.jsx").write_text("export function Card() { return null; }", encoding="utf-8")
  (local_root / "docs" / "readme.md").write_text("# Project notes", encoding="utf-8")
  (local_root / "node_modules" / "pkg").mkdir(parents=True)
  (local_root / "node_modules" / "pkg" / "index.js").write_text("ignored", encoding="utf-8")

  files = read_local_project_files(local_root)
  paths = {file_item["path"] for file_item in files}

  assert {
    "index.html",
    "package.json",
    "postcss.config.js",
    "src/App.jsx",
    "src/components/Card.jsx",
    "docs/readme.md",
  }.issubset(paths)
  assert "node_modules/pkg/index.js" not in paths


def test_project_file_path_normalizer_allows_safe_tree_and_rejects_private_files():
  assert normalize_project_file_path("src/components/App.jsx") == "src/components/App.jsx"
  assert normalize_project_file_path("./docs/readme.md") == "docs/readme.md"

  with pytest.raises(LocalWorkspaceError, match="inside an ignored folder"):
    normalize_project_file_path("node_modules/react/index.js")
  with pytest.raises(LocalWorkspaceError, match="Project file is ignored"):
    normalize_project_file_path(".env")
  with pytest.raises(LocalWorkspaceError, match="not allowed"):
    normalize_project_file_path("../package.json")


def test_local_workspace_binary_project_assets_round_trip_as_data_urls(tmp_path):
  local_root = tmp_path / "site"
  (local_root / "src" / "assets").mkdir(parents=True)
  (local_root / "index.html").write_text("<div id=\"root\"></div>", encoding="utf-8")
  (local_root / "package.json").write_text('{"scripts":{"build":"vite"}}', encoding="utf-8")
  (local_root / "src" / "App.jsx").write_text("export default function App() { return <main />; }", encoding="utf-8")
  binary_content = b"\x89PNG\r\n\x1a\n\x00\x00"
  (local_root / "src" / "assets" / "logo.png").write_bytes(binary_content)

  files = read_local_project_files(local_root)
  by_path = {file_item["path"]: file_item["content"] for file_item in files}

  assert by_path["src/assets/logo.png"].startswith("data:image/png;base64,")
  output_root = tmp_path / "output"
  write_local_project_files(output_root, files)
  assert (output_root / "src" / "assets" / "logo.png").read_bytes() == binary_content


def test_write_local_project_files_can_prune_stale_supported_files_on_full_sync(tmp_path):
  local_root = tmp_path / "site"
  (local_root / "src" / "legacy").mkdir(parents=True)
  (local_root / "node_modules" / "pkg").mkdir(parents=True)
  (local_root / "src" / "legacy" / "Old.jsx").write_text("export function Old() { return null; }", encoding="utf-8")
  (local_root / "docs.md").write_text("# stale", encoding="utf-8")
  (local_root / ".env").write_text("SECRET=kept", encoding="utf-8")
  (local_root / "node_modules" / "pkg" / "index.js").write_text("ignored", encoding="utf-8")

  count = write_local_project_files(
    local_root,
    [
      {"path": "index.html", "content": "<div id=\"root\"></div>"},
      {"path": "package.json", "content": "{\"scripts\":{\"build\":\"vite\"}}"},
      {"path": "src/App.jsx", "content": "export default function App() { return <main />; }"},
    ],
    prune_missing=True,
    allow_prune_missing=True,
  )

  assert count == 3
  assert (local_root / "src" / "App.jsx").exists()
  assert not (local_root / "src" / "legacy" / "Old.jsx").exists()
  assert not (local_root / "docs.md").exists()
  assert (local_root / ".env").read_text(encoding="utf-8") == "SECRET=kept"
  assert (local_root / "node_modules" / "pkg" / "index.js").read_text(encoding="utf-8") == "ignored"


def test_write_local_project_files_blocks_prune_without_explicit_approval(tmp_path):
  local_root = tmp_path / "site"
  (local_root / "src").mkdir(parents=True)
  (local_root / "src" / "Old.jsx").write_text("export function Old() { return null; }", encoding="utf-8")

  with pytest.raises(LocalWorkspaceError, match="allow_prune_missing"):
    write_local_project_files(
      local_root,
      [{"path": "src/App.jsx", "content": "export default function App() { return null; }"}],
      prune_missing=True,
    )

  assert (local_root / "src" / "Old.jsx").exists()


def test_write_local_project_files_rolls_back_partial_batch_on_error(tmp_path):
  local_root = tmp_path / "site"
  (local_root / "src").mkdir(parents=True)
  app_path = local_root / "src" / "App.jsx"
  app_path.write_text("export default function App() { return <main>old</main>; }", encoding="utf-8")

  with pytest.raises(LocalWorkspaceError):
    write_local_project_files(
      local_root,
      [
        {"path": "src/App.jsx", "content": "export default function App() { return <main>new</main>; }"},
        {"path": "../outside.jsx", "content": "export default function Outside() { return null; }"},
      ],
    )

  assert app_path.read_text(encoding="utf-8") == "export default function App() { return <main>old</main>; }"


def test_write_local_project_files_default_incremental_write_preserves_other_files(tmp_path):
  local_root = tmp_path / "site"
  (local_root / "src").mkdir(parents=True)
  (local_root / "src" / "Keep.jsx").write_text("export function Keep() { return null; }", encoding="utf-8")

  write_local_project_files(
    local_root,
    [{"path": "src/App.jsx", "content": "export default function App() { return <main />; }"}],
  )

  assert (local_root / "src" / "App.jsx").exists()
  assert (local_root / "src" / "Keep.jsx").exists()


def test_read_project_files_keeps_backend_snapshot_when_no_local_workspace():
  stored_files = [{"path": "src/App.jsx", "content": "export default function App() { return <main />; }"}]

  class FakeStore:
    def get_project(self, project_id, user):
      return {"id": project_id, "local_path": None}

    def list_files(self, project_id, user):
      return stored_files

    def replace_project_files(self, *args, **kwargs):
      raise AssertionError("backend-only reads should not rewrite project files")

  result = execute_website_tool(
    "READ_PROJECT_FILES",
    ToolRuntimeContext(store=FakeStore(), settings=None),
    type("User", (), {"id": "user-1"})(),
    {"project_id": "project-1"},
  )

  assert result["files"] == stored_files
  assert result["file_count"] == 1
  assert result["local_sync"] is None
