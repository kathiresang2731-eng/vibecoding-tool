from __future__ import annotations

import json
import os
from typing import Any


def orchestration_terminal_enabled() -> bool:
  value = os.getenv("WORKTUAL_ORCHESTRATION_TERMINAL", "1").strip().lower()
  return value not in {"0", "false", "no", "off"}


def _short(value: Any, *, max_chars: int = 320) -> str:
  text = " ".join(str(value).split())
  if len(text) <= max_chars:
    return text
  return f"{text[: max_chars - 3]}..."


def _detail_block(detail: dict[str, Any] | None, *, keys: tuple[str, ...]) -> str:
  if not isinstance(detail, dict):
    return ""
  parts = [f"{key}={_short(detail[key], max_chars=120)}" for key in keys if detail.get(key) not in (None, "", [], {})]
  return " | ".join(parts)


def _banner(label: str) -> None:
  line = "─" * 72
  print(f"\n{line}\n{label}\n{line}", flush=True)


def print_orchestration_event(event: dict[str, Any]) -> None:
  if not orchestration_terminal_enabled():
    return

  step = str(event.get("step") or "")
  status = str(event.get("status") or "running")
  message = str(event.get("message") or "")
  detail = event.get("detail") if isinstance(event.get("detail"), dict) else {}

  # User / model conversation
  if step == "generation.user_prompt":
    _banner("USER QUERY")
    print(_short(message, max_chars=2000), flush=True)
    return

  if step == "assistant.delta":
    chunk = str(detail.get("delta") or message)
    if chunk.strip():
      print(f"[Model] {_short(chunk, max_chars=500)}", flush=True)
    return

  if step in {"orchestrator.starting", "agent.run.started"}:
    print(f"\n▶ Orchestrator: {message}", flush=True)
    return

  if step == "agent.decision":
    workflow = detail.get("workflow") or detail.get("intent")
    extra = _detail_block(detail, keys=("workflow", "selected_agents", "specialists_skipped", "task_count", "wave_count"))
    print(f"◆ Decision: {message}" + (f" ({extra})" if extra else ""), flush=True)
    return

  if step == "route.intent":
    print(
      f"◆ Intent routing: intent={detail.get('intent')} next={detail.get('next_action')} tool={detail.get('next_tool')}",
      flush=True,
    )
    return

  # Parallel workers / waves
  if step == "agent.parallel.plan":
    tasks = detail.get("task_count") or len(detail.get("tasks") or [])
    waves = detail.get("wave_count") or len(detail.get("waves") or [])
    print(f"\n▶ Parallel plan: {tasks} task(s), {waves} wave(s)", flush=True)
    if detail.get("tasks"):
      for task in detail["tasks"][:8]:
        paths = ", ".join(task.get("paths") or [])
        scope = task.get("scope") or task.get("kind") or "file"
        print(f"   • {task.get('id')}: [{scope}] {paths}", flush=True)
    return

  if step == "agent.parallel.wave.started":
    wave = detail.get("wave") or "?"
    count = len(detail.get("task_ids") or [])
    print(f"\n▶ Wave {wave} started — {count} worker(s) in parallel", flush=True)
    return

  if step == "agent.parallel.wave.completed":
    wave = detail.get("wave") or "?"
    results = detail.get("results") or []
    summary = ", ".join(f"{item.get('task_id')}:{item.get('status')}" for item in results[:6])
    print(f"✓ Wave {wave} finished — {summary}", flush=True)
    return

  if step.startswith("agent.worker."):
    agent = detail.get("agent") or detail.get("parallel_worker") or "worker"
    paths = detail.get("paths") or []
    path_text = ", ".join(paths[:4])
    print(f"  [{status}] {agent}: {message}" + (f" → {path_text}" if path_text else ""), flush=True)
    return

  if step == "agent.fallback.brand_rename":
    paths = ", ".join(detail.get("paths") or [])
    target = detail.get("target") or "?"
    print(f"⚡ Brand rename fallback → {target} in [{paths}]", flush=True)
    return

  # Tool loop
  if step.startswith("tool."):
    tool = detail.get("tool") or step.replace("tool.", "")
    path = detail.get("path") or ""
    agent = detail.get("agent") or detail.get("parallel_worker") or ""
    start_line = detail.get("start_line")
    end_line = detail.get("end_line")
    added = detail.get("added")
    removed = detail.get("removed")
    line_suffix = ""
    if start_line and end_line:
      line_suffix = f" L{start_line}-{end_line}"
    elif start_line:
      line_suffix = f" L{start_line}"
    if added is not None or removed is not None:
      line_suffix += f" (+{added or 0}/-{removed or 0})"
    prefix = f"[Tool:{tool}]"
    if agent:
      prefix = f"[{agent} → {tool}]"
    print(f"  {prefix} {path or message}{line_suffix}", flush=True)
    return

  if step == "tool.requested":
    tool = detail.get("tool") or "?"
    step_no = detail.get("step") or "?"
    print(f"  [Tool request step {step_no}] {tool}", flush=True)
    return

  # Agent-to-agent / shared memory
  if step == "agent.a2a.message":
    sender = detail.get("from_agent") or detail.get("from_task") or "agent"
    receiver = detail.get("to_agent") or "orchestrator"
    summary = _short(detail.get("summary") or message)
    paths = ", ".join(detail.get("paths_changed") or [])
    print(f"↔ A2A {sender} → {receiver}: {summary}" + (f" [{paths}]" if paths else ""), flush=True)
    return

  # Persistence / local sync
  if step in {"files.persisting", "files.persisted", "files.materialized"}:
    paths = detail.get("paths") or []
    count = detail.get("file_count") or len(paths)
    local = detail.get("local_sync") or {}
    local_path = local.get("path") or ""
    print(f"💾 {message} ({count} file(s))" + (f" → {local_path}" if local_path else ""), flush=True)
    if paths and step == "files.persisted":
      for path in paths[:6]:
        print(f"   • {path}", flush=True)
      extra = max(len(paths) - 6, 0)
      if extra:
        print(f"   • +{extra} more", flush=True)
    return

  if step.startswith("local.sync"):
    count = detail.get("count") or detail.get("file_count") or "?"
    path = detail.get("path") or detail.get("path_written") or ""
    print(f"📁 Local sync {step.split('.')[-1]}: {message}" + (f" ({path})" if path else ""), flush=True)
    return

  # Validation / completion
  if step in {"streaming.file_agent.completed", "agent.runtime.loop.completed", "orchestrator.completed"}:
    changed = detail.get("changed_paths") or []
    tools = detail.get("tool_call_count")
    suffix = ""
    if changed:
      suffix = f" — changed: {', '.join(changed[:5])}"
    if tools is not None:
      suffix += f" ({tools} tool calls)"
    print(f"\n✓ {message}{suffix}", flush=True)
    return

  if step == "gate.passed" or step == "error.diagnosed":
    print(f"  [{step}] {message}", flush=True)
    return

  if status == "failed" or ".failed" in step:
    err = detail.get("error") or detail.get("raw_error") or message
    print(f"✗ FAILED {step}: {_short(err)}", flush=True)
    return

  # Stage markers (orchestration pipeline)
  if step.startswith("stage.") and step.endswith(".started"):
    stage = step.replace("stage.", "").replace(".started", "")
    print(f"\n▶ Stage: {stage.replace('_', ' ')}", flush=True)
    return

  if step.startswith("stage.") and step.endswith(".completed"):
    stage = step.replace("stage.", "").replace(".completed", "")
    duration = detail.get("duration_ms")
    suffix = f" ({duration}ms)" if duration else ""
    print(f"✓ Stage complete: {stage.replace('_', ' ')}{suffix}", flush=True)
    return

  # Generic progress for important steps only
  important_prefixes = (
    "agent.",
    "orchestrator.",
    "plan.",
    "streaming.",
    "file.",
    "generation.",
    "route.",
  )
  if any(step.startswith(prefix) for prefix in important_prefixes):
    extra = _detail_block(detail, keys=("intent", "engine", "workflow", "model"))
    if message:
      print(f"  · {step}: {_short(message)}" + (f" | {extra}" if extra else ""), flush=True)


def print_user_query(prompt: str) -> None:
  if not orchestration_terminal_enabled():
    return
  _banner("USER QUERY")
  print(_short(prompt, max_chars=4000), flush=True)


def print_routing_result(routing: dict[str, Any]) -> None:
  if not orchestration_terminal_enabled():
    return
  print(
    f"\n◆ Intent Router → intent={routing.get('intent')} "
    f"action={routing.get('next_action')} tool={routing.get('next_tool')}",
    flush=True,
  )
  if routing.get("reasoning"):
    print(f"   Reason: {_short(routing['reasoning'])}", flush=True)


def print_a2a_messages(messages: list[dict[str, Any]]) -> None:
  if not orchestration_terminal_enabled() or not messages:
    return
  print("\n↔ Agent-to-agent messages:", flush=True)
  for msg in messages[-8:]:
    sender = msg.get("from_agent") or msg.get("from_task") or "?"
    receiver = msg.get("to_agent") or "orchestrator"
    summary = _short(msg.get("summary") or "")
    paths = ", ".join(msg.get("paths_changed") or [])
    print(f"   {sender} → {receiver}: {summary}" + (f" [{paths}]" if paths else ""), flush=True)
