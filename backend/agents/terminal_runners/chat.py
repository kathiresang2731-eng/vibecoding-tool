from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from backend.agents.gemini_client.config import load_dotenv
from backend.agents.orchestration.conversation import generate_conversation_response
from backend.agents.orchestration.routing import route_generation_action_tool
from backend.agents.orchestration.state import GenerationPipelineState
from backend.agents.agent_runtime.model_agents import (
  run_planner_agent,
  run_prompt_analyst_agent,
  run_review_agent,
)
from backend.agents.dynamic_agents import create_dynamic_workflow
from backend.agents.memory.episodic import (
  build_episodic_context_block,
  select_episodic_memories_for_prompt,
)
from backend.agents.memory.session_monitor import persist_generation_memory_checkpoint
from backend.agents.providers import GeminiProvider
from backend.agents.project_inspection import build_project_inspection_context
from backend.agents.update_engine.scope_engine import resolve_update_scope
from backend.local_workspace import (
  MAX_LOCAL_FILE_BYTES,
  normalize_project_file_path,
  should_ignore,
)
from backend.local_workspace.content import is_binary_project_asset
from backend.config import load_settings
from backend.agents.terminal_runners.testing_db import (
  TerminalDatabaseContext,
  initialize_terminal_database,
)
from backend.agents.terminal_runners.terminal_logging import (
  configure_terminal_logging,
  log_user_input,
)


PLANNING_INTENTS = {"simple_code", "website_generation", "website_update"}
FILE_PROPOSAL_SCHEMA: dict[str, Any] = {
  "type": "object",
  "properties": {
    "summary": {"type": "string"},
    "files": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "path": {"type": "string"},
          "action": {"type": "string"},
          "purpose": {"type": "string"},
          "planned_changes": {"type": "array", "items": {"type": "string"}},
          "dependencies": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["path", "action", "purpose", "planned_changes", "dependencies"],
      },
    },
  },
  "required": ["summary", "files"],
}


class RecordingProvider:
  """Record structured LLM outputs while preserving the production provider."""

  def __init__(self, provider: Any) -> None:
    self.provider = provider
    self.calls: list[dict[str, Any]] = []

  def generate_json(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
    trace_label = str(kwargs.get("trace_label") or "generate_json")
    response = self.provider.generate_json(prompt, **kwargs)
    self.calls.append(
      {
        "trace_label": trace_label,
        "response": response,
      }
    )
    return response

  def __getattr__(self, name: str) -> Any:
    return getattr(self.provider, name)


def load_terminal_project_files(
  project_path: str | Path | None = None,
) -> tuple[Path | None, list[dict[str, str]]]:
  load_dotenv()
  raw_path = str(project_path or os.getenv("WORKTUAL_TERMINAL_PROJECT_PATH") or "").strip()
  if not raw_path:
    return None, []
  root = Path(raw_path).expanduser().resolve()
  if not root.exists() or not root.is_dir():
    raise ValueError(f"Project path is not a directory: {root}")
  files: list[dict[str, str]] = []
  for path in sorted(root.rglob("*")):
    if not path.is_file() or should_ignore(path, root):
      continue
    relative_path = normalize_project_file_path(path.relative_to(root).as_posix())
    if is_binary_project_asset(relative_path) or path.stat().st_size > MAX_LOCAL_FILE_BYTES:
      continue
    try:
      content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
      continue
    if "\x00" in content:
      continue
    files.append({"path": relative_path, "content": content})
  return root, files


def normalize_file_proposal(
  response: Any,
  *,
  allowed_paths: set[str] | None = None,
) -> dict[str, Any]:
  raw = response if isinstance(response, dict) else {}
  normalized_files: list[dict[str, Any]] = []
  seen: set[str] = set()
  for item in raw.get("files") or []:
    if not isinstance(item, dict):
      continue
    path = str(item.get("path") or "").replace("\\", "/").strip().lstrip("./")
    if not path or path.startswith("/") or ".." in path.split("/") or path in seen:
      continue
    if allowed_paths is not None and path not in allowed_paths:
      continue
    seen.add(path)
    normalized_files.append(
      {
        "path": path,
        "action": str(item.get("action") or "modify").strip(),
        "purpose": str(item.get("purpose") or "").strip(),
        "planned_changes": [
          str(value).strip() for value in item.get("planned_changes") or [] if str(value).strip()
        ],
        "dependencies": [
          str(value).strip() for value in item.get("dependencies") or [] if str(value).strip()
        ],
      }
    )
  return {
    "summary": str(raw.get("summary") or "").strip(),
    "files": normalized_files,
  }


def propose_generation_files(
  provider: RecordingProvider,
  *,
  user_input: str,
  brief: dict[str, Any],
  plan: dict[str, Any],
) -> dict[str, Any]:
  response = provider.generate_json(
    "Create a dry-run project file manifest for this website request.\n"
    "Return paths and responsibilities only. Do not return source code, patches, markdown, "
    "or file contents. Include the complete minimal React/Vite project tree needed to satisfy "
    "the request. Use action=create for every file.\n\n"
    f"USER REQUEST:\n{user_input}\n\n"
    f"BRIEF:\n{json.dumps(brief, ensure_ascii=False)[:16000]}\n\n"
    f"PLAN:\n{json.dumps(plan, ensure_ascii=False)[:12000]}",
    system_instruction="You are the Worktual dry-run file architecture agent. Return strict JSON only.",
    trace_label="dry_run_generation_file_planner",
    response_schema=FILE_PROPOSAL_SCHEMA,
  )
  return normalize_file_proposal(response)


def propose_update_changes(
  provider: RecordingProvider,
  *,
  user_input: str,
  scope: dict[str, Any],
) -> dict[str, Any]:
  allowed = {
    str(path)
    for path in [
      *(scope.get("candidate_files") or []),
      *(scope.get("candidate_new_files") or []),
    ]
    if str(path).strip()
  }
  response = provider.generate_json(
    "Describe the exact dry-run changes planned for the approved update scope.\n"
    "Return paths and change descriptions only. Never return source code, patches, SEARCH/REPLACE "
    "blocks, or full file contents. Use action=modify for existing candidate_files and action=create "
    "for candidate_new_files. Do not include paths outside the approved scope.\n\n"
    f"USER REQUEST:\n{user_input}\n\n"
    f"APPROVED SCOPE:\n{json.dumps(scope, ensure_ascii=False)[:24000]}",
    system_instruction="You are the Worktual dry-run scoped change planner. Return strict JSON only.",
    trace_label="dry_run_update_change_planner",
    response_schema=FILE_PROPOSAL_SCHEMA,
  )
  return normalize_file_proposal(response, allowed_paths=allowed)


def is_targeted_brand_rename(scope: dict[str, Any] | None) -> bool:
  targeted = (scope or {}).get("targeted_patch")
  return (
    isinstance(targeted, dict)
    and str(targeted.get("kind") or "") == "brand_name_update"
    and bool(str(targeted.get("new_value") or "").strip())
  )


def build_brand_rename_proposal(
  *,
  scope: dict[str, Any],
  project_files: list[dict[str, str]],
) -> dict[str, Any]:
  targeted = scope.get("targeted_patch") if isinstance(scope.get("targeted_patch"), dict) else {}
  old_value = str(targeted.get("old_value") or "").strip()
  new_value = str(targeted.get("new_value") or "").strip()
  candidates = {
    str(path)
    for path in [
      *(scope.get("candidate_files") or []),
      *(scope.get("candidate_new_files") or []),
    ]
    if str(path).strip()
  }
  proposed: list[dict[str, Any]] = []
  for item in project_files:
    path = item["path"]
    content = item["content"]
    if path not in candidates:
      continue
    has_old_brand = bool(old_value) and old_value.lower() in content.lower()
    is_document_title = path == "index.html" and "<title" in content.lower()
    if not has_old_brand and not is_document_title:
      continue
    planned_changes = (
      [f"Replace the current HTML document title with '{new_value}'."]
      if is_document_title and not has_old_brand
      else [f"Replace visible brand references from '{old_value}' to '{new_value}'."]
    )
    proposed.append(
      {
        "path": path,
        "action": "modify",
        "purpose": "Update verified website branding from live source evidence.",
        "planned_changes": planned_changes,
        "dependencies": [],
      }
    )
  return {
    "summary": f"Targeted dry-run rename from {old_value or 'the current brand'} to {new_value}.",
    "files": proposed,
    "evidence_policy": "Only files containing the old brand or the live HTML title were included.",
  }


def project_info_result(
  user_input: str,
  routing: dict[str, Any],
  *,
  project_root: Path | None,
  project_files: list[dict[str, str]],
  llm_calls: list[dict[str, Any]],
  provider: RecordingProvider,
) -> dict[str, Any]:
  routing["project_context"] = build_project_inspection_context(
    project_files,
    question=user_input,
    project_name=project_root.name if project_root else "",
    local_path=str(project_root) if project_root else "",
  )
  state = GenerationPipelineState(
    user_prompt=user_input,
    intent="project_info",
    routing_result=routing,
    control_client=provider,
  )
  conversation = generate_conversation_response(state, provider)
  message = str(conversation.get("message") or "")
  return {
    "user_input": user_input,
    "intent": "project_info",
    "routing": routing,
    "llm_calls": llm_calls,
    "execution_mode": "backend_observation_only",
    "process_steps": [
      {
        "step": "intent_routing",
        "agent": "Intent Router Agent",
        "status": "completed",
        "output": routing,
      },
      {
        "step": "read_project_context",
        "agent": "Project Context Agent",
        "status": "completed",
        "output": {
          "root": str(project_root) if project_root else None,
          "file_count": len(project_files),
        },
      },
      {
        "step": "flow_completion",
        "agent": "Supervisor Agent",
        "status": "completed",
      },
    ],
    "project_context": {
      "root": str(project_root) if project_root else None,
      "mode": "read_only",
      "file_count": len(project_files),
      "file_tree": [item["path"] for item in project_files],
    },
    "code_writes_enabled": False,
    "local_workspace_enabled": project_root is not None,
    "assistant_response": message,
    "conversation": conversation,
  }


def run_chat_turn(
  user_input: str,
  provider: RecordingProvider,
  *,
  project_path: str | Path | None = None,
  episodic_memories: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
  provider.calls.clear()
  routing = route_generation_action_tool(user_input, provider)
  intent = str(routing.get("intent") or "")
  project_root, project_files = load_terminal_project_files(project_path)
  memory_block = build_episodic_context_block(
    list(episodic_memories or []),
    prompt=user_input,
  )
  if memory_block:
    routing["episodic_memory_context"] = memory_block

  if intent == "project_info":
    return project_info_result(
      user_input,
      routing,
      project_root=project_root,
      project_files=project_files,
      llm_calls=provider.calls,
      provider=provider,
    )

  result: dict[str, Any] = {
    "user_input": user_input,
    "intent": intent,
    "routing": routing,
    "llm_calls": provider.calls,
    "execution_mode": "backend_observation_only",
    "process_steps": [
      {
        "step": "intent_routing",
        "agent": "Intent Router Agent",
        "status": "completed",
        "output": routing,
      }
    ],
    "code_writes_enabled": False,
    "local_workspace_enabled": False,
  }
  if intent in PLANNING_INTENTS:
    if intent == "website_update":
      if project_root is None:
        raise ValueError(
          "website_update requires a loaded project. Use /project /absolute/path/to/project "
          "or start with --project-path."
        )
    read_result = {
      "status": "not_requested",
      "files": project_files,
      "file_index": [{"path": item["path"]} for item in project_files[:240]],
      "file_count": len(project_files),
      "source": "terminal_local_project_read_only" if project_root else "backend_observation_only",
    }
    empty_memory_result = {
      "status": "loaded",
      "memories": list(episodic_memories or []),
      "source": "vibe_builder_testing",
    }
    update_scope: dict[str, Any] | None = None
    if intent == "website_update":
      resolved_scope = resolve_update_scope(
        prompt=user_input,
        project_files=project_files,
        control_provider=provider,
        project_id="terminal-dry-run",
        project_name=project_root.name if project_root else "",
      )
      update_scope = resolved_scope.to_update_analysis()
      result["project_context"] = {
        "root": str(project_root),
        "mode": "read_only",
        "file_count": len(project_files),
        "file_tree": [item["path"] for item in project_files],
      }
      result["update_scope"] = update_scope
      result["process_steps"].append(
        {
          "step": "update_scope_resolution",
          "agent": "Update Analysis Agent",
          "status": "completed",
          "output": update_scope,
        }
      )
      if is_targeted_brand_rename(update_scope):
        file_proposal = build_brand_rename_proposal(
          scope=update_scope,
          project_files=project_files,
        )
        result["file_proposal"] = file_proposal
        result["process_steps"].extend(
          [
            {
              "step": "exact_source_evidence",
              "agent": "Targeted Update Agent",
              "status": "completed",
              "output": file_proposal,
            },
            {
              "step": "write_policy",
              "agent": "Commit Agent",
              "status": "dry_run",
              "reason": "Verified rename proposals were returned without writing files.",
            },
            {
              "step": "flow_completion",
              "agent": "Supervisor Agent",
              "status": "completed",
              "reason": "Targeted brand rename dry run completed.",
            },
          ]
        )
        paths = [item["path"] for item in file_proposal["files"]]
        result["assistant_response"] = (
          "Targeted rename dry run completed. Verified files: "
          f"{', '.join(paths) or 'none'}. No code was generated or written."
        )
        return result

    brief = run_prompt_analyst_agent(
      provider,
      user_input,
      routing,
      read_result,
      empty_memory_result,
    )
    result["brief"] = brief
    result["process_steps"].append(
      {
        "step": "request_analysis",
        "agent": "Prompt Analyst Agent",
        "status": "completed",
        "output": brief,
      }
    )

    dynamic_workflow = create_dynamic_workflow(
      user_input,
      routing_result=routing,
      brief=brief,
      provider=provider,
    )
    result["dynamic_workflow"] = dynamic_workflow
    result["process_steps"].append(
      {
        "step": "dynamic_workflow_planning",
        "agent": "Agent Registry and Task Decomposer Agents",
        "status": "completed",
        "output": dynamic_workflow,
      }
    )

    plan = run_planner_agent(
      provider,
      user_input,
      brief,
      {"execution_mode": "backend_observation_only"},
      empty_memory_result,
    )
    result["plan"] = plan
    review_state = {"brief": brief, "plan": plan}
    ux_review = run_review_agent(
      provider,
      trace_label="ux_review_agent",
      system_instruction="You are the Worktual UX review agent. Review the proposed plan only and return strict JSON.",
      prompt=user_input,
      state=review_state,
    )
    accessibility_review = run_review_agent(
      provider,
      trace_label="accessibility_review_agent",
      system_instruction="You are the Worktual accessibility review agent. Review the proposed plan only and return strict JSON.",
      prompt=user_input,
      state=review_state,
    )
    result["reviews"] = {
      "ux": ux_review,
      "accessibility": accessibility_review,
    }
    file_proposal = (
      propose_update_changes(provider, user_input=user_input, scope=update_scope or {})
      if intent == "website_update"
      else propose_generation_files(
        provider,
        user_input=user_input,
        brief=brief,
        plan=plan,
      )
    )
    result["file_proposal"] = file_proposal
    result["process_steps"].extend(
      [
        {
          "step": "planning",
          "agent": "Planner Agent",
          "status": "completed",
          "output": plan,
        },
        {
          "step": "file_change_proposal",
          "agent": "Dry-Run File Planning Agent",
          "status": "completed",
          "output": file_proposal,
        },
        {
          "step": "plan_reviews",
          "agent": "UX and Accessibility Review Agents",
          "status": "completed",
          "output": result["reviews"],
        },
        {
          "step": "write_policy",
          "agent": "Commit Agent",
          "status": "dry_run",
          "reason": "Proposals were returned without generating code or writing files.",
        },
        {
          "step": "artifact_validation_preview_visual_qa",
          "agent": "Validation, Preview, and Visual QA Agents",
          "status": "not_applicable",
          "reason": "These phases require generated source artifacts; the dry run reports their planned workflow without fabricating results.",
        },
        {
          "step": "flow_completion",
          "agent": "Supervisor Agent",
          "status": "completed",
          "reason": "Intent, analysis, and planning outputs were collected from backend agents.",
        },
      ]
    )
    result["assistant_response"] = (
      "Backend observation flow completed. Intent, prompt analysis, and planning "
      "outputs are shown above; project access was read-only and no code was generated or written."
    )
    return result

  state = GenerationPipelineState(
    user_prompt=user_input,
    intent=intent,
    routing_result=routing,
    control_client=provider,
  )
  conversation = generate_conversation_response(state, provider)
  result["assistant_response"] = conversation.get("message")
  result["conversation"] = conversation
  result["process_steps"].extend(
    [
      {
        "step": "conversation_response",
        "agent": "Conversation Agent",
        "status": "completed",
        "output": conversation,
      },
      {
        "step": "flow_completion",
        "agent": "Supervisor Agent",
        "status": "completed",
      },
    ]
  )
  return result


def persist_terminal_turn(
  database: TerminalDatabaseContext,
  *,
  user_input: str,
  result: dict[str, Any],
  project_path: str | None,
) -> dict[str, Any]:
  store = database.store
  store.record_project_chat_message(
    database.project_id,
    database.user,
    role="user",
    content=user_input,
    metadata={"source": "terminal_dry_run", "intent": result.get("intent")},
    chat_session_id=database.chat_session_id,
  )
  store.record_project_chat_message(
    database.project_id,
    database.user,
    role="model",
    content=str(result.get("assistant_response") or ""),
    metadata={
      "source": "terminal_dry_run",
      "intent": result.get("intent"),
      "file_proposal": result.get("file_proposal") or {},
    },
    chat_session_id=database.chat_session_id,
  )
  _root, files = load_terminal_project_files(project_path)
  proposed_paths = [
    str(item.get("path") or "")
    for item in (result.get("file_proposal") or {}).get("files") or []
    if isinstance(item, dict) and str(item.get("path") or "").strip()
  ]
  return persist_generation_memory_checkpoint(
    store,
    database.user,
    project_id=database.project_id,
    chat_session_id=database.chat_session_id,
    generation_run_id=None,
    prompt=user_input,
    intent=str(result.get("intent") or "conversation"),
    outcome="dry_run_planned",
    project_name=_root.name if _root else "Terminal dry-run project",
    files=files,
    changed_paths=[],
    preview_status="dry_run",
    extra={
      "source": "terminal_dry_run",
      "project_path": str(_root) if _root else "",
      "proposed_paths": proposed_paths,
      "writes_applied": False,
    },
  )


def update_terminal_database_project(
  database: TerminalDatabaseContext | None,
  root: Path,
) -> None:
  if database is None:
    return
  database.store.update_project(
    database.project_id,
    database.user,
    name=root.name,
  )
  database.store.set_project_local_path(
    database.project_id,
    database.user,
    str(root),
  )


def append_chat_history(provider: RecordingProvider, user_input: str, response: Any) -> None:
  history = getattr(provider.provider, "chat_history", None)
  if not isinstance(history, list):
    return
  history.extend(
    [
      {"role": "user", "parts": [{"text": user_input}]},
      {"role": "model", "parts": [{"text": str(response or "")}]},
    ]
  )


def print_turn(result: dict[str, Any]) -> None:
  print("\n" + "=" * 72)
  print(f"Intent: {result['intent']}")
  print("Routing:")
  print(json.dumps(result["routing"], indent=2, ensure_ascii=False))

  calls = result.get("llm_calls") or []
  print(f"LLM calls: {len(calls)}")
  for index, call in enumerate(calls, start=1):
    print(f"\nLLM response {index} [{call['trace_label']}]:")
    print(json.dumps(call["response"], indent=2, ensure_ascii=False))

  print("\nBackend process:")
  for index, step in enumerate(result.get("process_steps") or [], start=1):
    print(
      f"  {index}. {step.get('agent')} -> {step.get('step')} "
      f"[{step.get('status')}]"
    )

  if result.get("brief") is not None:
    print("\nPrompt Analyst output:")
    print(json.dumps(result["brief"], indent=2, ensure_ascii=False))
  if result.get("plan") is not None:
    print("\nPlanner output:")
    print(json.dumps(result["plan"], indent=2, ensure_ascii=False))
  if result.get("dynamic_workflow") is not None:
    print("\nDynamic agent workflow:")
    print(json.dumps(result["dynamic_workflow"], indent=2, ensure_ascii=False))
  if result.get("reviews") is not None:
    print("\nPlan reviews:")
    print(json.dumps(result["reviews"], indent=2, ensure_ascii=False))
  if result.get("update_scope") is not None:
    print("\nScoped update files and tasks:")
    print(json.dumps(result["update_scope"], indent=2, ensure_ascii=False))
  if result.get("file_proposal") is not None:
    print("\nProposed project tree / file changes:")
    print(json.dumps(result["file_proposal"], indent=2, ensure_ascii=False))

  print("\nWrite policy: backend observation only; code and local workspace writes disabled")
  print("\nAssistant:")
  print(result.get("assistant_response") or "")


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Observe production Worktual routing, analysis, and planning without generating or writing code."
  )
  parser.add_argument("--model", help="Gemini model override; defaults to GEMINI_MODEL from .env.")
  parser.add_argument(
    "--project-path",
    help="Existing local project to load read-only for project-info and update requests.",
  )
  parser.add_argument(
    "--no-db",
    action="store_true",
    help="Disable isolated vibe_builder_testing persistence and episodic memory.",
  )
  parser.add_argument("--prompt", help="Run one user input and exit instead of opening interactive chat.")
  parser.add_argument(
    "--no-history",
    action="store_true",
    help="Do not carry earlier terminal turns into later LLM calls.",
  )
  return parser


def main(argv: list[str] | None = None) -> int:
  log_path = configure_terminal_logging()
  args = build_parser().parse_args(argv)
  provider = RecordingProvider(GeminiProvider(model=args.model))
  active_project_path = str(args.project_path or "").strip() or None
  database: TerminalDatabaseContext | None = None

  print("Worktual chat-only orchestration tester")
  print("Backend routing, analysis, and planning run to completion.")
  print("Local projects are read-only; code generation, file writes, builds, and visual QA are disabled.")
  print("Type /project <absolute-path> to load or switch a read-only project.")
  print("Type /project to show the loaded directory. Type /exit to quit.")
  print(f"Log file: {log_path}")

  if active_project_path:
    try:
      root, files = load_terminal_project_files(active_project_path)
    except Exception as exc:
      print(f"Could not load project: {exc}")
      return 2
    active_project_path = str(root)
    print(f"Loaded project: {root} ({len(files)} readable source files)")

  if not args.no_db:
    try:
      settings = load_settings(require_database=True)
      terminal_database_url = str(
        os.getenv("WORKTUAL_TERMINAL_DATABASE_URL") or settings.database_url
      ).strip()
      database = initialize_terminal_database(
        terminal_database_url,
        project_name=Path(active_project_path).name if active_project_path else "Terminal dry-run project",
        local_path=active_project_path,
      )
    except Exception as exc:
      print(f"Could not initialize vibe_builder_testing: {exc}")
      return 2
    print(
      f"Database: {database.database_name}; episodic memory session: "
      f"{database.chat_session_id}"
    )
    prior_messages = database.store.list_project_chat_messages(
      database.project_id,
      database.user,
      chat_session_id=database.chat_session_id,
      limit=40,
    )
    provider.provider.chat_history = [
      {
        "role": "model" if str(item.get("role")) == "model" else "user",
        "parts": [{"text": str(item.get("content") or "")}],
      }
      for item in prior_messages
    ]

  while True:
    if args.prompt is not None:
      user_input = args.prompt.strip()
    else:
      try:
        user_input = input("\nYou> ").strip()
      except (EOFError, KeyboardInterrupt):
        print()
        return 0

    if user_input.lower() in {"/exit", "/quit", "exit", "quit"}:
      log_user_input(user_input)
      return 0
    log_user_input(user_input)
    if user_input == "/project":
      if active_project_path:
        root, files = load_terminal_project_files(active_project_path)
        print(f"Loaded project: {root} ({len(files)} readable source files)")
      else:
        print("No project loaded. Use /project /absolute/path/to/project")
      if args.prompt is not None:
        return 0
      continue
    if user_input.startswith("/project "):
      candidate = user_input.removeprefix("/project ").strip()
      try:
        root, files = load_terminal_project_files(candidate)
      except Exception as exc:
        print(f"Could not load project: {exc}")
      else:
        active_project_path = str(root)
        print(f"Loaded project: {root} ({len(files)} readable source files)")
        update_terminal_database_project(database, root)
      if args.prompt is not None:
        return 0
      continue
    candidate_path = Path(user_input).expanduser()
    if candidate_path.is_absolute() and candidate_path.is_dir():
      try:
        root, files = load_terminal_project_files(candidate_path)
      except Exception as exc:
        print(f"Could not load project: {exc}")
      else:
        active_project_path = str(root)
        print(f"Loaded project: {root} ({len(files)} readable source files)")
        update_terminal_database_project(database, root)
      if args.prompt is not None:
        return 0
      continue
    if not user_input:
      if args.prompt is not None:
        print("Prompt cannot be empty.")
        return 2
      continue

    try:
      episodic_memories = (
        select_episodic_memories_for_prompt(
          database.store,
          database.user,
          project_id=database.project_id,
          chat_session_id=database.chat_session_id,
          prompt=user_input,
          limit=4,
        )
        if database is not None
        else []
      )
      result = run_chat_turn(
        user_input,
        provider,
        project_path=active_project_path,
        episodic_memories=episodic_memories,
      )
    except Exception as exc:
      print(f"\nError: {type(exc).__name__}: {exc}")
      if args.prompt is not None:
        return 1
    else:
      print_turn(result)
      if not args.no_history:
        append_chat_history(provider, user_input, result.get("assistant_response"))
      if database is not None:
        memory_result = persist_terminal_turn(
          database,
          user_input=user_input,
          result=result,
          project_path=active_project_path,
        )
        print(
          "Memory: "
          f"snapshot={memory_result.get('status', 'completed')}, "
          f"episode={memory_result.get('episode_status', 'skipped')}"
        )

    if args.prompt is not None:
      return 0


if __name__ == "__main__":
  raise SystemExit(main())
