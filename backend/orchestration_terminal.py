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


def _print_path_list(label: str, paths: Any, *, max_items: int = 40) -> None:
  if not isinstance(paths, list) or not paths:
    return
  print(f"   {label}:", flush=True)
  for path in paths[:max_items]:
    if str(path or "").strip():
      print(f"      • {path}", flush=True)
  extra = max(len(paths) - max_items, 0)
  if extra:
    print(f"      • +{extra} more", flush=True)


def _print_workspace_detail(detail: dict[str, Any], *, include_inputs: bool = False, include_outputs: bool = True) -> None:
  workspace = detail.get("workspace") if isinstance(detail.get("workspace"), dict) else detail
  if not isinstance(workspace, dict):
    return
  folder = workspace.get("folder")
  mode = workspace.get("workspace_mode")
  intent = workspace.get("intent")
  input_count = workspace.get("input_file_count")
  generated_count = workspace.get("generated_file_count")
  if folder or mode:
    print(
      "   workspace:"
      + (f" mode={mode}" if mode else "")
      + (f" folder={folder}" if folder else "")
      + (f" intent={intent}" if intent else ""),
      flush=True,
    )
  if input_count not in (None, ""):
    print(f"   input files: {input_count}", flush=True)
  if generated_count not in (None, ""):
    print(f"   generated files: {generated_count}", flush=True)
  if include_inputs:
    _print_path_list("input paths", workspace.get("resolved_input_paths") or workspace.get("input_paths"))
  if include_outputs:
    _print_path_list("output paths", workspace.get("resolved_generated_paths") or workspace.get("generated_paths"))


def _line_text(detail: dict[str, Any]) -> str:
  start_line = detail.get("start_line") or detail.get("line") or detail.get("function_line")
  end_line = detail.get("end_line")
  if start_line and end_line and end_line != start_line:
    return f"L{start_line}-{end_line}"
  if start_line:
    return f"L{start_line}"
  return ""


def _function_text(detail: dict[str, Any]) -> str:
  function_name = (
    detail.get("function_name")
    or detail.get("function")
    or detail.get("component")
    or detail.get("symbol")
  )
  if not function_name:
    return ""
  function_line = detail.get("function_line")
  if function_line:
    return f"{function_name}@L{function_line}"
  return str(function_name)


def _print_modification_targets(targets: Any, *, max_items: int = 12) -> None:
  if not isinstance(targets, list) or not targets:
    return
  print("   targets:", flush=True)
  for target in targets[:max_items]:
    if not isinstance(target, dict):
      continue
    path = str(target.get("path") or "").strip()
    if not path:
      continue
    line = _line_text(target)
    function = _function_text(target)
    reason = _short(target.get("reason") or target.get("text") or "", max_chars=180)
    location = " ".join(part for part in (line, f"fn={function}" if function else "") if part)
    print(
      f"      • {path}"
      + (f" {location}" if location else "")
      + (f" — {reason}" if reason else ""),
      flush=True,
    )
  extra = max(len(targets) - max_items, 0)
  if extra:
    print(f"      • +{extra} more", flush=True)


def print_orchestration_event(event: dict[str, Any]) -> None:
  if not orchestration_terminal_enabled():
    return

  step = str(event.get("step") or "")
  status = str(event.get("status") or "running")
  message = str(event.get("message") or "")
  detail = event.get("detail") if isinstance(event.get("detail"), dict) else {}

  # User / model conversation
  if step == "generation.user_prompt":
    try:
      from backend.agents.prompt_context import current_user_prompt
    except ImportError:
      from agents.prompt_context import current_user_prompt
    _banner("USER QUERY")
    print(_short(current_user_prompt(message), max_chars=2000), flush=True)
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

  if step == "workspace.files.loaded":
    count = detail.get("input_file_count") or 0
    folder = detail.get("folder") or ""
    print(f"📂 Workspace loaded: {count} file(s)" + (f" from {folder}" if folder else ""), flush=True)
    _print_workspace_detail(detail, include_inputs=True, include_outputs=False)
    return

  if step == "scope.resolved":
    request_kind = detail.get("request_kind") or "update"
    mode = detail.get("update_mode") or ""
    source = detail.get("preflight_source") or ""
    candidates = detail.get("candidate_files") or []
    print(
      f"🎯 Update target selection: {request_kind}"
      + (f" mode={mode}" if mode else "")
      + (f" source={source}" if source else ""),
      flush=True,
    )
    if detail.get("scope_rationale"):
      print(f"   reason: {_short(detail.get('scope_rationale'), max_chars=220)}", flush=True)
    if detail.get("interaction_summary"):
      print(f"   interaction: {_short(detail.get('interaction_summary'), max_chars=220)}", flush=True)
    if detail.get("project_ui_match_count") not in (None, "", 0):
      matched = ", ".join(str(path) for path in (detail.get("project_ui_matched_files") or [])[:6])
      print(
        f"   rendered UI matches: {detail.get('project_ui_match_count')}"
        + (f" ({matched})" if matched else ""),
        flush=True,
      )
    _print_modification_targets(detail.get("modification_targets"))
    if not detail.get("modification_targets"):
      _print_path_list("candidate files", candidates, max_items=12)
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
    line_suffix = f" {_line_text(detail)}" if _line_text(detail) else ""
    function = _function_text(detail)
    if function:
      line_suffix += f" fn={function}"
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
  if step == "files.missing":
    print(f"✗ FAILED {step}: {_short(message or 'No generated files returned')}", flush=True)
    _print_workspace_detail(detail, include_inputs=True, include_outputs=True)
    return

  if step in {"files.persisting", "files.persisted", "files.materialized"}:
    paths = detail.get("paths") or []
    count = detail.get("file_count") or len(paths)
    local = detail.get("local_sync") or {}
    local_path = local.get("path") or ""
    print(f"💾 {message} ({count} file(s))" + (f" → {local_path}" if local_path else ""), flush=True)
    _print_workspace_detail(detail, include_inputs=count == 0, include_outputs=True)
    if paths and step == "files.persisted" and not (
      isinstance(detail.get("workspace"), dict)
      and (detail["workspace"].get("resolved_generated_paths") or detail["workspace"].get("generated_paths"))
    ):
      _print_path_list("saved paths", paths, max_items=6)
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
  try:
    from backend.agents.prompt_context import current_user_prompt
  except ImportError:
    from agents.prompt_context import current_user_prompt
  _banner("USER QUERY")
  print(_short(current_user_prompt(prompt), max_chars=4000), flush=True)


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
