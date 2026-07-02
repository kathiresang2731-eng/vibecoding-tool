from __future__ import annotations

import argparse
import sys

from .bootstrap import ensure_project_root_on_path
from .catalog import FLOW_PHASES, format_phase_menu, list_all_agents, phase_agents
from .executor import main_for_agent, prompt_for_user_input, run_agent_actions


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description="Run the Worktual agent flow phase-wise in terminal.")
  parser.add_argument("--prompt", "-p", help="User prompt for all agents in the flow.")
  parser.add_argument("--provider", choices=["mock", "live", "basic-mock"], default="mock")
  parser.add_argument("--operation", choices=["generate", "update"], default="generate")
  parser.add_argument("--project-id", default="terminal-test-project")
  parser.add_argument("--session", default="auto", help="Persist state between agents (default: auto).")
  parser.add_argument("--phase", help="Run only one phase id, e.g. 3_planning")
  parser.add_argument("--list", action="store_true", help="List phases and agents, then exit.")
  parser.add_argument("--auto", action="store_true", help="Run all phases without asking between agents.")
  return parser


def main(argv: list[str] | None = None) -> int:
  ensure_project_root_on_path()
  args = build_parser().parse_args(argv)
  if args.list:
    print(format_phase_menu())
    print("Standalone scripts:")
    for agent in list_all_agents():
      from .catalog import AGENT_SCRIPT_NAMES

      print(f"  python backend/agents/terminal_runners/{AGENT_SCRIPT_NAMES.get(agent, 'run_flow')}.py  # {agent}")
    return 0

  prompt = prompt_for_user_input(args.prompt)
  phases = [phase for phase in FLOW_PHASES if not args.phase or phase["id"] == args.phase]
  if not phases:
    print(f"Unknown phase: {args.phase}", file=sys.stderr)
    return 1

  print(format_phase_menu())

  for phase in phases:
    print(f"\n\n{'#' * 72}\n# {phase['title']}\n{'#' * 72}")
    if not args.auto:
      answer = input(f"Run phase {phase['id']} ({', '.join(phase['agents'])})? [Y/n] ").strip().lower()
      if answer in {"n", "no"}:
        continue

    for agent_name in phase_agents(phase["id"]):
      if not args.auto:
        agent_answer = input(f"  Run {agent_name}? [Y/n] ").strip().lower()
        if agent_answer in {"n", "no"}:
          continue
      seed_mode = "default"
      if phase["id"] == "4_dynamic" and agent_name == "Agent Registry Agent":
        seed_mode = "dynamic_planner"
      run_agent_actions(
        agent_name=agent_name,
        prompt=prompt,
        provider_mode=args.provider,
        operation=args.operation,
        project_id=args.project_id,
        session_file=args.session,
        seed_mode=seed_mode,
      )

  return 0


if __name__ == "__main__":
  raise SystemExit(main())
