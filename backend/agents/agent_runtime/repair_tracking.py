from __future__ import annotations

import hashlib
import re
from typing import Any


def repair_failure_signature(reason: Any) -> str:
  text = " ".join(str(reason or "").lower().split())
  text = re.sub(r'"/[^"]+"', '"/path"', text)
  text = re.sub(r"'/[^']+'", "'/path'", text)
  text = re.sub(r"/[^\s:()]+", "/path", text)
  text = re.sub(r"\b[0-9a-f]{8,}\b", "<id>", text)
  text = re.sub(r"\d+\.\d+s|\d+ms|\d+s", "<duration>", text)
  text = text[:1200]
  return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def record_repair_error(state: dict[str, Any], reason: Any, *, source: str = "") -> dict[str, Any]:
  reason_text = str(reason or "Unknown repair error.")
  state.setdefault("repair_errors", []).append(reason_text)
  signature = repair_failure_signature(reason_text)
  signature_counts = state.setdefault("repair_failure_signatures", {})
  next_count = int(signature_counts.get(signature) or 0) + 1
  signature_counts[signature] = next_count
  state["latest_repair_failure_signature"] = signature
  if source:
    state["latest_repair_failure_source"] = source
  return {"signature": signature, "count": next_count, "source": source}


def mark_repair_attempt_for_error(state: dict[str, Any], reason: Any, *, agent: str) -> dict[str, Any]:
  signature = repair_failure_signature(reason)
  attempted = state.setdefault("repair_attempted_signatures", {})
  previous_count = int(attempted.get(signature) or 0)
  attempted[signature] = previous_count + 1
  return {
    "signature": signature,
    "already_attempted": previous_count > 0,
    "attempt_count": previous_count + 1,
    "agent": agent,
  }
