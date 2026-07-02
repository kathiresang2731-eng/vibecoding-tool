from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Callable

from ..agent_runtime.actions.dispatcher import ACTION_HANDLERS, execute_loop_action
from ..agent_runtime.supervision import available_runtime_actions, effective_repair_attempt_budget
try:
  from ...agent_tools import ToolRuntimeContext
except ImportError:
  from agent_tools import ToolRuntimeContext
from ..graph_runtime.dynamic_spawn_runtime import sync_dynamic_spawn_state
from ..graph_runtime.a2a.bus import publish_dynamic_agent_spawns
from ..providers import ARTIFACT_PROVIDER_ROLE, CONTROL_PROVIDER_ROLE
from ..providers.gemini import GeminiProvider
from ..providers.mock import MockProvider
from ..providers.roles import assert_provider_role
from ..runtime_agents.registry import ACTION_REGISTRY
from .bootstrap import ensure_project_root_on_path
from .catalog import actions_for_agent_name, agent_catalog_entry
from .mock_provider import TerminalMockProvider, build_terminal_mock_artifact
from .printer import print_action_result, print_agent_header, print_flow_summary, print_next_steps
from .seeds import seed_state_for_agent
from .session import load_session, merge_session_state, save_session, session_path


def build_providers(mode: str, *, prompt: str) -> tuple[Any, Any]:
  if mode == "live":
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
      print("WARNING: GEMINI_API_KEY not set; falling back to terminal mock provider.", file=sys.stderr)
      mode = "mock"
    else:
      model = os.getenv("WORKTUAL_TERMINAL_MODEL", "gemini-3.5-flash")
      provider = GeminiProvider(model=model)
      assert_provider_role(provider, CONTROL_PROVIDER_ROLE)
      artifact = GeminiProvider(model=model)
      assert_provider_role(artifact, ARTIFACT_PROVIDER_ROLE)
      return provider, artifact

  if mode == "mock":
    artifact_payload = build_terminal_mock_artifact(prompt)
    provider = TerminalMockProvider(artifact_payload=artifact_payload)
    artifact = TerminalMockProvider(artifact_payload=artifact_payload)
    return provider, artifact

  provider = MockProvider(artifact_payload=build_terminal_mock_artifact(prompt))
  artifact = MockProvider(artifact_payload=build_terminal_mock_artifact(prompt))
  return provider, artifact


def terminal_tool_executor(
  name: str,
  tool_context: ToolRuntimeContext,
  user: Any,
  arguments: dict[str, Any],
) -> dict[str, Any]:
  if name == "READ_PROJECT_FILES":
    return {"status": "ok", "files": [], "file_count": 0, "local_sync": None}
  if name == "LOAD_PROJECT_MEMORY":
    return {"status": "ok", "memories": []}
  if name == "VALIDATE_PROJECT_ARTIFACT":
    return {"status": "passed", "issues": []}
  if name == "BUILD_STAGED_PROJECT_PREVIEW":
    return {"status": "passed", "preview_url": "/preview/terminal-mock", "issues": []}
  if name == "WRITE_PROJECT_FILES":
    return {"status": "ok", "written_paths": ["src/App.jsx"]}
  if name == "PERSIST_PROJECT_MEMORY":
    return {"status": "ok"}
  return {"status": "ok", "tool": name, "arguments": arguments}


def run_terminal_action(
  *,
  action: str,
  state: dict[str, Any],
  control_provider: Any,
  artifact_provider: Any,
  progress: Callable[..., None] | None = None,
) -> dict[str, Any]:
  if action not in ACTION_HANDLERS:
    raise ValueError(f"Unsupported action: {action}")

  agent = ACTION_REGISTRY[action]["agent"]
  decision = {
    "next_action": action,
    "next_agent": agent,
    "reason": f"Terminal runner executed {action} for {agent}.",
    "audit_id": f"terminal-{action.lower()}",
    "decision_source": "terminal_runner",
  }
  state["_pending_decision"] = decision
  state["_pending_action"] = action

  execute_loop_action(
    action,
    state=state,
    decision=decision,
    control_provider=control_provider,
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=terminal_tool_executor,
    tool_context=ToolRuntimeContext(store=None, settings=None),
    user=type("TerminalUser", (), {"id": "terminal-user"})(),
    project_id=str(state.get("project_id") or "terminal-test-project"),
    start_time=time.time(),
    timeout_seconds=120,
    progress=progress or (lambda *_args, **_kwargs: None),
    runtime_objects={},
  )

  if action == "RUN_DYNAMIC_AGENT_PLANNER":
    state = sync_dynamic_spawn_state(state)
    publish_dynamic_agent_spawns(state, list(state.get("spawned_dynamic_agents") or []))

  return state


def run_agent_actions(
  *,
  agent_name: str,
  prompt: str,
  actions: list[str] | None = None,
  provider_mode: str = "mock",
  operation: str = "generate",
  project_id: str = "terminal-test-project",
  session_file: str | None = None,
  seed_mode: str = "default",
) -> dict[str, Any]:
  selected_actions = actions or actions_for_agent_name(agent_name)
  if not selected_actions:
    raise ValueError(f"No actions registered for agent: {agent_name}")

  state = seed_state_for_agent(
    agent_name=agent_name,
    prompt=prompt,
    project_id=project_id,
    operation=operation,
    seed_mode=seed_mode,
  )
  if session_file:
    saved = load_session(session_path(project_id) if session_file == "auto" else session_file)
    state = merge_session_state(state, saved.get("state", saved))

  control_provider, artifact_provider = build_providers(provider_mode, prompt=prompt)
  print_agent_header(agent_name, prompt=prompt, provider_mode=provider_mode)

  for action in selected_actions:
    print(f"\n>>> Running action: {action}")
    state = run_terminal_action(
      action=action,
      state=state,
      control_provider=control_provider,
      artifact_provider=artifact_provider,
      progress=lambda step, message, **_kwargs: print(f"    [{step}] {message}"),
    )
    print_action_result(action, state)

  repair_budget = effective_repair_attempt_budget(1)
  next_actions = available_runtime_actions(state, max_repair_attempts=repair_budget)
  print_next_steps(state, next_actions)
  print_flow_summary(state)

  if session_file:
    path = session_path(project_id) if session_file == "auto" else session_file
    save_session(path, {"project_id": project_id, "prompt": prompt, "state": _session_safe_state(state)})

  return state


def _session_safe_state(state: dict[str, Any]) -> dict[str, Any]:
  safe = dict(state)
  for key in list(safe.keys()):
    if key.startswith("_"):
      safe.pop(key, None)
  return safe


def prompt_for_user_input(argv_prompt: str | None) -> str:
  if argv_prompt and argv_prompt.strip():
    return argv_prompt.strip()
  print("\nEnter user prompt (example: generate the code for farm website):")
  print("> ", end="", flush=True)
  line = sys.stdin.readline()
  return line.strip() or "generate the code for farm website"


def build_arg_parser(agent_name: str) -> argparse.ArgumentParser:
  entry = agent_catalog_entry(agent_name)
  parser = argparse.ArgumentParser(
    description=f"Run {agent_name} standalone in the terminal.",
  )
  parser.add_argument("--prompt", "-p", help="User prompt. If omitted, terminal asks interactively.")
  parser.add_argument(
    "--action",
    choices=entry.get("actions") or None,
    help="Specific action to run when the agent has multiple actions.",
  )
  parser.add_argument(
    "--provider",
    choices=["mock", "live", "basic-mock"],
    default=os.getenv("WORKTUAL_TERMINAL_PROVIDER", "mock"),
    help="mock=deterministic terminal payloads, live=Gemini, basic-mock=generic MockProvider",
  )
  parser.add_argument("--operation", choices=["generate", "update"], default="generate")
  parser.add_argument("--project-id", default="terminal-test-project")
  parser.add_argument(
    "--session",
    help="Save/load JSON session. Use 'auto' for .worktual/terminal_sessions/<project>.json",
  )
  parser.add_argument(
    "--seed-mode",
    choices=["default", "dynamic_planner", "dynamic_specialists"],
    default="default",
    help="Prerequisite seeding strategy for dynamic-agent terminal tests.",
  )
  return parser


def main_for_agent(agent_name: str, argv: list[str] | None = None) -> int:
  ensure_project_root_on_path()
  parser = build_arg_parser(agent_name)
  args = parser.parse_args(argv)
  prompt = prompt_for_user_input(args.prompt)
  actions = [args.action] if args.action else None
  try:
    run_agent_actions(
      agent_name=agent_name,
      prompt=prompt,
      actions=actions,
      provider_mode=args.provider,
      operation=args.operation,
      project_id=args.project_id,
      session_file=args.session,
      seed_mode=args.seed_mode,
    )
  except Exception as exc:
    print(f"\nERROR: {exc}", file=sys.stderr)
    return 1
  return 0
