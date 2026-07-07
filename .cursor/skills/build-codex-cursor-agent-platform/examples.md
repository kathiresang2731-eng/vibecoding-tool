# Examples: Applying the Platform Skill to worktual_codex

## Implementation status (worktual_codex)

| Capability | Status | Location |
|------------|--------|----------|
| Live runtime trace (source of truth) | Done | `backend/agents/orchestration/live_runtime_trace.py` |
| Hierarchical MAS LangGraph | Done | `backend/agents/graph_runtime/hierarchical_runtime_graph.py` |
| v1 runs API + event schema | Partial | `backend/api/v1/` |
| Platform capabilities API | Done | `GET /api/v1/platform/capabilities` |
| Platform parity registry | Done | `backend/platform/parity.py` |
| Risk policy tiers | Done | `backend/platform/policy.py` |
| Failure → repair routing | Done | `backend/platform/repair_routing.py` + `api/failures.py` |
| APPLY_PATCH + universal file tools | Partial (staged) | `backend/execution/patch/`, `agentic/tools/platform.py` |
| SEARCH_CODEBASE / terminal / MCP | Planned | Phase 2–4 |

Query live status: `GET /api/v1/platform/capabilities`

---

## Example 1: Add codebase search (Phase 2)

**User request:** "Add Cursor-like @codebase search to our backend."

**Classification:**
- Layer: Context Engine + Tool Executor
- Parity: Cursor @Codebase
- Orchestration: No change (supervisor loop adds tool)

**Design:**

```text
New packages:
  backend/context/indexer/     # walk repo, chunk, hash
  backend/context/embeddings/  # embed → Qdrant
  backend/context/search/      # hybrid ranker

New tool:
  SEARCH_CODEBASE { query, max_results, include_globs?, exclude_globs? }

New API:
  POST /v1/workspaces/{id}/index
  GET  /v1/workspaces/{id}/index/status
  POST /v1/context/search

Events:
  context.index.started | context.index.completed
  context.search.completed

worktual_codex touchpoints:
  - Inject search results in api/generation.py before orchestrator
  - Register tool in agentic/tools/registry.py
  - Call from agents/agent_runtime/actions/analysis.py context step
```

**Gate:** Index must respect `.gitignore` and `backend/agents/artifacts/paths.py` deny rules.

---

## Example 2: Replace local_helper terminal (Phase 3)

**User request:** "Make terminal work like Codex shell tool."

**Classification:**
- Layer: Tool Executor + Policy
- Parity: Codex `shell` tool
- Orchestration: Supervisor invokes `RUN_TERMINAL`

**Design:**

```text
New package:
  backend/execution/terminal/
    sandbox.py      # subprocess + pty + caps
    policy.py       # tier: safe | developer | trusted
    session.py      # per-run terminal session

New tool:
  RUN_TERMINAL { command, cwd?, timeout_ms? }

Policy:
  safe: allowlist (npm test, pytest, git status, ...)
  developer: broader shell, approval for rm -rf, curl | bash
  trusted: local CLI only

Events:
  terminal.started
  terminal.output   # chunked stdout/stderr
  terminal.completed | terminal.failed

Migration:
  - Keep local_helper as fallback for LAN browser clients
  - CLI/IDE use backend /v1/terminal/sessions directly
```

---

## Example 3: Unified run API (Phase 0)

**User request:** "One API for web, CLI, and IDE."

**Classification:**
- Layer: API Gateway
- Parity: Codex App Server pattern

**Design:**

```text
Map existing:
  POST /api/projects/{id}/generate-stream
    → POST /v1/runs { workspace_id, prompt, client: "web" }

New entities:
  session → workspace → run → events

Compatibility:
  api/generation.py calls internal start_run() used by both v1 and legacy routes

Event types (extend api/progress.py):
  run.created, tool.*, patch.*, approval.*, gate.*, run.completed
```

---

## Example 4: MCP integration (Phase 4)

**User request:** "Connect GitHub and Postgres like Cursor MCP."

**Classification:**
- Layer: Tool Executor (MCP bridge)
- Parity: Cursor MCP + Codex McpHandler

**Design:**

```text
New package:
  backend/execution/mcp/
    host.py         # manage server lifecycle
    registry.py     # configured servers per workspace
    proxy.py        # MCP_CALL_TOOL → remote server

Config (per workspace or user):
  .worktual/mcp.json or DB mcp_servers table

Flow:
  1. Session start → connect configured MCP servers (stdio/HTTP)
  2. tools/list cached per server
  3. Model calls MCP_CALL_TOOL { server, tool, arguments }
  4. Backend proxies, validates, audits, returns structured result

Scale:
  If tools > 50, add tool_search (BM25) like Codex
```

---

## Example 5: Choose orchestration for 12 agents

**Scenario:** Platform has planner, searcher, coder, tester, reviewer, security, git, terminal, preview, repair, memory, registry agents.

**Decision:**

```text
Pattern: Hierarchical supervisor (not flat swarm)

Structure:
  Chief Supervisor
    ├── Context Team (searcher, memory)
    ├── Edit Team (coder, repair) — subgraph
    ├── Verify Team (tester, preview, security) — pipeline
    └── Ship Team (git, registry) — approval-gated

LangGraph:
  Parent graph: chief_supervisor node
  Subgraphs: edit_team_graph, verify_pipeline_graph
  Shared state keys: messages, workspace_id, patch_set, gate_results

Why not swarm:
  Coding tasks need deterministic gate order (test before commit)
```

---

## Example 6: Patch-first edit (Phase 1)

**User request:** "Stop overwriting whole files on small edits."

**Classification:**
- Layer: Tool Executor + Gate
- Parity: Codex apply_patch, Aider diffs

**Before (worktual_codex):**
```
WRITE_PROJECT_FILES [{ path, content: entire_file }]
```

**After:**
```
APPLY_PATCH { patches: [{ path, unified_diff }] }
  → validate paths
  → dry-run apply
  → stage in run snapshot
  → gate: lint/test
  → commit on approval
```

**Touchpoints:**
- `backend/agentic/tools/handlers.py` — new handler
- `backend/code_diff/` — reuse for diff preview events
- `backend/agents/runtime_agents/repair_agent/` — emit patches not full files

---

## Example 7: Risk approval for git commit

**Scenario:** Agent wants to run `git commit -m "fix tests"`.

**Policy flow:**

```text
1. RUN_TERMINAL proposes command
2. policy.classify → risk_tier: high (git write)
3. approval.required event → client UI
4. User approves → execute in sandbox
5. gate: GIT_DIFF_REVIEW passed?
6. audit log: tool.completed + git.commit metadata
```

**worktual_codex:** Extend `requirement_confirmation/` into general `policy/approvals.py`.

---

## Example 8: Subagent for parallel research

**Scenario:** "Analyze all API routes and suggest security fixes."

**Codex pattern:**

```text
Manager agent:
  spawn_agent(task="enumerate routes in backend/api/", context_budget=32k)
  spawn_agent(task="check auth middleware", context_budget=32k)
  wait_agent(agent_ids)
  synthesize → propose patches
```

**worktual_codex mapping:**
- Extend `dynamic_agenting/` for user-owned specialists
- Add `SPAWN_SUBAGENT` / `WAIT_SUBAGENT` tools
- Use LangGraph subgraph per subagent (per-invocation persistence)

---

## Example 9: Error category → repair routing

**From production logs (worktual_codex):**

| Error | Category | Route |
|-------|----------|-------|
| `path outside allowed surface` | policy_denied | Repair with valid paths; never retry same path |
| `finishReason: RECITATION` | model_blocked | Rephrase prompt; switch model tier |
| `dictionary changed size during iteration` | runtime_bug | Fix loop state mutation; no model retry |
| `update_clarification` | needs_user_input | Return to user; do not enter repair loop |

**Implement in:** `api/failures.py` + supervisor routing in `agent_runtime/supervision/`.

---

## Example 10: Skills + AGENTS.md hierarchy

**Codex/Cursor context stack for worktual_codex:**

```text
Priority (high → low):
  1. User message
  2. Project .worktual/AGENTS.md (create if missing)
  3. Matched skills (backend/skills/matcher.py)
  4. ~/.worktual-skills/{user}/ (skills1 seed)
  5. Retrieved codebase chunks
  6. Project memory (agentic/runtime_persistence/memory)
```

**New file to add:** `AGENTS.md` template in workspace bootstrap (alongside skills bootstrap in `backend/skills/bootstrap.py`).
