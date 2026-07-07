# Terminal Agent Runners

Run each Worktual runtime agent **standalone** from the terminal for phase-wise debugging.

## Quick start

From the project root:

```bash
# Interactive production-LLM chat routing without website generation
python -m backend.agents.terminal_runners.chat

# List phases and scripts
python backend/agents/terminal_runners/run_flow.py --list

# Interactive phase-wise flow (asks before each phase/agent)
python backend/agents/terminal_runners/run_flow.py

# Auto-run all phases with one prompt
python backend/agents/terminal_runners/run_flow.py --auto --prompt "generate the code for farm website"

# Run one agent only
python backend/agents/terminal_runners/planner_agent.py --prompt "generate the code for farm website"
```

The chat-only runner prints each raw structured LLM response, normalized intent,
selected action/tool, agent process step, prompt-analysis output, plan, and final
conversation response. It completes an observation-only backend flow with
optional read-only local-project access and without code generation, file
writes, builds, or visual QA.

For read-only update planning, configure both values in `.env`:

```dotenv
LOCAL_WORKSPACE_ROOTS=/absolute/allowed/parent
WORKTUAL_TERMINAL_PROJECT_PATH=/absolute/allowed/parent/project
```

The `.env` path is only an optional default. Prefer supplying the project
directly:

```bash
python -m backend.agents.terminal_runners.chat --project-path /absolute/path/to/project
```

Inside an interactive session, load or switch it at any time:

```text
/project /absolute/path/to/project
```

Generation dry runs return the proposed project tree. Update dry runs read the
configured project, resolve the production scoped-update candidates, and return
per-file planned changes without generating or applying source code.

By default the terminal runner creates/uses the isolated PostgreSQL database
`vibe_builder_testing`. It stores terminal chat history, session snapshots, and
episodic memories under a dedicated testing user/project. Use `--no-db` only
when database persistence is intentionally unwanted.

Every terminal session is also captured through Loguru in:

```text
logs/teminal_testinh_YYYY-MM-DD.log
```

Set `WORKTUAL_TERMINAL_LOG_DIR` to change the containing directory.
The file is a plain terminal transcript without timestamps or log-level prefixes.

Keep the production and terminal-testing connections separate:

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/vibe_builder
WORKTUAL_TERMINAL_DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/vibe_builder_testing
```

The PostgreSQL application role must own or be allowed to create the testing
database. If it lacks `CREATEDB`, create the database once as a PostgreSQL
administrator with the same owner as the database named by `DATABASE_URL`;
the terminal runner will then bootstrap its schema automatically.

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
