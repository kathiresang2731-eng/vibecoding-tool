from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
  from .runtime import (
    PreviewRuntimeError,
    link_workspace_node_modules,
    normalize_preview_runtime_files,
    prepare_workspace,
    preview_node_modules_roots,
    resolve_node_binary,
    write_project_files,
  )
  from .storage import PostgresStore, UserContext
except ImportError:
  from runtime import (
    PreviewRuntimeError,
    link_workspace_node_modules,
    normalize_preview_runtime_files,
    prepare_workspace,
    preview_node_modules_roots,
    resolve_node_binary,
    write_project_files,
  )
  from storage import PostgresStore, UserContext


DEV_PREVIEW_START_TIMEOUT_SECONDS = 30
DEV_PREVIEW_HOST = os.getenv("DEV_PREVIEW_HOST", "0.0.0.0").strip() or "0.0.0.0"


@dataclass
class DevPreviewSession:
  project_id: str
  port: int
  workspace: Path
  process: subprocess.Popen[Any]
  started_at: float
  cleanup_node_modules: Any = None


_lock = threading.Lock()
_sessions: dict[str, DevPreviewSession] = {}


def _find_free_port() -> int:
  with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    return int(sock.getsockname()[1])


def _wait_for_port(port: int, *, timeout_seconds: float) -> bool:
  deadline = time.monotonic() + max(1.0, timeout_seconds)
  while time.monotonic() < deadline:
    session = _sessions.get(_session_id_for_port(port) or "")
    if session and session.process.poll() is not None:
      return False
    try:
      with socket.create_connection(("127.0.0.1", port), timeout=0.4):
        return True
    except OSError:
      time.sleep(0.25)
  return False


def _session_id_for_port(port: int) -> str | None:
  for project_id, session in _sessions.items():
    if session.port == port:
      return project_id
  return None


def _public_dev_preview_base(*, public_base_url: str, port: int, request_host: str | None = None) -> str:
  host = (request_host or "").strip()
  if not host:
    parsed = urlparse(public_base_url.strip() or "http://127.0.0.1:8787")
    host = parsed.hostname or "127.0.0.1"
  host = host.split(":")[0]
  return f"http://{host}:{port}/"


def stop_dev_preview(project_id: str) -> None:
  with _lock:
    session = _sessions.pop(project_id, None)
  if not session:
    return
  cleanup = getattr(session, "cleanup_node_modules", None)
  try:
    if session.process.poll() is None:
      session.process.terminate()
      try:
        session.process.wait(timeout=3)
      except subprocess.TimeoutExpired:
        session.process.kill()
  except Exception:
    pass
  if callable(cleanup):
    try:
      cleanup()
    except Exception:
      pass


def start_project_dev_preview(
  store: PostgresStore,
  project_id: str,
  user: UserContext,
  *,
  app_root: Path,
  public_base_url: str = "",
  request_host: str | None = None,
) -> dict[str, Any]:
  project = store.get_project(project_id, user)
  if not project:
    raise PreviewRuntimeError("Project not found.")

  files = store.list_files(project_id, user)
  if not files:
    raise PreviewRuntimeError("Project has no files to preview.")

  stop_dev_preview(project_id)

  normalized_files = normalize_preview_runtime_files(files)
  workspace = prepare_workspace(app_root, project_id)
  write_project_files(workspace, normalized_files)

  node_modules_roots = preview_node_modules_roots(app_root, workspace)
  vite_bin = next(
    (root / "vite" / "bin" / "vite.js" for root in node_modules_roots if (root / "vite" / "bin" / "vite.js").exists()),
    None,
  )
  if vite_bin is None:
    raise PreviewRuntimeError("Vite is not installed in node_modules. Run npm install in the platform root first.")

  node_binary = resolve_node_binary()
  if not node_binary:
    raise PreviewRuntimeError("Node.js was not found. Configure NODE_BINARY or install Node.js.")

  port = _find_free_port()
  cleanup_node_modules = link_workspace_node_modules(app_root, workspace)
  try:
    process = subprocess.Popen(
      [
        node_binary,
        str(vite_bin),
        "--host",
        DEV_PREVIEW_HOST,
        "--port",
        str(port),
        "--strictPort",
      ],
      cwd=workspace,
      env={
        **os.environ,
        "NODE_PATH": os.pathsep.join(str(root) for root in node_modules_roots if root.exists()),
      },
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
      text=True,
    )
  except OSError as exc:
    cleanup_node_modules()
    raise PreviewRuntimeError(f"Could not start Vite dev server: {exc}") from exc

  session = DevPreviewSession(
    project_id=project_id,
    port=port,
    workspace=workspace,
    process=process,
    started_at=time.time(),
    cleanup_node_modules=cleanup_node_modules,
  )
  with _lock:
    _sessions[project_id] = session

  ready = _wait_for_port(port, timeout_seconds=DEV_PREVIEW_START_TIMEOUT_SECONDS)

  if not ready or process.poll() is not None:
    output = ""
    try:
      if process.stdout is not None:
        output = process.stdout.read(4000) or ""
    except Exception:
      pass
    stop_dev_preview(project_id)
    raise PreviewRuntimeError(
      "Vite dev preview did not start in time."
      + (f"\n\n{output.strip()}" if output.strip() else "")
    )

  dev_preview_url = _public_dev_preview_base(
    public_base_url=public_base_url,
    port=port,
    request_host=request_host,
  )
  return {
    "status": "ready",
    "mode": "dev",
    "port": port,
    "dev_preview_url": dev_preview_url,
    "message": "Dev preview is running. Open DevTools (F12) → Console to copy runtime errors.",
  }
