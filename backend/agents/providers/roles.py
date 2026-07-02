from __future__ import annotations

from typing import Any

from .constants import ARTIFACT_PROVIDER_ROLE, CONTROL_PROVIDER_ROLE, DUAL_PROVIDER_ROLE
from .errors import ProviderRoleError


def assert_provider_role(provider: Any, required_role: str) -> None:
  if provider is None:
    raise ProviderRoleError(f"{required_role} provider is required.")
  roles = provider_role_values(provider)
  if required_role not in roles:
    name = provider_display_name(provider)
    declared = ", ".join(sorted(roles)) if roles else "none"
    raise ProviderRoleError(
      f"{required_role} provider {name} is not allowed for this call path. "
      f"Declared provider roles: {declared}."
    )


def provider_role_values(provider: Any) -> set[str]:
  raw_roles = getattr(provider, "provider_roles", None)
  if raw_roles is None:
    raw_roles = getattr(provider, "provider_role", None)
  roles = normalize_provider_roles(raw_roles)
  return roles


def normalize_provider_roles(raw_roles: Any) -> set[str]:
  if raw_roles is None:
    return set()
  if isinstance(raw_roles, str):
    normalized = raw_roles.strip().lower()
    if normalized in {DUAL_PROVIDER_ROLE, "both", "dual", "*"}:
      return {CONTROL_PROVIDER_ROLE, ARTIFACT_PROVIDER_ROLE}
    return {normalized} if normalized else set()
  if isinstance(raw_roles, (list, tuple, set)):
    normalized: set[str] = set()
    for raw_role in raw_roles:
      normalized.update(normalize_provider_roles(raw_role))
    return normalized
  return set()


def provider_display_name(provider: Any) -> str:
  name = getattr(provider, "name", None)
  if isinstance(name, str) and name.strip():
    return name.strip()
  return provider.__class__.__name__ if provider is not None else "unknown"
