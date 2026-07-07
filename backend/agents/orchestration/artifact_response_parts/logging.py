from __future__ import annotations

from typing import Any

from ..tool_registry import log_tool_call


def log_generated_website_tools(result: dict[str, Any]) -> None:
  generated_website = result["orchestration_flow"]["generated_website"]
  sections = generated_website.get("sections") or []
  files = generated_website.get("files") or []
  intent = result["multi_agent_system"].get("intent")
  is_update = intent == "website_update"
  runtime = result["multi_agent_system"].get("agentic_runtime")
  runtime = runtime if isinstance(runtime, dict) else {}
  runtime_failed = str(runtime.get("status") or "").lower() == "failed"
  validation_status = "failed" if runtime_failed else "prepared"

  log_tool_call(
    "analyze_update_request" if is_update else "analyze_prompt",
    "output",
    {
      "intent": intent,
      "routing_result": result["multi_agent_system"].get("routing_result"),
      "website_title": generated_website.get("title"),
      "section_count": len(sections),
      "project_file_count": runtime.get("project_file_count"),
      "update_scope": runtime.get("update_scope") if is_update else None,
    },
  )
  log_tool_call(
    "generate_update_artifact" if is_update else "generate_website_files",
    "output",
    {
      "file_count": len(files),
      "paths": [file.get("path") for file in files if isinstance(file, dict)],
      "changed_paths": runtime.get("changed_paths") if is_update else None,
      "status": "failed" if runtime_failed else "prepared",
    },
  )
  log_tool_call(
    "validate_generated_website",
    "output",
    {
      "status": validation_status,
      "section_count": len(sections),
      "file_count": len(files),
      "requirement_validation": runtime.get("requirement_validation") if is_update else None,
    },
  )
