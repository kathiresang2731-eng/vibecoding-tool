from __future__ import annotations


def local_control_failure_marker(lowered_error: str) -> bool:
  return any(
    marker in lowered_error
    for marker in (
      "local control model",
      "local gpt",
      "local model provider",
      "local model endpoint",
    )
  )


def gemini_artifact_failure_marker(lowered_error: str) -> bool:
  artifact_markers = (
    "code artifact validation failed",
    "generate_website_artifact",
    "update_website_artifact",
    "repair_website_artifact",
    "artifact model call",
    "gemini network error",
  )
  connection_markers = ("connection", "network", "timeout", "timed out")
  return any(marker in lowered_error for marker in artifact_markers) and any(marker in lowered_error for marker in connection_markers)

