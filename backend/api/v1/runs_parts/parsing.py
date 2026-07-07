from __future__ import annotations


def _normalize_client(client: str | None) -> str:
  normalized = str(client or "web").strip().lower()
  if normalized in {"web", "cli", "ide"}:
    return normalized
  return "web"

