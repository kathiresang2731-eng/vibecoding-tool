from __future__ import annotations

from fastapi import HTTPException

from ..constants import SUPPORTED_GENERATION_MODELS


def normalize_generation_model(model: str | None) -> str | None:
  if not model:
    return None
  cleaned = model.strip()
  if not cleaned or cleaned == "server-default":
    return None
  if cleaned not in SUPPORTED_GENERATION_MODELS:
    raise HTTPException(status_code=400, detail=f"Unsupported generation model: {cleaned}")
  return cleaned

