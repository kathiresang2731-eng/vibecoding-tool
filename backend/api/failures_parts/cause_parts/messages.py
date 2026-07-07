from __future__ import annotations


def failure_cause_label(category: str) -> str:
  return {
    "local_control_model": "local GPT control model unavailable",
    "gemini_generation": "Gemini generation provider failed",
    "artifact_validation": "artifact validation failed",
    "preview_build": "staged preview build failed",
    "visual_qa": "visual QA failed",
    "storage": "project storage failed",
    "local_sync": "local workspace sync failed",
    "model_connection": "model connection failed",
    "routing": "intent routing failed before generation started",
    "agent_runtime_timeout": "agent runtime timed out",
    "update_clarification": "the update request needs clarification",
    "scoped_update_guard": "the scoped update was blocked to preserve the existing website",
  }.get(category, "backend generation failed")


def provider_from_failure_category(category: str) -> str | None:
  if category == "local_control_model":
    return "local-gpt"
  if category == "gemini_generation":
    return "gemini"
  if category == "model_connection":
    return "unknown-model"
  if category == "routing":
    return "control-model"
  return None

