from __future__ import annotations

from typing import Any


def extract_preview_status_from_generation(generation: dict[str, Any]) -> str | None:
  multi_agent = generation.get("multi_agent_system") if isinstance(generation, dict) else {}
  agentic_runtime = multi_agent.get("agentic_runtime") if isinstance(multi_agent, dict) else {}
  if not isinstance(agentic_runtime, dict):
    return None
  final_output = agentic_runtime.get("final_output")
  if isinstance(final_output, dict):
    preview_status = final_output.get("preview_status")
    if preview_status:
      return str(preview_status)
  visual_qa = agentic_runtime.get("visual_qa")
  if isinstance(visual_qa, dict):
    visual_status = visual_qa.get("status")
    if visual_status == "failed":
      return "visual_qa_failed"
  preview = agentic_runtime.get("preview")
  if isinstance(preview, dict):
    status = preview.get("status")
    if status:
      return str(status)
  build_gate = agentic_runtime.get("build_gate")
  if isinstance(build_gate, dict):
    status = build_gate.get("status")
    if status:
      return str(status)
  return None
