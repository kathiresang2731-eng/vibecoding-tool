from __future__ import annotations

from typing import Any

from .errors import StorageError
from .roles import READ_ROLES, WRITE_ROLES
from .user import UserContext


def require_project(store: Any, project_id: str, user: UserContext) -> dict[str, Any]:
  project = store.get_project(project_id, user)
  if not project:
    raise StorageError("Project not found.")
  return project


def require_write(user: UserContext) -> None:
  if user.role not in WRITE_ROLES:
    raise StorageError("User does not have write access.")


def ensure_project_read(user: UserContext, project: dict[str, Any]) -> None:
  if user.role == "admin":
    return
  if user.role in READ_ROLES and project.get("owner_user_id") == user.id:
    return
  raise StorageError("User does not have access to this project.")


def ensure_project_write(user: UserContext, project: dict[str, Any]) -> None:
  if user.role == "admin":
    return
  if user.role in WRITE_ROLES and project.get("owner_user_id") == user.id:
    return
  raise StorageError("User does not have write access to this project.")
