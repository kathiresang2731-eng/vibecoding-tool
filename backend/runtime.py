from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

try:
  from .config import Settings
  from .local_workspace import LocalWorkspaceError, resolve_local_project_path, write_local_project_files, write_project_file_content
  from .storage import PostgresStore, UserContext, new_id
except ImportError:
  from config import Settings
  from local_workspace import LocalWorkspaceError, resolve_local_project_path, write_local_project_files, write_project_file_content
  from storage import PostgresStore, UserContext, new_id


BUILD_TIMEOUT_SECONDS = 45
SOURCE_IMPORT_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx")
PREVIEW_CONTENT_TYPES = {
  ".css": "text/css",
  ".html": "text/html",
  ".js": "text/javascript",
  ".mjs": "text/javascript",
  ".svg": "image/svg+xml",
}


class PreviewRuntimeError(RuntimeError):
  pass


BARE_IMPORT_RE = re.compile(
  r"""(?:import\s+(?:[^'"]+\s+from\s+)?|export\s+[^'"]+\s+from\s+|import\s*\(|require\s*\()\s*['"]([^'"]+)['"]""",
  re.MULTILINE,
)


def normalize_preview_runtime_files(files: list[dict[str, Any]], *, title: str = "Generated Website") -> list[dict[str, Any]]:
  try:
    from .agents.agent_runtime.scaffolding import ensure_tailwind_runtime_files, ensure_vite_scaffold_files, normalize_frontend_runtime_imports
  except ImportError:
    from agents.agent_runtime.scaffolding import ensure_tailwind_runtime_files, ensure_vite_scaffold_files, normalize_frontend_runtime_imports

  scaffolded_files, _ = ensure_vite_scaffold_files(files, title=title)
  runtime_files, _ = normalize_frontend_runtime_imports(scaffolded_files)
  tailwind_files, _ = ensure_tailwind_runtime_files(runtime_files)
  return prepare_preview_files(tailwind_files)


def persist_preview_runtime_fixes(
  store: PostgresStore,
  project_id: str,
  user: UserContext,
  files: list[dict[str, Any]],
  normalized_files: list[dict[str, Any]],
) -> None:
  if not hasattr(store, "upsert_file"):
    return
  originals = {
    str(item.get("path") or ""): str(item.get("content") or "")
    for item in files
    if isinstance(item, dict) and item.get("path")
  }
  for file_item in normalized_files:
    path = str(file_item.get("path") or "")
    content = str(file_item.get("content") or "")
    if not path or originals.get(path) == content:
      continue
    store.upsert_file(project_id, user, path=path, content=content, emit_event=False)


def build_project_preview(store: PostgresStore, project_id: str, user: UserContext, settings: Settings) -> dict[str, Any]:
  app_root = settings.app_root
  project = store.get_project(project_id, user)
  if not project:
    raise PreviewRuntimeError("Project not found.")

  files = store.list_files(project_id, user)
  if not files:
    raise PreviewRuntimeError("Project has no files to build.")

  local_path = project.get("local_path")
  if isinstance(local_path, str) and local_path.strip():
    return build_linked_local_preview(store, project, files, user, settings)

  normalized_files = normalize_preview_runtime_files(files, title=str(project.get("name") or "Generated Website"))
  persist_preview_runtime_fixes(store, project_id, user, files, normalized_files)
  validate_preview_dependency_imports(app_root, normalized_files)
  version_workspace = prepare_workspace(app_root, project_id)
  write_project_files(version_workspace, normalized_files)
  build_log, status = run_vite_build(app_root, version_workspace)
  version_id = new_id()
  preview_url = None
  if status == "ready":
    preview_url = f"/api/previews/{project_id}/{version_id}/"
  version = store.create_version(
    project_id,
    user,
    version_id=version_id,
    status=status,
    preview_url=preview_url,
    build_log=build_log,
    files=[{"path": file_item["path"], "content": file_item["content"]} for file_item in normalized_files],
  )

  final_workspace = runtime_project_path(app_root, project_id, version["id"])
  if final_workspace.exists():
    shutil.rmtree(final_workspace)
  version_workspace.rename(final_workspace)

  return version


def build_staged_project_preview(
  store: PostgresStore,
  project_id: str,
  user: UserContext,
  settings: Settings,
  files: list[dict[str, Any]],
) -> dict[str, Any]:
  project = store.get_project(project_id, user)
  if not project:
    raise PreviewRuntimeError("Project not found.")
  if not files:
    raise PreviewRuntimeError("Staged project has no files to build.")

  normalized_files = normalize_preview_runtime_files(files, title=str(project.get("name") or "Generated Website"))
  local_path = project.get("local_path")
  if isinstance(local_path, str) and local_path.strip():
    return build_staged_linked_local_preview(store, project, user, settings, normalized_files)

  validate_preview_dependency_imports(settings.app_root, normalized_files)
  version_workspace = prepare_workspace(settings.app_root, project_id)
  write_project_files(version_workspace, normalized_files)
  build_log, status = run_vite_build(settings.app_root, version_workspace)
  build_log = f"Building staged candidate files before project commit.\n\n{build_log}".strip()
  version_id = new_id()
  preview_url = f"/api/previews/{project_id}/{version_id}/" if status == "ready" else None
  version = store.create_version(
    project_id,
    user,
    version_id=version_id,
    status=status,
    preview_url=preview_url,
    build_log=build_log,
    files=[{"path": file_item["path"], "content": file_item["content"]} for file_item in normalized_files],
  )

  final_workspace = runtime_project_path(settings.app_root, project_id, version["id"])
  if final_workspace.exists():
    shutil.rmtree(final_workspace)
  version_workspace.rename(final_workspace)

  return version


def build_staged_linked_local_preview(
  store: PostgresStore,
  project: dict[str, Any],
  user: UserContext,
  settings: Settings,
  files: list[dict[str, Any]],
) -> dict[str, Any]:
  try:
    local_root = resolve_local_project_path(settings, str(project.get("local_path") or ""))
    validate_preview_dependency_imports(local_root, files)
  except LocalWorkspaceError as exc:
    raise PreviewRuntimeError(str(exc)) from exc

  staging_workspace = local_root / ".worktual-staging"
  if staging_workspace.exists():
    shutil.rmtree(staging_workspace)
  staging_workspace.mkdir(parents=True)

  try:
    write_project_files(staging_workspace, files)
    build_log, status = run_vite_build(settings.app_root, staging_workspace)
    build_log = f"Building staged candidate files in linked local folder: {staging_workspace}\n\n{build_log}".strip()
    version_id = new_id()
    preview_url = f"/api/previews/{project['id']}/{version_id}/" if status == "ready" else None
    version = store.create_version(
      project["id"],
      user,
      version_id=version_id,
      status=status,
      preview_url=preview_url,
      build_log=build_log,
      files=[{"path": file_item["path"], "content": file_item["content"]} for file_item in files],
    )

    if status == "ready":
      publish_local_preview_dist(settings.app_root, project["id"], version["id"], staging_workspace)
    return version
  finally:
    if staging_workspace.exists():
      shutil.rmtree(staging_workspace)


def build_linked_local_preview(
  store: PostgresStore,
  project: dict[str, Any],
  files: list[dict[str, Any]],
  user: UserContext,
  settings: Settings,
) -> dict[str, Any]:
  try:
    local_root = resolve_local_project_path(settings, str(project.get("local_path") or ""))
    normalized_files = normalize_preview_runtime_files(files, title=str(project.get("name") or "Generated Website"))
    persist_preview_runtime_fixes(store, project["id"], user, files, normalized_files)
    validate_preview_dependency_imports(local_root, normalized_files)
    write_local_project_files(local_root, normalized_files, prune_missing=False)
  except LocalWorkspaceError as exc:
    raise PreviewRuntimeError(str(exc)) from exc

  build_log, status = run_vite_build(settings.app_root, local_root)
  build_log = f"Building in linked local folder: {local_root}\n\n{build_log}".strip()
  version_id = new_id()
  preview_url = f"/api/previews/{project['id']}/{version_id}/" if status == "ready" else None
  version = store.create_version(
    project["id"],
    user,
    version_id=version_id,
    status=status,
    preview_url=preview_url,
    build_log=build_log,
    files=[{"path": file_item["path"], "content": file_item["content"]} for file_item in normalized_files],
  )

  if status == "ready":
    publish_local_preview_dist(settings.app_root, project["id"], version["id"], local_root)

  return version


def publish_local_preview_dist(app_root: Path, project_id: str, version_id: str, local_root: Path) -> None:
  dist_root = local_root / "dist"
  if not dist_root.exists():
    raise PreviewRuntimeError("Local preview build finished but did not create a dist folder.")

  final_workspace = runtime_project_path(app_root, project_id, version_id)
  if final_workspace.exists():
    shutil.rmtree(final_workspace)
  final_workspace.mkdir(parents=True)
  shutil.copytree(dist_root, final_workspace / "dist")


def prepare_workspace(app_root: Path, project_id: str) -> Path:
  runtime_root = app_root / ".runtime" / "projects" / project_id
  runtime_root.mkdir(parents=True, exist_ok=True)
  workspace = runtime_root / "pending"
  if workspace.exists():
    shutil.rmtree(workspace)
  workspace.mkdir(parents=True)
  return workspace


def runtime_project_path(app_root: Path, project_id: str, version_id: str) -> Path:
  return app_root / ".runtime" / "projects" / project_id / version_id


def delete_project_runtime(app_root: Path, project_id: str) -> None:
  runtime_root = app_root / ".runtime" / "projects"
  project_root = (runtime_root / project_id).resolve(strict=False)
  runtime_root = runtime_root.resolve(strict=False)
  if runtime_root not in project_root.parents:
    raise PreviewRuntimeError(f"Unsafe runtime project path: {project_id}")
  if project_root.exists():
    shutil.rmtree(project_root)


def write_project_files(workspace: Path, files: list[dict[str, Any]]) -> None:
  normalized_files = prepare_preview_files(files)
  for file_item in normalized_files:
    destination = safe_join(workspace, file_item["path"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_project_file_content(destination, file_item["path"], file_item["content"])


def prepare_preview_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
  package_file = next((file_item for file_item in files if file_item.get("path") == "package.json"), None)
  package_type = package_json_type(package_file.get("content", "") if package_file else "")
  normalized = []
  for file_item in files:
    path = file_item["path"]
    content = file_item["content"]
    if package_type == "module" and path in {"postcss.config.js", "tailwind.config.js"}:
      content = commonjs_config_to_esm(content)
    normalized.append({"path": path, "content": content})
  return normalized


def validate_preview_dependency_imports(app_root: Path, files: list[dict[str, Any]]) -> None:
  node_modules_root = app_root / "node_modules"
  if not node_modules_root.exists():
    return

  declared_dependencies = preview_declared_dependencies(files)
  missing: list[dict[str, str]] = []
  unsupported_runtime_imports: list[dict[str, str]] = []
  for file_item in files:
    path = str(file_item.get("path") or "")
    if not should_scan_preview_imports(path):
      continue
    content = str(file_item.get("content") or "")
    for specifier in extract_bare_import_specifiers(content):
      package_name = bare_package_name(specifier)
      if not package_name:
        continue
      if package_name in builtin_browser_ignored_imports():
        continue
      if package_name not in declared_dependencies:
        unsupported_runtime_imports.append({"path": path, "import": specifier, "package": package_name})
        continue
      if not preview_package_installed(node_modules_root, package_name):
        missing.append({"path": path, "import": specifier, "package": package_name})

  if unsupported_runtime_imports or missing:
    issue_parts: list[str] = []
    if unsupported_runtime_imports:
      formatted = ", ".join(f'{item["import"]} in {item["path"]}' for item in unsupported_runtime_imports[:6])
      issue_parts.append(f"undeclared imports: {formatted}")
    if missing:
      formatted = ", ".join(f'{item["package"]} required by {item["path"]}' for item in missing[:6])
      issue_parts.append(f"dependencies not installed in preview runtime: {formatted}")
    raise PreviewRuntimeError(
      "Preview dependency preflight failed before Vite build: "
      + "; ".join(issue_parts)
      + ". Use existing installed packages, platform shims, or update the generated code before commit."
    )


def should_scan_preview_imports(path: str) -> bool:
  if not path.endswith(SOURCE_IMPORT_EXTENSIONS):
    return False
  if path.endswith((".config.js", ".config.ts")):
    return False
  if path.startswith("src/worktual-"):
    return False
  return path.startswith("src/") or "/" not in path


def preview_declared_dependencies(files: list[dict[str, Any]]) -> set[str]:
  dependencies = {
    "react",
    "react-dom",
    "lucide-react",
  }
  package_file = next((file_item for file_item in files if file_item.get("path") == "package.json"), None)
  if not package_file:
    return dependencies
  try:
    package_data = json.loads(str(package_file.get("content") or ""))
  except json.JSONDecodeError:
    return dependencies
  for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
    section = package_data.get(key)
    if not isinstance(section, dict):
      continue
    for package_name in section:
      if isinstance(package_name, str) and package_name.strip():
        dependencies.add(package_name.strip())
  return dependencies


def extract_bare_import_specifiers(content: str) -> list[str]:
  specifiers: list[str] = []
  for match in BARE_IMPORT_RE.finditer(content):
    specifier = match.group(1).strip()
    if is_bare_import_specifier(specifier):
      specifiers.append(specifier)
  return specifiers


def is_bare_import_specifier(specifier: str) -> bool:
  if not specifier:
    return False
  return not (
    specifier.startswith(".")
    or specifier.startswith("/")
    or specifier.startswith("#")
    or specifier.startswith("http:")
    or specifier.startswith("https:")
  )


def bare_package_name(specifier: str) -> str:
  parts = specifier.split("/")
  if not parts:
    return ""
  if specifier.startswith("@") and len(parts) >= 2:
    return "/".join(parts[:2])
  return parts[0]


def preview_package_installed(node_modules_root: Path, package_name: str) -> bool:
  return (node_modules_root / package_name).exists()


def builtin_browser_ignored_imports() -> set[str]:
  return {"vite/client"}


def package_json_type(content: str) -> str:
  try:
    package_data = json.loads(content)
  except json.JSONDecodeError:
    return ""
  package_type = package_data.get("type")
  return package_type.strip() if isinstance(package_type, str) else ""


def commonjs_config_to_esm(content: str) -> str:
  stripped = content.lstrip()
  leading = content[: len(content) - len(stripped)]
  if stripped.startswith("module.exports"):
    remainder = stripped.removeprefix("module.exports").lstrip()
    if remainder.startswith("="):
      remainder = remainder[1:].lstrip()
    return f"{leading}export default {remainder}"
  return content


def run_vite_build(app_root: Path, workspace: Path) -> tuple[str, str]:
  node_modules_roots = preview_node_modules_roots(app_root, workspace)
  vite_bin = next((root / "vite" / "bin" / "vite.js" for root in node_modules_roots if (root / "vite" / "bin" / "vite.js").exists()), None)
  if vite_bin is None:
    return "Vite is not installed in node_modules. Run npm install first.", "failed"
  node_binary = resolve_node_binary()
  if not node_binary:
    return "Node.js was not found. Configure NODE_BINARY or install Node.js.", "failed"

  cleanup_node_modules = link_workspace_node_modules(app_root, workspace)
  try:
    completed = subprocess.run(
      [node_binary, str(vite_bin), "build", "--base", "./"],
      cwd=workspace,
      env={**os.environ, "NODE_PATH": os.pathsep.join(str(root) for root in node_modules_roots if root.exists())},
      text=True,
      capture_output=True,
      timeout=BUILD_TIMEOUT_SECONDS,
      check=False,
    )
  except subprocess.TimeoutExpired as exc:
    output = (exc.stdout or "") + "\n" + (exc.stderr or "")
    return f"Build timed out after {BUILD_TIMEOUT_SECONDS}s.\n{output}".strip(), "failed"
  finally:
    cleanup_node_modules()

  build_log = "\n".join(part for part in [completed.stdout, completed.stderr] if part).strip()
  if completed.returncode != 0:
    return build_log or "Build failed.", "failed"

  runtime_issues = scan_built_preview_runtime(workspace / "dist")
  if runtime_issues:
    issue_log = "\n".join(runtime_issues)
    return f"{build_log or 'Build completed.'}\n\nPreview runtime scan failed:\n{issue_log}", "failed"
  return build_log or "Build completed.", "ready"


def preview_node_modules_roots(app_root: Path, workspace: Path) -> list[Path]:
  roots = [workspace / "node_modules"]
  if workspace.name == ".worktual-staging":
    roots.append(workspace.parent / "node_modules")
  roots.append(app_root / "node_modules")

  deduped: list[Path] = []
  seen: set[str] = set()
  for root in roots:
    key = str(root)
    if key not in seen:
      deduped.append(root)
      seen.add(key)
  return deduped


def resolve_node_binary() -> str:
  configured = os.getenv("VITE_NODE_BINARY") or os.getenv("NODE_BINARY")
  candidates = [
    configured,
    "/opt/homebrew/bin/node",
    "/usr/local/bin/node",
    shutil.which("node"),
    "/Applications/Codex.app/Contents/Resources/node",
  ]
  for candidate in candidates:
    if not isinstance(candidate, str) or not candidate.strip():
      continue
    path = Path(candidate)
    if path.exists() and os.access(path, os.X_OK):
      return str(path)
  return ""


def scan_built_preview_runtime(dist_root: Path) -> list[str]:
  if not dist_root.exists():
    return ["Preview build completed but dist output was not found."]

  issues: list[str] = []
  for bundle_path in sorted(dist_root.glob("assets/*.js")):
    try:
      bundle_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
      issues.append(f"Could not inspect built JS bundle {bundle_path.name}: {exc}")
  return issues


def link_workspace_node_modules(app_root: Path, workspace: Path):
  root_node_modules = app_root / "node_modules"
  workspace_node_modules = workspace / "node_modules"
  if workspace.name == ".worktual-staging" and (workspace.parent / "node_modules").exists():
    return lambda: None
  if workspace_node_modules.exists() or workspace_node_modules.is_symlink() or not root_node_modules.exists():
    return lambda: None

  try:
    workspace_node_modules.symlink_to(root_node_modules, target_is_directory=True)
  except OSError:
    return lambda: None

  def cleanup() -> None:
    try:
      if workspace_node_modules.is_symlink():
        workspace_node_modules.unlink()
    except OSError:
      pass

  return cleanup


def resolve_preview_file(app_root: Path, project_id: str, version_id: str, asset_path: str = "") -> tuple[Path, str]:
  dist_root = runtime_project_path(app_root, project_id, version_id) / "dist"
  if not dist_root.exists():
    raise PreviewRuntimeError("Preview build output was not found.")
  normalized_asset_path = asset_path.strip("/")
  requested = safe_join(dist_root, normalized_asset_path or "index.html")
  if requested.is_dir():
    requested = requested / "index.html"
  if not requested.exists():
    if normalized_asset_path and (normalized_asset_path.startswith("assets/") or Path(normalized_asset_path).suffix):
      raise PreviewRuntimeError(f"Preview asset was not found: {normalized_asset_path}")
    requested = dist_root / "index.html"
  content_type = PREVIEW_CONTENT_TYPES.get(requested.suffix.lower()) or mimetypes.guess_type(requested.name)[0] or "text/html"
  return requested, content_type


def safe_join(root: Path, relative_path: str) -> Path:
  candidate = (root / relative_path).resolve()
  root_resolved = root.resolve()
  if root_resolved not in candidate.parents and candidate != root_resolved:
    raise PreviewRuntimeError(f"Unsafe preview path: {relative_path}")
  return candidate
