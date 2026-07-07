from __future__ import annotations

V1_EVENT_TYPES: tuple[str, ...] = (
  "run.created",
  "run.progress",
  "run.heartbeat",
  "run.completed",
  "run.failed",
  "run.cancelled",
  "tool.requested",
  "tool.completed",
  "tool.failed",
  "patch.proposed",
  "patch.applied",
  "approval.required",
  "approval.resolved",
  "gate.started",
  "gate.passed",
  "gate.failed",
  "terminal.output",
  "context.search.completed",
)

_LEGACY_TOOL_STEPS = {
  "tool.requested",
  "tool.completed",
  "tool.failed",
}
