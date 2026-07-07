from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse

try:
  from .api.constants import FAVICON_SVG, GENERATION_STREAM_HEARTBEAT_SECONDS, HOST, PORT, PREVIEW_RESPONSE_HEADERS
  from .api.automation_tests import automation_test_detail_payload, list_automation_tests_payload, resolve_screenshot_file
  from .api.context import AppContext, app, build_app, get_context, get_current_user, require_admin_user, require_admin_user
  from .api.errors import storage_http_error
  from .api.failures import generation_failure_payload, normalize_generation_model
  from .api.generation import run_generation_pipeline, run_generation_resume
  from .api.generation_stream import generation_stream_events
  from .api.local_workspaces import (
    directory_listing_payload,
    normalize_local_folder_name,
    path_is_inside_allowed_root,
    require_linked_local_root,
    resolve_directory_listing_path,
    serialize_local_directory,
    write_linked_project_files,
  )
  from .api.models import (
    AdminCreateUserRequest,
    AdminUpdateUserRequest,
    BrowserDirectoryFile,
    BrowserDirectoryImportRequest,
    CreateChatSessionRequest,
    CreateLocalDirectoryRequest,
    CreateProjectRequest,
    CreateSkillRequest,
    GenerateRequest,
    LoginRequest,
    LocalEnvironmentErrorRequest,
    LocalPathRequest,
    LocalSyncRequest,
    MemoryPreferenceRequest,
    RecordChatMessageRequest,
    ResumeGenerationRequest,
    SaveFileRequest,
    SignupRequest,
    UpdateProfileRequest,
    UpdateProjectRequest,
  )
  from .api.v1.models import CancelRunRequest, CreateRunRequest as V1CreateRunRequest
  from .api.previews import rewrite_preview_html
  from .api.project_download import build_project_zip, safe_download_filename
  from .api.progress import emit_progress
  from .api.run_locks import active_project_run, cancel_project_run
  from .agent_runtime import persist_agent_runtime_output
  from .audit_logging import RunTelemetryContext, telemetry_scope
  from .agents.artifacts import ArtifactValidationError
  from .agents.generator import generate_website, generate_website_or_error
  from .agents.providers import GeminiProvider
  from .debug_trace import trace_function
  from .local_workspace import (
    LocalWorkspaceError,
    normalize_project_file_path,
    read_local_project_files,
    resolve_local_project_path,
    validate_complete_project_import,
    write_local_project_files,
  )
  from .runtime import PreviewRuntimeError, build_project_preview, delete_project_runtime, resolve_preview_file
  from .dev_preview import start_project_dev_preview, stop_dev_preview
  from .storage import StorageError, UserContext
except ImportError:
  from backend.api.constants import FAVICON_SVG, GENERATION_STREAM_HEARTBEAT_SECONDS, HOST, PORT, PREVIEW_RESPONSE_HEADERS
  from backend.api.automation_tests import automation_test_detail_payload, list_automation_tests_payload, resolve_screenshot_file
  from backend.api.context import AppContext, app, build_app, get_context, get_current_user, require_admin_user
  from backend.api.errors import storage_http_error
  from backend.api.failures import generation_failure_payload, normalize_generation_model
  from backend.api.generation import run_generation_pipeline, run_generation_resume
  from backend.api.generation_stream import generation_stream_events
  from backend.api.local_workspaces import (
    directory_listing_payload,
    normalize_local_folder_name,
    path_is_inside_allowed_root,
    require_linked_local_root,
    resolve_directory_listing_path,
    serialize_local_directory,
    write_linked_project_files,
  )
  from backend.api.models import (
    AdminCreateUserRequest,
    AdminUpdateUserRequest,
    BrowserDirectoryFile,
    BrowserDirectoryImportRequest,
    CreateChatSessionRequest,
    CreateLocalDirectoryRequest,
    CreateProjectRequest,
    CreateSkillRequest,
    GenerateRequest,
    LoginRequest,
    LocalEnvironmentErrorRequest,
    LocalPathRequest,
    LocalSyncRequest,
    MemoryPreferenceRequest,
    RecordChatMessageRequest,
    ResumeGenerationRequest,
    SaveFileRequest,
    SignupRequest,
    UpdateProfileRequest,
    UpdateProjectRequest,
  )
  from backend.api.v1.models import CancelRunRequest, CreateRunRequest as V1CreateRunRequest
  from backend.api.previews import rewrite_preview_html
  from backend.api.project_download import build_project_zip, safe_download_filename
  from backend.api.progress import emit_progress
  from backend.api.run_locks import active_project_run, cancel_project_run
  from backend.agent_runtime import persist_agent_runtime_output
  from backend.audit_logging import RunTelemetryContext, telemetry_scope
  from backend.agents.artifacts import ArtifactValidationError
  from backend.agents.generator import generate_website, generate_website_or_error
  from backend.agents.providers import GeminiProvider
  from backend.debug_trace import trace_function
  from backend.local_workspace import (
    LocalWorkspaceError,
    normalize_project_file_path,
    read_local_project_files,
    resolve_local_project_path,
    validate_complete_project_import,
    write_local_project_files,
  )
  from backend.runtime import PreviewRuntimeError, build_project_preview, delete_project_runtime, resolve_preview_file
  from backend.dev_preview import start_project_dev_preview, stop_dev_preview
  from backend.storage import StorageError, UserContext


@app.get("/api/health")
def health() -> dict[str, Any]:
  return {"ok": True, "service": "vibe-platform-backend"}


@app.get("/api/health/memory")
def memory_health(_admin: UserContext = Depends(require_admin_user)) -> dict[str, Any]:
  context = get_context()
  try:
    from .agents.memory.episode_vector_store import episode_vector_health
  except ImportError:
    from backend.agents.memory.episode_vector_store import episode_vector_health
  memory = context.store.get_memory_health()
  vector = episode_vector_health()
  return {
    "ok": bool(memory.get("healthy")) and bool(vector.get("healthy")),
    "memory": memory,
    "vector_retrieval": vector,
    "worker_enabled": context.settings.memory_consistency_worker_enabled,
  }


@app.post("/api/health/memory/validate-constraints")
def validate_memory_constraints(
  dry_run: bool = True,
  _admin: UserContext = Depends(require_admin_user),
) -> dict[str, Any]:
  context = get_context()
  if not hasattr(context.store, "validate_memory_scope_constraints"):
    return {
      "status": "unsupported",
      "reason": "store_does_not_support_memory_scope_constraint_validation",
      "dry_run": dry_run,
    }
  return context.store.validate_memory_scope_constraints(dry_run=dry_run)


def format_local_environment_error_message(request: LocalEnvironmentErrorRequest) -> str:
  lines = [
    "Local environment error reported by Worktual UI.",
    f"Operation: {request.operation or 'unknown'}",
    f"Error: {request.message}",
  ]
  if request.workspace_name:
    lines.append(f"Workspace: {request.workspace_name}")
  if request.workspace_kind:
    lines.append(f"Workspace kind: {request.workspace_kind}")
  if request.system_name:
    lines.append(f"System name: {request.system_name}")
  if request.helper_url:
    lines.append(f"Local terminal helper: {request.helper_url}")
  lines.extend(
    [
      "Orchestrator instruction: route this as a local environment / terminal handling failure. Use the Universal Error Handling Agent and terminal handling agent capabilities where available.",
      "If the local helper is unreachable, instruct the user to start it on their own machine before running terminal actions.",
      "If dependencies are missing, use terminal actions to inspect the workspace and install only required dependencies before retrying tests/builds.",
    ]
  )
  if request.recommended_action:
    lines.append(f"Recommended action: {request.recommended_action}")
  if request.details:
    lines.append(f"Details: {request.details}")
  return "\n".join(lines)


@app.get("/api/local-helper/skills-helper.py")
def download_skills_helper() -> FileResponse:
  helper_path = Path(__file__).resolve().parents[1] / "local_helper" / "skills_helper.py"
  if not helper_path.is_file():
    raise HTTPException(status_code=404, detail="Local skills helper script was not found.")
  return FileResponse(
    helper_path,
    media_type="text/x-python",
    filename="worktual-skills-helper.py",
  )


@app.get("/api/local-helper/bootstrap.sh")
def download_bootstrap_script(request: Request, project_path: Optional[str] = None) -> Response:
  template_path = Path(__file__).resolve().parents[1] / "local_helper" / "bootstrap.sh"
  if not template_path.is_file():
    raise HTTPException(status_code=404, detail="Local bootstrap script was not found.")
  server_base = str(request.base_url).rstrip("/")
  script = template_path.read_text(encoding="utf-8").replace("__WORKTUAL_SERVER__", server_base)
  filename = "worktual-local-setup.sh"
  headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
  return Response(content=script, media_type="application/x-sh", headers=headers)


@app.get("/api/skills")
def list_skills(
  workspace_root: Optional[str] = None,
  system_name: Optional[str] = None,
  x_worktual_system_name: Optional[str] = Header(default=None),
) -> dict[str, Any]:
  try:
    from .api.skills import list_skills_payload
  except ImportError:
    from api.skills import list_skills_payload
  return list_skills_payload(workspace_root, system_name=system_name or x_worktual_system_name)


@app.post("/api/skills/bootstrap")
def bootstrap_skills(
  workspace_root: Optional[str] = None,
  system_name: Optional[str] = None,
  x_worktual_system_name: Optional[str] = Header(default=None),
) -> dict[str, Any]:
  try:
    from .api.skills import bootstrap_skills_payload
  except ImportError:
    from api.skills import bootstrap_skills_payload
  try:
    return bootstrap_skills_payload(
      workspace_root,
      system_name=system_name or x_worktual_system_name,
    )
  except Exception as exc:
    raise HTTPException(status_code=500, detail=f"Skills bootstrap failed: {exc}") from exc


@app.post("/api/skills/create")
def create_skill(
  request: CreateSkillRequest,
  system_name: Optional[str] = None,
  x_worktual_system_name: Optional[str] = Header(default=None),
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .api.skills import create_skill_payload
  except ImportError:
    from api.skills import create_skill_payload
  try:
    return create_skill_payload(
      request.prompt,
      workspace_root=request.workspace_root,
      system_name=request.system_name or system_name or x_worktual_system_name,
      model_provider=GeminiProvider(model=normalize_generation_model(request.model)),
      project_id=request.project_id,
      store=context.store,
      user=user,
    )
  except ValueError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
  except Exception as exc:
    raise HTTPException(status_code=500, detail=f"Skill creation failed: {exc}") from exc


@app.get("/api/projects/{project_id}/skills")
def list_project_skills(
  project_id: str,
  workspace_root: Optional[str] = None,
  system_name: Optional[str] = None,
  x_worktual_system_name: Optional[str] = Header(default=None),
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .api.skills import list_project_skills_payload
  except ImportError:
    from api.skills import list_project_skills_payload
  try:
    return list_project_skills_payload(
      project_id,
      context.store,
      user,
      workspace_root=workspace_root,
      system_name=system_name or x_worktual_system_name,
    )
  except ValueError as exc:
    raise HTTPException(status_code=404, detail=str(exc)) from exc
  except StorageError as exc:
    raise storage_http_error(exc)


@app.post("/api/projects/{project_id}/skills/bootstrap")
def bootstrap_project_skills(
  project_id: str,
  workspace_root: Optional[str] = None,
  system_name: Optional[str] = None,
  x_worktual_system_name: Optional[str] = Header(default=None),
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .api.skills import bootstrap_project_skills_payload
  except ImportError:
    from api.skills import bootstrap_project_skills_payload
  try:
    return bootstrap_project_skills_payload(
      project_id,
      context.store,
      user,
      workspace_root=workspace_root,
      system_name=system_name or x_worktual_system_name,
    )
  except ValueError as exc:
    raise HTTPException(status_code=404, detail=str(exc)) from exc
  except StorageError as exc:
    raise storage_http_error(exc)
  except Exception as exc:
    raise HTTPException(status_code=500, detail=f"Project skills bootstrap failed: {exc}") from exc


@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.svg", include_in_schema=False)
def favicon() -> Response:
  return Response(
    content=FAVICON_SVG,
    media_type="image/svg+xml",
    headers={"Cache-Control": "public, max-age=86400"},
  )


@app.get("/api/session")
def session(
  user: UserContext = Depends(get_current_user),
  context: AppContext = Depends(get_context),
) -> dict[str, Any]:
  usage = context.store.get_user_usage_summary(user.id)
  return {
    "user": {
      "id": user.id,
      "email": user.email,
      "role": user.role,
      "display_name": user.display_name,
      "is_active": user.is_active,
      "usage": usage,
    },
    "roles": ["admin", "owner", "editor", "viewer"],
    "auth": {
      "signup_enabled": context.settings.auth_allow_signup,
    },
    "usage": usage,
  }


@app.get("/api/users/me/usage")
def current_user_usage(
  recent_request_limit: Optional[int] = None,
  user: UserContext = Depends(get_current_user),
  context: AppContext = Depends(get_context),
) -> dict[str, Any]:
  if recent_request_limit is not None:
    return context.store.get_user_usage_summary(
      user.id,
      recent_request_limit=recent_request_limit,
    )
  return context.store.get_user_usage_summary(user.id)


@app.get("/api/admin/users")
def list_admin_users(
  context: AppContext = Depends(get_context),
  admin: UserContext = Depends(require_admin_user),
) -> dict[str, Any]:
  try:
    from .api.admin_users import list_admin_users_payload
  except ImportError:
    from api.admin_users import list_admin_users_payload
  return list_admin_users_payload(context.store)


@app.post("/api/admin/users")
def create_admin_user(
  request: AdminCreateUserRequest,
  context: AppContext = Depends(get_context),
  admin: UserContext = Depends(require_admin_user),
) -> dict[str, Any]:
  try:
    from .api.admin_users import create_admin_user_payload
  except ImportError:
    from api.admin_users import create_admin_user_payload
  return create_admin_user_payload(request, context.store, admin)


@app.patch("/api/admin/users/{user_id}")
def update_admin_user(
  user_id: str,
  request: AdminUpdateUserRequest,
  context: AppContext = Depends(get_context),
  admin: UserContext = Depends(require_admin_user),
) -> dict[str, Any]:
  try:
    from .api.admin_users import update_admin_user_payload
  except ImportError:
    from api.admin_users import update_admin_user_payload
  return update_admin_user_payload(user_id, request, context.store, admin)


@app.delete("/api/admin/users/{user_id}")
def delete_admin_user(
  user_id: str,
  context: AppContext = Depends(get_context),
  admin: UserContext = Depends(require_admin_user),
) -> dict[str, Any]:
  try:
    from .api.admin_users import delete_admin_user_payload
  except ImportError:
    from api.admin_users import delete_admin_user_payload
  return delete_admin_user_payload(user_id, context.store, admin)


@app.post("/api/auth/signup")
def auth_signup(
  request: SignupRequest,
  context: AppContext = Depends(get_context),
) -> dict[str, Any]:
  try:
    from .api.auth import signup_payload
  except ImportError:
    from api.auth import signup_payload
  return signup_payload(request, context.store, context.settings)


@app.post("/api/auth/login")
def auth_login(
  request: LoginRequest,
  context: AppContext = Depends(get_context),
) -> dict[str, Any]:
  try:
    from .api.auth import login_payload
  except ImportError:
    from api.auth import login_payload
  return login_payload(request, context.store, context.settings)


@app.patch("/api/users/me")
def update_current_user(
  request: UpdateProfileRequest,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .api.auth import update_profile_payload
  except ImportError:
    from api.auth import update_profile_payload
  return update_profile_payload(user, request, context.store)


@app.get("/api/users/me/memory/preferences")
def list_user_memory_preferences(
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .api.memory_preferences import list_memory_preferences_payload
  except ImportError:
    from api.memory_preferences import list_memory_preferences_payload
  return list_memory_preferences_payload(user, context.store)


@app.post("/api/users/me/memory/preferences")
def upsert_user_memory_preference(
  request: MemoryPreferenceRequest,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .api.memory_preferences import upsert_memory_preference_payload
  except ImportError:
    from api.memory_preferences import upsert_memory_preference_payload
  return upsert_memory_preference_payload(user, request, context.store)


@app.delete("/api/users/me/memory/preferences/{preference_id}")
def delete_user_memory_preference(
  preference_id: str,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .api.memory_preferences import delete_memory_preference_payload
  except ImportError:
    from api.memory_preferences import delete_memory_preference_payload
  return delete_memory_preference_payload(user, preference_id, context.store)


@app.get("/api/users/me/memory/episodes")
def list_user_memory_episodes(
  project_id: str,
  chat_session_id: str,
  prompt: str = "",
  limit: int = 5,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .api.memory_episodes import list_memory_episodes_payload
  except ImportError:
    from api.memory_episodes import list_memory_episodes_payload
  return list_memory_episodes_payload(
    user,
    context.store,
    project_id=project_id,
    chat_session_id=chat_session_id,
    prompt=prompt,
    limit=limit,
  )


@app.delete("/api/users/me/memory/episodes/{episode_id}")
def delete_user_memory_episode(
  episode_id: str,
  project_id: str,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .api.memory_episodes import delete_memory_episode_payload
  except ImportError:
    from api.memory_episodes import delete_memory_episode_payload
  return delete_memory_episode_payload(
    user,
    context.store,
    episode_id=episode_id,
    project_id=project_id,
  )


@app.get("/api/memory/learning-events")
def list_memory_learning_events(
  project_id: str | None = None,
  chat_session_id: str | None = None,
  run_id: str | None = None,
  scope: str | None = None,
  limit: int = 50,
  all_users: bool = False,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .api.memory_learning import list_learning_events_payload
  except ImportError:
    from api.memory_learning import list_learning_events_payload
  return list_learning_events_payload(
    context.store,
    user,
    project_id=project_id,
    chat_session_id=chat_session_id,
    run_id=run_id,
    scope=scope,
    limit=limit,
    include_all_users=all_users,
  )


@app.get("/api/memory/why-injected")
def explain_memory_injection(
  run_id: str,
  project_id: str | None = None,
  limit: int = 25,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .api.memory_learning import why_injected_payload
  except ImportError:
    from api.memory_learning import why_injected_payload
  return why_injected_payload(
    context.store,
    user,
    run_id=run_id,
    project_id=project_id,
    limit=limit,
  )


@app.get("/api/memory/platform-patterns")
def list_memory_platform_patterns(
  domain: str | None = None,
  module: str | None = None,
  pattern_type: str | None = None,
  limit: int = 25,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .api.memory_learning import list_platform_memory_patterns_payload
  except ImportError:
    from api.memory_learning import list_platform_memory_patterns_payload
  return list_platform_memory_patterns_payload(
    context.store,
    domain=domain,
    module=module,
    pattern_type=pattern_type,
    limit=limit,
  )


@app.get("/api/projects")
def list_projects(
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  return {"projects": context.store.list_projects(user)}


@app.post("/api/projects")
def create_project(
  request: CreateProjectRequest,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    workspace_mode = request.workspace_mode.strip().lower()
    if request.local_path and request.local_path.strip():
      local_root = resolve_local_project_path(context.settings, request.local_path)
      local_root.mkdir(parents=True, exist_ok=True)
      project = context.store.create_project(user, name=request.name, description=request.description)
      project = context.store.set_project_local_path(project["id"], user, str(local_root))
      local_files = read_local_project_files(local_root)
      if local_files:
        validate_complete_project_import(local_files, source_label="Local workspace pull")
        context.store.replace_project_files(
          project["id"],
          user,
          local_files,
          event_type="local.pulled",
          event_payload={"path": str(local_root)},
          allow_prune_missing=True,
        )
        files = context.store.list_files(project["id"], user)
        sync = {"direction": "pull", "count": len(files), "path": str(local_root)}
      else:
        files = []
        context.store.add_event(project["id"], user.id, "local.workspace.ready", {"path": str(local_root)})
        sync = {"direction": "ready", "count": 0, "path": str(local_root)}
      return {"project": project, "files": files, "sync": sync}

    if workspace_mode not in {"backend", "local"}:
      raise HTTPException(status_code=400, detail="Project workspace mode must be backend or local.")
    if workspace_mode == "local":
      raise HTTPException(status_code=400, detail="Local path is required for local workspace projects.")

    project = context.store.create_project(user, name=request.name, description=request.description)
    context.store.add_event(project["id"], user.id, "workspace.backend.created", {"runtime": "backend"})
    return {"project": project, "files": [], "sync": {"direction": "backend", "count": 0}}
  except LocalWorkspaceError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
  except StorageError as exc:
    raise storage_http_error(exc)


@app.get("/api/projects/{project_id}/chat")
def list_project_chat(
  project_id: str,
  limit: int = 200,
  chat_session_id: Optional[str] = None,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .api.chat import list_project_chat_payload
  except ImportError:
    from api.chat import list_project_chat_payload
  try:
    return list_project_chat_payload(
      project_id,
      context.store,
      user,
      limit=limit,
      chat_session_id=chat_session_id,
    )
  except ValueError as exc:
    raise HTTPException(status_code=404, detail=str(exc)) from exc
  except StorageError as exc:
    raise storage_http_error(exc)


@app.get("/api/projects/{project_id}/chat/sessions")
def list_project_chat_sessions(
  project_id: str,
  limit: int = 20,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .api.chat import list_project_chat_sessions_payload
  except ImportError:
    from api.chat import list_project_chat_sessions_payload
  try:
    return list_project_chat_sessions_payload(project_id, context.store, user, limit=limit)
  except ValueError as exc:
    raise HTTPException(status_code=404, detail=str(exc)) from exc
  except StorageError as exc:
    raise storage_http_error(exc)


@app.get("/api/projects/{project_id}/chat/sessions/active")
def get_active_project_chat_session(
  project_id: str,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .api.chat import ensure_project_chat_session
  except ImportError:
    from api.chat import ensure_project_chat_session
  try:
    session = ensure_project_chat_session(project_id, context.store, user)
    return {"project_id": project_id, "user_id": user.id, "session": session}
  except ValueError as exc:
    raise HTTPException(status_code=404, detail=str(exc)) from exc
  except StorageError as exc:
    raise storage_http_error(exc)


@app.post("/api/projects/{project_id}/chat/sessions")
def create_project_chat_session(
  project_id: str,
  request: CreateChatSessionRequest,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .api.chat import create_project_chat_session_payload
  except ImportError:
    from api.chat import create_project_chat_session_payload
  try:
    return create_project_chat_session_payload(
      project_id,
      context.store,
      user,
      title=request.title,
      settings=context.settings,
    )
  except ValueError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
  except StorageError as exc:
    raise storage_http_error(exc)


@app.post("/api/projects/{project_id}/chat")
def record_project_chat(
  project_id: str,
  request: RecordChatMessageRequest,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .api.chat import record_project_chat_payload
  except ImportError:
    from api.chat import record_project_chat_payload
  try:
    return record_project_chat_payload(
      project_id,
      context.store,
      user,
      role=request.role,
      content=request.content,
      metadata=request.metadata,
      chat_session_id=request.chat_session_id,
    )
  except ValueError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
  except StorageError as exc:
    raise storage_http_error(exc)


@app.delete("/api/projects/{project_id}")
def delete_project(
  project_id: str,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    deleted_project = context.store.delete_project(project_id, user)
    delete_project_runtime(context.settings.app_root, project_id)
    return {"deleted_project": deleted_project}
  except (PreviewRuntimeError, StorageError) as exc:
    raise storage_http_error(exc)


@app.get("/api/projects/{project_id}")
def get_project(
  project_id: str,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    project = context.store.get_project(project_id, user)
  except StorageError as exc:
    raise storage_http_error(exc)
  if not project:
    raise HTTPException(status_code=404, detail="Project not found.")
  return {"project": project}


@app.patch("/api/projects/{project_id}")
def update_project(
  project_id: str,
  request: UpdateProjectRequest,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    project = context.store.update_project(project_id, user, name=request.name)
    return {"project": project}
  except StorageError as exc:
    raise storage_http_error(exc)


@app.get("/api/projects/{project_id}/files")
def list_files(
  project_id: str,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    return {"files": context.store.list_files(project_id, user)}
  except StorageError as exc:
    raise storage_http_error(exc)


@app.get("/api/projects/{project_id}/download")
def download_project_files(
  project_id: str,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> Response:
  try:
    project = context.store.get_project(project_id, user)
    if not project:
      raise HTTPException(status_code=404, detail="Project not found.")
    files = context.store.list_files(project_id, user)
    if not files:
      raise HTTPException(status_code=404, detail="No generated files are available to download yet.")
    archive = build_project_zip(files, project_name=str(project.get("name") or "project"))
    filename = f"{safe_download_filename(str(project.get('name') or 'project'))}-worktual.zip"
    return Response(
      content=archive,
      media_type="application/zip",
      headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
  except ValueError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
  except StorageError as exc:
    raise storage_http_error(exc)


@app.put("/api/projects/{project_id}/files/{path:path}")
def save_file(
  project_id: str,
  path: str,
  request: SaveFileRequest,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    safe_path = normalize_project_file_path(path)
    project = context.store.get_project(project_id, user)
    local_sync = write_linked_project_files(
      context,
      project,
      [{"path": safe_path, "content": request.content}],
      user,
      event_type="local.file.written",
    )
    saved_file = context.store.upsert_file(project_id, user, path=safe_path, content=request.content)
    try:
      from .agents.code_index.incremental import maybe_reindex_after_persist
    except ImportError:
      from agents.code_index.incremental import maybe_reindex_after_persist
    maybe_reindex_after_persist(
      project_id,
      [{"path": safe_path, "content": request.content}],
      changed_paths=[safe_path],
    )
    return {"file": saved_file, "local_sync": local_sync}
  except LocalWorkspaceError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
  except StorageError as exc:
    raise storage_http_error(exc)


@app.put("/api/projects/{project_id}/local-path")
def link_local_path(
  project_id: str,
  request: LocalPathRequest,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    local_root = resolve_local_project_path(context.settings, request.path)
    local_root.mkdir(parents=True, exist_ok=True)
    project = context.store.set_project_local_path(project_id, user, str(local_root))
    local_files = read_local_project_files(local_root)
    if local_files:
      validate_complete_project_import(local_files, source_label="Linked local workspace pull")
      context.store.replace_project_files(
        project_id,
        user,
        local_files,
        event_type="local.pulled",
        event_payload={"path": str(local_root)},
        allow_prune_missing=True,
      )
      files = context.store.list_files(project_id, user)
      sync = {"direction": "pull", "count": len(files), "path": str(local_root)}
    else:
      files = context.store.list_files(project_id, user)
      count = write_local_project_files(local_root, files, prune_missing=False)
      context.store.add_event(project_id, user.id, "local.pushed", {"path": str(local_root), "count": count, "mode": "upsert"})
      sync = {"direction": "push", "count": count, "path": str(local_root), "mode": "upsert"}
    return {"project": project, "files": files, "sync": sync}
  except LocalWorkspaceError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
  except StorageError as exc:
    raise storage_http_error(exc)


@app.post("/api/projects/{project_id}/sync-local")
def sync_local_path(
  project_id: str,
  request: LocalSyncRequest,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  direction = request.direction.strip().lower()
  if direction not in {"pull", "push"}:
    raise HTTPException(status_code=400, detail="Local sync direction must be pull or push.")

  try:
    project = context.store.get_project(project_id, user)
    if not project:
      raise HTTPException(status_code=404, detail="Project not found.")
    local_root = require_linked_local_root(context, project)
    if direction == "pull":
      files = read_local_project_files(local_root)
      if not files:
        raise LocalWorkspaceError("No supported project files were found in the linked local folder.")
      validate_complete_project_import(files, source_label="Local workspace pull")
      context.store.replace_project_files(
        project_id,
        user,
        files,
        event_type="local.pulled",
        event_payload={"path": str(local_root)},
        allow_prune_missing=True,
      )
      return {
        "project": context.store.get_project(project_id, user),
        "files": context.store.list_files(project_id, user),
        "sync": {"direction": "pull", "count": len(files), "path": str(local_root)},
      }

    files = context.store.list_files(project_id, user)
    allow_prune_missing = bool(request.allow_prune_missing)
    count = write_local_project_files(
      local_root,
      files,
      prune_missing=allow_prune_missing,
      allow_prune_missing=allow_prune_missing,
    )
    mode = "replace_all" if allow_prune_missing else "upsert"
    context.store.add_event(project_id, user.id, "local.pushed", {"path": str(local_root), "count": count, "mode": mode})
    return {"project": project, "files": files, "sync": {"direction": "push", "count": count, "path": str(local_root), "mode": mode}}
  except HTTPException:
    raise
  except LocalWorkspaceError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
  except StorageError as exc:
    raise storage_http_error(exc)


@app.get("/api/local-directories")
def list_local_directories(
  path: Optional[str] = None,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    current_path = resolve_directory_listing_path(context.settings, path)
    return directory_listing_payload(context.settings, current_path)
  except LocalWorkspaceError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/local-directories")
def create_local_directory(
  request: CreateLocalDirectoryRequest,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    parent_path = resolve_local_project_path(context.settings, request.parent_path)
    folder_name = normalize_local_folder_name(request.name)
    directory_path = parent_path / folder_name
    if not path_is_inside_allowed_root(context.settings, directory_path):
      raise LocalWorkspaceError("New folder must stay inside an allowed local workspace root.")
    directory_path.mkdir(parents=True, exist_ok=True)
    return {"directory": serialize_local_directory(directory_path), "listing": directory_listing_payload(context.settings, parent_path)}
  except LocalWorkspaceError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/import-directory")
def import_browser_directory(
  project_id: str,
  request: BrowserDirectoryImportRequest,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    project = context.store.get_project(project_id, user)
    if not project:
      raise HTTPException(status_code=404, detail="Project not found.")
    normalized_files = []
    seen_paths: set[str] = set()
    for file_item in request.files:
      path = normalize_project_file_path(file_item.path)
      if path in seen_paths:
        raise LocalWorkspaceError(f"Duplicate file path: {path}")
      seen_paths.add(path)
      normalized_files.append({"path": path, "content": file_item.content})
    if not normalized_files:
      context.store.add_event(
        project_id,
        user.id,
        "local.browser_workspace_ready",
        {"count": 0, "paths": [], "root_files": []},
      )
      return {
        "project": context.store.get_project(project_id, user),
        "files": context.store.list_files(project_id, user),
        "sync": {
          "direction": "browser_import_ready",
          "count": 0,
          "paths": [],
          "root_files": [],
        },
      }
    validate_complete_project_import(
      normalized_files,
      source_label="Browser directory import",
      require_complete=False,
    )
    imported_paths = [file_item["path"] for file_item in normalized_files]
    root_files = [path for path in imported_paths if "/" not in path]
    context.store.replace_project_files(
      project_id,
      user,
      normalized_files,
      event_type="local.browser_imported",
      event_payload={
        "count": len(normalized_files),
        "paths": imported_paths[:100],
        "root_files": root_files,
      },
      allow_prune_missing=True,
    )
    return {
      "project": context.store.get_project(project_id, user),
      "files": context.store.list_files(project_id, user),
      "sync": {
        "direction": "browser_import",
        "count": len(normalized_files),
        "paths": imported_paths,
        "root_files": root_files,
      },
    }
  except HTTPException:
    raise
  except LocalWorkspaceError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
  except ArtifactValidationError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
  except StorageError as exc:
    raise storage_http_error(exc)


@app.post("/api/projects/{project_id}/local-environment-error")
def record_local_environment_error(
  project_id: str,
  request: LocalEnvironmentErrorRequest,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  project = context.store.get_project(project_id, user)
  if not project:
    raise HTTPException(status_code=404, detail="Project not found.")

  message = format_local_environment_error_message(request)
  try:
    chat_message = context.store.record_project_chat_message(
      project_id,
      user,
      role="user",
      content=message,
      metadata={
        "source": "local_environment_error",
        "operation": request.operation,
        "workspace_name": request.workspace_name,
        "workspace_kind": request.workspace_kind,
        "system_name": request.system_name,
        "helper_url": request.helper_url,
        "details": request.details or {},
      },
    )
    context.store.add_event(
      project_id,
      user.id,
      "local.environment.error",
      {
        "source": request.source,
        "operation": request.operation,
        "message": request.message,
        "workspace": request.workspace_name,
        "workspace_kind": request.workspace_kind,
        "system_name": request.system_name,
      },
    )
    return {"ok": True, "message": chat_message}
  except StorageError as exc:
    raise storage_http_error(exc)


@app.post("/api/projects/{project_id}/generate")
@trace_function(project_id=lambda project_id, *_args, **_kwargs: project_id, endpoint="/api/projects/{project_id}/generate")
def generate_project(
  project_id: str,
  request: GenerateRequest,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
  x_worktual_system_name: Optional[str] = Header(default=None),
  x_worktual_chat_session_id: Optional[str] = Header(default=None),
) -> dict[str, Any]:
  prompt = request.prompt.strip()
  if not prompt:
    raise HTTPException(status_code=400, detail="Prompt is empty. Describe the website you want to build.")

  try:
    _ensure_update_workspace_access(
      project_id=project_id,
      prompt=prompt,
      workspace_access=request.workspace_access,
      context=context,
      user=user,
    )
    if request.model:
      return run_generation_pipeline(
        project_id,
        prompt,
        context,
        user,
        model=request.model,
        model_policy=request.model_policy,
        artifact_model=request.artifact_model,
        request_class=request.request_class,
        estimated_credit_reservation=request.estimated_credit_reservation,
        system_name=x_worktual_system_name,
        chat_session_id=x_worktual_chat_session_id,
      )
    return run_generation_pipeline(
      project_id,
      prompt,
      context,
      user,
      model_policy=request.model_policy,
      artifact_model=request.artifact_model,
      request_class=request.request_class,
      estimated_credit_reservation=request.estimated_credit_reservation,
      system_name=x_worktual_system_name,
      chat_session_id=x_worktual_chat_session_id,
    )
  except HTTPException as exc:
    if exc.status_code >= 500:
      failure = generation_failure_payload(exc, default_status=exc.status_code)
      raise HTTPException(status_code=failure["status"], detail=failure) from exc
    raise
  except StorageError as exc:
    raise storage_http_error(exc)
  except Exception as exc:
    try:
      context.store.create_generation_run(
        project_id,
        user,
        prompt=prompt,
        provider=request.model or "gemini",
        status="failed",
        error=str(exc),
      )
    except Exception:
      pass
    failure = generation_failure_payload(exc)
    raise HTTPException(status_code=failure["status"], detail=failure) from exc


def _first_text_value(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
  for key in keys:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
      return value.strip()
  return ""


def _coerce_generate_request_payload(payload: Any) -> GenerateRequest:
  if isinstance(payload, GenerateRequest):
    return payload
  if isinstance(payload, str):
    return GenerateRequest(prompt=payload.strip())
  if not isinstance(payload, dict):
    return GenerateRequest()

  prompt = _first_text_value(payload, ("prompt", "message", "content", "text", "query", "input"))
  model = payload.get("model")
  if not isinstance(model, str) or model == "server-default":
    model = None
  confirmation_action = payload.get("confirmation_action")
  if confirmation_action not in {"confirm", "cancel"}:
    confirmation_action = None
  patch_action = payload.get("patch_action")
  if patch_action not in {"approve", "reject"}:
    patch_action = None
  attachments = payload.get("attachments") if isinstance(payload, dict) else []
  if not isinstance(attachments, list):
    attachments = []
  workspace_access = payload.get("workspace_access")
  if not isinstance(workspace_access, dict):
    workspace_access = None
  return GenerateRequest(
    prompt=prompt,
    model=model,
    confirmation_action=confirmation_action,
    patch_action=patch_action,
    attachments=attachments,
    workspace_access=workspace_access,
  )


async def _read_generate_request(request: Request) -> GenerateRequest:
  payload: Any = {}
  try:
    payload = await request.json()
  except Exception:
    try:
      raw_body = (await request.body()).decode("utf-8", errors="ignore").strip()
      if raw_body:
        payload = raw_body
    except Exception:
      payload = {}

  generate_request = _coerce_generate_request_payload(payload)
  if not generate_request.prompt:
    query_prompt = _first_text_value(dict(request.query_params), ("prompt", "message", "content", "text", "query", "input"))
    if query_prompt:
      generate_request.prompt = query_prompt
  return generate_request


def _ensure_update_workspace_access(
  *,
  project_id: str,
  prompt: str,
  workspace_access: dict[str, Any] | None,
  context: AppContext,
  user: UserContext,
) -> dict[str, Any]:
  from backend.api.generation_parts.workspace_access import ensure_update_workspace_ready

  project = context.store.get_project(project_id, user)
  if not project:
    raise HTTPException(status_code=404, detail="Project not found.")
  project_files = context.store.list_files(project_id, user)
  return ensure_update_workspace_ready(
    prompt=prompt,
    project=project,
    project_files=project_files,
    settings=context.settings,
    client_workspace_access=workspace_access,
  )


@app.get("/api/projects/{project_id}/update-readiness")
def project_update_readiness(
  project_id: str,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  from backend.api.generation_parts.workspace_access import local_workspace_readiness

  project = context.store.get_project(project_id, user)
  if not project:
    raise HTTPException(status_code=404, detail="Project not found.")
  return {"project_id": project_id, "workspace_access": local_workspace_readiness(project, context.settings)}


@app.post("/api/projects/{project_id}/generate/resume")
@trace_function(project_id=lambda project_id, *_args, **_kwargs: project_id, endpoint="/api/projects/{project_id}/generate/resume")
def resume_project_generation(
  project_id: str,
  request: ResumeGenerationRequest,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  prompt = request.prompt.strip()
  if not prompt:
    raise HTTPException(status_code=400, detail="Prompt is empty. Reply with confirm, revise, or cancel.")

  try:
    return run_generation_resume(
      project_id,
      prompt,
      context,
      user,
      thread_id=request.thread_id,
      model=request.model,
      model_policy=request.model_policy,
      artifact_model=request.artifact_model,
      request_class=request.request_class,
      estimated_credit_reservation=request.estimated_credit_reservation,
      resume_graph=request.resume_graph,
    )
  except ValueError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
  except HTTPException as exc:
    if exc.status_code >= 500:
      failure = generation_failure_payload(exc, default_status=exc.status_code)
      raise HTTPException(status_code=failure["status"], detail=failure) from exc
    raise
  except StorageError as exc:
    raise storage_http_error(exc)
  except Exception as exc:
    failure = generation_failure_payload(exc)
    raise HTTPException(status_code=failure["status"], detail=failure) from exc


@app.post("/api/projects/{project_id}/generate-stream")
@trace_function(project_id=lambda project_id, *_args, **_kwargs: project_id, endpoint="/api/projects/{project_id}/generate-stream")
async def generate_project_stream(
  project_id: str,
  request: Request,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> StreamingResponse:
  generate_request = await _read_generate_request(request)
  prompt = generate_request.prompt.strip()
  attachments = [item.model_dump() for item in generate_request.attachments]
  if not prompt and not attachments:
    raise HTTPException(status_code=400, detail="Prompt is empty. Describe the website you want to build or attach a screenshot/file.")
  _ensure_update_workspace_access(
    project_id=project_id,
    prompt=prompt,
    workspace_access=generate_request.workspace_access,
    context=context,
    user=user,
  )

  headers = getattr(request, "headers", {})
  system_name = headers.get("x-worktual-system-name") if hasattr(headers, "get") else None
  chat_session_id = headers.get("x-worktual-chat-session-id") if hasattr(headers, "get") else None

  return StreamingResponse(
    generation_stream_events(
      project_id,
      prompt,
      context,
      user,
      model=generate_request.model,
      model_policy=generate_request.model_policy,
      artifact_model=generate_request.artifact_model,
      request_class=generate_request.request_class,
      estimated_credit_reservation=generate_request.estimated_credit_reservation,
      run_generation_pipeline=run_generation_pipeline,
      system_name=system_name,
      chat_session_id=chat_session_id,
      confirmation_action=generate_request.confirmation_action,
      patch_action=generate_request.patch_action,
      attachments=attachments,
    ),
    media_type="application/x-ndjson",
  )


@app.post("/api/projects/{project_id}/generate/cancel")
def cancel_project_generation(
  project_id: str,
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  cancelled = cancel_project_run(project_id, user_id=user.id, wait_seconds=0.5)
  if not cancelled:
    active = active_project_run(project_id, user_id=user.id)
    return {
      "cancelled": False,
      "cancel_requested": False,
      "stopped": active is None,
      "active_run": active,
    }
  return {
    "cancelled": True,
    "cancel_requested": True,
    "stopped": bool(cancelled.get("stopped")),
    "active_run": cancelled,
  }


@app.get("/api/projects/{project_id}/generate/status")
def project_generation_status(
  project_id: str,
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  active = active_project_run(project_id, user_id=user.id)
  return {
    "active": active is not None,
    "stopped": active is None,
    "active_run": active,
  }


@app.get("/api/v1/events/schema")
def v1_events_schema() -> dict[str, Any]:
  try:
    from .api.v1.events import event_schema_payload
  except ImportError:
    from api.v1.events import event_schema_payload
  return event_schema_payload()


@app.get("/api/v1/platform/capabilities")
def v1_platform_capabilities() -> dict[str, Any]:
  try:
    from .api.v1.platform import v1_platform_capabilities as load_capabilities
  except ImportError:
    from api.v1.platform import v1_platform_capabilities as load_capabilities
  return load_capabilities()


@app.get("/api/v1/platform/memory/patterns")
def v1_platform_memory_patterns(
  domain: str | None = None,
  module: str | None = None,
  pattern_type: str | None = None,
  limit: int = 25,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .api.v1.platform_memory import v1_platform_memory_patterns as load_patterns
  except ImportError:
    from api.v1.platform_memory import v1_platform_memory_patterns as load_patterns
  return load_patterns(
    context.store,
    domain=domain,
    module=module,
    pattern_type=pattern_type,
    limit=limit,
  )


@app.post("/api/v1/platform/memory/migrate-legacy-episodes")
def v1_migrate_legacy_episodes(
  project_id: str,
  chat_session_id: str,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .agents.memory.legacy_episodic import migrate_legacy_episodic_items_to_episodes
  except ImportError:
    from agents.memory.legacy_episodic import migrate_legacy_episodic_items_to_episodes

  if not project_id.strip() or not chat_session_id.strip():
    from fastapi import HTTPException

    raise HTTPException(status_code=400, detail="project_id and chat_session_id are required.")
  project = context.store.get_project(project_id, user)
  if not project:
    from fastapi import HTTPException

    raise HTTPException(status_code=404, detail="Project not found.")
  return migrate_legacy_episodic_items_to_episodes(
    context.store,
    user,
    project_id=project_id.strip(),
    chat_session_id=chat_session_id.strip(),
  )


@app.post("/api/v1/runs/stream")
async def v1_runs_stream(
  request: V1CreateRunRequest,
  http_request: Request,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> StreamingResponse:
  try:
    from .api.v1.runs import v1_runs_stream_events
  except ImportError:
    from api.v1.runs import v1_runs_stream_events

  headers = getattr(http_request, "headers", {})
  system_name = headers.get("x-worktual-system-name") if hasattr(headers, "get") else None
  _ensure_update_workspace_access(
    project_id=request.workspace_id.strip(),
    prompt=request.prompt.strip(),
    workspace_access=request.workspace_access,
    context=context,
    user=user,
  )

  return StreamingResponse(
    v1_runs_stream_events(
      request,
      context,
      user,
      run_generation_pipeline=run_generation_pipeline,
      system_name=system_name,
    ),
    media_type="application/x-ndjson",
  )


@app.post("/api/v1/runs/cancel")
def v1_runs_cancel(
  request: CancelRunRequest,
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    from .api.v1.runs import cancel_v1_run
  except ImportError:
    from api.v1.runs import cancel_v1_run

  return cancel_v1_run(request.workspace_id, user, run_id=request.run_id)


@app.post("/api/projects/{project_id}/build-preview")
def build_preview(
  project_id: str,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    version = build_project_preview(context.store, project_id, user, context.settings)
    return {"version": version}
  except (PreviewRuntimeError, StorageError) as exc:
    raise storage_http_error(exc)


@app.post("/api/projects/{project_id}/dev-preview")
def start_dev_preview(
  project_id: str,
  request: Request,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    payload = start_project_dev_preview(
      context.store,
      project_id,
      user,
      app_root=context.settings.app_root,
      public_base_url=context.settings.backend_public_base_url,
      request_host=request.headers.get("host"),
    )
    return payload
  except PreviewRuntimeError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/projects/{project_id}/dev-preview")
def stop_dev_preview_route(
  project_id: str,
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  stop_dev_preview(project_id)
  return {"status": "stopped", "project_id": project_id}


@app.get("/api/projects/{project_id}/versions/{version_id}")
def get_version(
  project_id: str,
  version_id: str,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    version = context.store.get_version(project_id, version_id, user)
  except StorageError as exc:
    raise storage_http_error(exc)
  if not version:
    raise HTTPException(status_code=404, detail="Version not found.")
  return {"version": version}


@app.get("/api/events")
def list_events(
  project_id: Optional[str] = None,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  try:
    return {"events": context.store.list_events(user, project_id=project_id)}
  except StorageError as exc:
    raise storage_http_error(exc)


@app.get("/api/previews/{project_id}/{version_id}/{asset_path:path}")
@app.get("/api/previews/{project_id}/{version_id}/")
def serve_preview(
  project_id: str,
  version_id: str,
  asset_path: str = "",
  context: AppContext = Depends(get_context),
):
  try:
    file_path, content_type = resolve_preview_file(context.settings.app_root, project_id, version_id, asset_path)
    if content_type == "text/html":
      return HTMLResponse(
        rewrite_preview_html(
          file_path.read_text(encoding="utf-8"),
          project_id=project_id,
          version_id=version_id,
        ),
        headers=PREVIEW_RESPONSE_HEADERS,
      )
    return FileResponse(file_path, media_type=content_type, headers=PREVIEW_RESPONSE_HEADERS)
  except PreviewRuntimeError as exc:
    raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/automation-tests")
def list_project_automation_tests(
  project_id: str,
  chat_session_id: Optional[str] = None,
  limit: int = 50,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  return list_automation_tests_payload(
    context.store,
    user,
    project_id=project_id,
    chat_session_id=chat_session_id,
    limit=limit,
  )


@app.get("/api/projects/{project_id}/automation-tests/{test_run_id}")
def get_project_automation_test(
  project_id: str,
  test_run_id: str,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
  return automation_test_detail_payload(
    context.store,
    user,
    project_id=project_id,
    test_run_id=test_run_id,
  )


@app.get("/api/screenshots/{artifact_id}")
def serve_automation_screenshot(
  artifact_id: str,
  context: AppContext = Depends(get_context),
  user: UserContext = Depends(get_current_user),
):
  path = resolve_screenshot_file(context.store, context.settings, user, artifact_id=artifact_id)
  return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@app.post("/api/generate")
def legacy_generate(request: GenerateRequest) -> dict[str, Any]:
  status, payload = generate_website_or_error(request.prompt)
  if status >= 400:
    raise HTTPException(status_code=status, detail=payload.get("error", "Generation failed."))
  return payload


def run() -> None:
  print(f"Vibe Platform backend running at http://{HOST}:{PORT}")
  print("Set DATABASE_URL before starting the local platform APIs.")
  uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
  run()
