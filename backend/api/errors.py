from __future__ import annotations

from fastapi import HTTPException


def storage_http_error(exc: Exception) -> HTTPException:
  message = str(exc)
  lowered = message.lower()
  if "not found" in lowered:
    return HTTPException(status_code=404, detail=message)
  if "access" in lowered:
    return HTTPException(status_code=403, detail=message)
  if "unsafe" in lowered or "allowed" in lowered:
    return HTTPException(status_code=400, detail=message)
  return HTTPException(status_code=503, detail=message)

