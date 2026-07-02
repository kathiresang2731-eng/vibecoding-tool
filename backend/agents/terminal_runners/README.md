# Terminal Agent Runners

Run each Worktual runtime agent **standalone** from the terminal for phase-wise debugging.

## Quick start

From the project root:

```bash
# List phases and scripts
python backend/agents/terminal_runners/run_flow.py --list

# Interactive phase-wise flow (asks before each phase/agent)
python backend/agents/terminal_runners/run_flow.py

# Auto-run all phases with one prompt
python backend/agents/terminal_runners/run_flow.py --auto --prompt "generate the code for farm website"

# Run one agent only
python backend/agents/terminal_runners/planner_agent.py --prompt "generate the code for farm website"
```

If you omit `--prompt`, the script asks:

```text
Enter user prompt (example: generate the code for farm website)
>
```

## Phase map

| Phase | Team | Agents |
|-------|------|--------|
| 1 | Context | `memory_agent.py` |
| 2 | Analysis | `error_handling_agent.py`, `update_analysis_agent.py`, `prompt_analyst_agent.py` |
| 3 | Planning | `planner_agent.py` |
| 4 | Dynamic | `agent_registry_agent.py`, `dynamic_specialists.py` |
| 5 | Generation | `code_agent.py`, `scoped_update_agent.py`, ... |
| 6 | Verification | `ux_review_agent.py`, `validation_agent.py`, ... |
| 7 | Commit | `commit_agent.py`, `memory_agent.py` |

## Provider modes

| Flag | Meaning |
|------|---------|
| `--provider mock` | Deterministic terminal payloads (default) |
| `--provider live` | Gemini (`GEMINI_API_KEY` required) |
| `--provider basic-mock` | Generic `MockProvider` |

## Session chaining

Pass `--session auto` to save state between agents:

```bash
python backend/agents/terminal_runners/prompt_analyst_agent.py --prompt "farm website" --session auto
python backend/agents/terminal_runners/planner_agent.py --session auto
```

State file: `.worktual/terminal_sessions/<project-id>.json`

## Dynamic agent testing

```bash
# Spawn + execute specialists (planner + specialists actions)
python backend/agents/terminal_runners/agent_registry_agent.py --prompt "farm website"

# Execute specialists only (workflow pre-seeded)
python backend/agents/terminal_runners/dynamic_specialists.py --prompt "farm website"
```

## Output

Each run prints:

1. Agent / phase / team metadata  
2. Action output JSON  
3. Parallel execution details (thread pool / LangGraph Send) when applicable  
4. **Next node / agent actions** with suggested script  
5. Run summary (`action_history`, spawned dynamic agents)

## Regenerate per-agent scripts

```bash
python backend/agents/terminal_runners/_generate_agent_scripts.py
```
