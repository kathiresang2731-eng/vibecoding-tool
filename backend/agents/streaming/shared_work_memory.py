from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any


_EXPORT_RE = re.compile(
  r"export\s+(?:default\s+)?(?:function|const|class)\s+(\w+)",
  re.MULTILINE,
)


@dataclass
class SharedWorkMemory:
  """Thread-safe workspace snapshot + agent-to-agent messages for parallel file workers."""

  project_id: str
  files: dict[str, str] = field(default_factory=dict)
  messages: list[dict[str, Any]] = field(default_factory=list)
  _lock: threading.RLock = field(default_factory=threading.Lock, repr=False)

  def snapshot_files(self) -> dict[str, str]:
    with self._lock:
      return dict(self.files)

  def get_file(self, path: str) -> str:
    with self._lock:
      return str(self.files.get(path) or "")

  def update_file(self, path: str, content: str) -> None:
    with self._lock:
      self.files[path] = content

  def publish_staged(
    self,
    *,
    task_id: str,
    agent_label: str,
    path: str,
    note: str = "Applied staged edit",
  ) -> None:
    with self._lock:
      self.messages.append(
        {
          "sequence": len(self.messages) + 1,
          "from_task": task_id,
          "from_agent": agent_label,
          "to_agent": "co-workers",
          "status": "in_progress",
          "paths_changed": [path],
          "summary": note[:400],
          "protocol": "worktual-parallel-a2a-v1",
        }
      )

  def publish_completion(
    self,
    *,
    task_id: str,
    agent_label: str,
    paths: list[str],
    summary: str,
    status: str = "completed",
  ) -> dict[str, Any]:
    exports: dict[str, list[str]] = {}
    with self._lock:
      for path in paths:
        content = self.files.get(path, "")
        names = _EXPORT_RE.findall(content)
        if names:
          exports[path] = names[:8]
      message = {
        "sequence": len(self.messages) + 1,
        "from_task": task_id,
        "from_agent": agent_label,
        "to_agent": "Parallel File Orchestrator",
        "status": status,
        "paths_changed": list(paths),
        "summary": summary[:1200],
        "exports": exports,
        "protocol": "worktual-parallel-a2a-v1",
      }
      self.messages.append(message)
      return message

  def context_for_task(self, *, task_id: str, depends_on: list[str], include_coworkers: bool = True) -> str:
    with self._lock:
      if not self.messages:
        return ""
      if depends_on:
        relevant = [msg for msg in self.messages if msg.get("from_task") in depends_on]
      elif include_coworkers:
        relevant = [msg for msg in self.messages if msg.get("from_task") != task_id]
      else:
        relevant = list(self.messages)
      if not relevant:
        relevant = self.messages[-6:]
      blocks: list[str] = [
        "## Shared agent memory (co-worker agents — respect these exports and paths)",
      ]
      for msg in relevant[-12:]:
        paths = ", ".join(msg.get("paths_changed") or [])
        exports = msg.get("exports") or {}
        export_line = ""
        if exports:
          parts = [f"{path}: {', '.join(names)}" for path, names in exports.items()]
          export_line = f" Exports: {'; '.join(parts)}."
        status = str(msg.get("status") or "updated")
        blocks.append(
          f"- [{msg.get('from_agent')}] ({status}) {paths}: {msg.get('summary') or 'updated'}{export_line}"
        )
      blocks.append(f"(Your task id: {task_id})")
      return "\n".join(blocks)

  def to_dict(self) -> dict[str, Any]:
    with self._lock:
      return {
        "project_id": self.project_id,
        "file_count": len(self.files),
        "message_count": len(self.messages),
        "messages": list(self.messages),
      }
