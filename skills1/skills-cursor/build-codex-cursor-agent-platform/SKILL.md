---
name: build-codex-cursor-agent-platform
description: Designs and implements Codex/Cursor-class agentic coding platforms with context engines, tool executors, MAS orchestration, MCP/A2A integration, and validation gates. Use when building AI coding agents, CLI/IDE backends, multi-agent orchestration, codebase indexing, terminal sandboxes, or enhancing worktual_codex toward full agentic tool parity. **Always read [plan.md](plan.md) for the master implementation roadmap.**
---

# Build Codex/Cursor-Class Agent Platform

Guides backend and platform design for tools comparable to OpenAI Codex CLI, Cursor IDE, Claude Code, Windsurf, and Aider.

## When to Apply

Apply this skill when the user asks to:
- Build or enhance an agentic coding tool (CLI, IDE extension, web workspace)
- Design backend architecture for multi-agent systems
- Add codebase search, terminal, git, MCP, or patch-based editing
- Choose MAS/orchestration patterns (supervisor, swarm, hierarchical)
- Map features from Codex/Cursor into an existing codebase (e.g. worktual_codex)

## Core Principle

**The model proposes; the backend executes.** Never let the LLM be the authority for permissions, file writes, git commits, or sandbox escape.

## Target Architecture (4 Layers)

```text
Client (CLI / IDE / Web)
    ↓
API Gateway (sessions, runs, streaming events)
    ↓
Agent Core (orchestrator + runtime loop + supervisor)
    ↓
Context Engine + Tool Executor + Validation Gates
    ↓
Persistence (Postgres, Redis, vectors, snapshots)
```

### Layer Responsibilities

| Layer | Answers | Must NOT do |
|-------|---------|-------------|
| **Context Engine** | What is true and relevant? | Execute tools or mutate workspace |
| **Agent Core** | What is the next admissible step? | Bypass policy or skip gates |
| **Tool Executor** | How to run approved actions? | Decide policy or assemble full context |
| **Validation Gates** | Did the change pass checks? | Generate code or plan tasks |

## Master Implementation Plan

**Full roadmap:** [plan.md](plan.md) — 9 core concepts + extended requirements + sprint order.

**Current sprint:** Tier 4 — CLI/IDE clients on `/v1/runs/stream`.

**Live status:** `GET /api/v1/platform/capabilities`

### 9 core concepts (foundation)

| # | Concept | Status |
|---|---------|--------|
| 1 | A2A | Partial |
| 2 | MAS | Partial |
| 3 | LangGraph (hierarchical teams + conditional edges) | Done |
| 4 | LangChain (live trace projections) | Partial |
| 5 | Orchestration | Done |
| 6 | Multi-threading (parallel bootstrap/reviews/specialists) | Partial |
| 7 | Hierarchical flow (default at parity ≥ 90) | Done |
| 8 | Remove unused files | Done |
| 9 | Memory (Postgres chat + project + episodic) | Partial |

Implement any feature by classifying it against this table + [plan.md](plan.md) tiers.

## Codex / Cursor Feature Parity Checklist

Copy and track when scoping backend work:

```text
Platform Parity:
- [x] Live runtime trace as source of truth
- [x] Hierarchical MAS LangGraph (chief → teams)
- [~] Unified run API (session → workspace → run → events)  # v1 scaffold
- [~] Streaming event contract (tool, patch, terminal, gate, approval)
- [ ] Context engine (index + semantic search + file graph)
- [~] Patch-first file edits (APPLY_PATCH in scoped update loop)
- [~] Validation gates (artifact + syntax lint; test runner next)
- [~] Context compaction on chat budget
- [~] Terminal sandbox (allowlisted RUN_TERMINAL)
- [~] Git tools (GIT_STATUS/DIFF/COMMIT with approval)
- [~] Test/build runner tools (RUN_TESTS/RUN_LINT in gates)
- [ ] MCP host (stdio + HTTP transports)
- [~] Skills + rules injection (AGENTS.md / SKILL.md hierarchy)
- [~] Human approval for high-risk actions (plan confirm + policy tiers)
- [~] Run replay + checkpoint resume (checkpointer partial)
- [~] Multi-client support (CLI, IDE, web share one harness)
```

Legend: `[x]` done · `[~]` partial · `[ ]` not started. Update when merging tiers from [plan.md](plan.md).

## MAS & Orchestration Pattern Selection

Choose pattern by agent count and task dynamism:

| Pattern | Structure | Best for | Trade-off |
|---------|-----------|----------|-----------|
| **Supervisor** | One router → workers | 3–8 agents, deterministic pipelines | Single point of routing |
| **Pipeline** | Sequential stages | Lint → test → build → deploy | Low flexibility |
| **Swarm / Mesh** | Peer handoffs | Dynamic conversations, research | Harder to debug |
| **Hierarchical** | Manager → leads → workers | 15+ agents, enterprise domains | Latency, context compression loss |
| **Subgraphs** (LangGraph) | Nested compiled graphs | Mixed teams, reusable modules | Schema mapping complexity |

**Default for coding agents:** Supervisor + Pipeline gates inside the loop.

**Promote to hierarchical** only when a single supervisor cannot route 15+ specialists.

**Use subgraphs** when teams need isolated state (e.g. research subgraph vs code-edit subgraph).

## Standard Agent Runtime Loop

Every Codex/Cursor-class tool converges on this loop:

```text
1. Receive user input + client hints (open files, selection, cwd)
2. Compose context pack (search + memory + rules + skills)
3. Classify intent + risk tier
4. If high risk → pause for approval
5. Supervisor selects next action/tool
6. Policy check → execute tool in sandbox
7. Append tool result to run state
8. Repeat until done or budget exceeded
9. Run validation gates (lint, test, build, security)
10. Stage or commit patches; persist run + audit trail
```

### Codex-specific patterns (from open-source harness)
- **SQ/EQ queues:** Submission queue (client → core) + Event queue (core → client)
- **Turn-based execution:** Each user message = one or more turns; turns can resume via bookmark/response_id
- **App Server:** One harness, many clients via JSON-RPC over stdio (CLI, IDE, TUI share core)
- **Worktrees:** Parallel tasks on isolated git working copies
- **Subagents:** `spawn_agent` / `wait_agent` for parallel workers with separate context

### Cursor-specific patterns
- **Codebase index:** Vector RAG over repo chunks (hybrid with grep/symbol tools)
- **Composer:** Multi-file patch generation with diff preview
- **Cloud agents:** Remote VM sandbox close to repo
- **MCP + skills + subagents:** Extensibility via standardized tool surface
- **SDK embedding:** Same harness exposed for third-party products (Notion-style integrations)

## Tool Surface (Minimum Viable + Parity)

Expand beyond website-only tools toward this set:

| Category | Tools |
|----------|-------|
| Filesystem | `READ_FILE`, `READ_FILE_RANGE`, `LIST_DIR`, `GLOB_SEARCH`, `APPLY_PATCH` |
| Search | `SEARCH_CODEBASE`, `GET_SYMBOL_REFERENCES`, `GET_FILE_TREE` |
| Terminal | `RUN_TERMINAL` (sandboxed, tiered policy) |
| Git | `GIT_STATUS`, `GIT_DIFF`, `GIT_COMMIT` (approval-gated) |
| Validation | `RUN_TESTS`, `RUN_BUILD`, `RUN_LINT` |
| Browser | `BROWSER_ACTION` (CDP) |
| MCP | `MCP_CALL_TOOL` (proxy to external servers) |
| Memory | `LOAD_MEMORY`, `PERSIST_MEMORY` |
| Orchestration | `SPAWN_SUBAGENT`, `WAIT_SUBAGENT` (optional) |

**Tool contract rules:**
- Typed input/output schemas (Pydantic or JSON Schema)
- Timeouts, byte caps, structured errors (never raw exceptions to model)
- Python binds `workspace_id`, `user_id`, `cwd` — model cannot override
- Every call logged with correlation_id for replay

## MCP vs A2A (Use Both, Different Jobs)

| Protocol | Connects | Example |
|----------|----------|---------|
| **MCP** | Agent → tools/data | GitHub API, DB, filesystem, code-graph server |
| **A2A** | Agent → agent | Delegate research task to remote specialist agent |

**Rule:** Equip agents with MCP tools; use A2A when agents must collaborate across frameworks/vendors.

MCP primitives: **Tools** (model-invoked actions), **Resources** (read-only context), **Prompts** (templates).

## Context Engineering Stack

Build context in layers (do not dump whole repo):

```text
L0 System: role, safety policy, tool schemas
L1 Workspace: AGENTS.md, rules, skills, package manifests
L2 Retrieval: top-K semantic chunks + grep hits + symbol neighbors
L3 Session: chat history (compacted), recent tool results
L4 Client hints: open tabs, cursor selection, diagnostics
L5 Task: current objective, execution brief, success criteria
```

**Compaction triggers:** token budget threshold, N turns, or repeated tool failures.

**Hybrid retrieval:** semantic search (vectors) + exact search (ripgrep) + optional code graph (callers/usages).

## Validation Gates (Non-Negotiable)

No commit without passing required gates:

```text
syntax/lint → typecheck → dependency preflight → unit tests → build → security scan → diff review → commit
```

Gate failures route to repair agent with structured error category — not generic retry.

## Risk Policy Tiers

| Tier | Examples | Backend behavior |
|------|----------|------------------|
| Low | read, search, single-file small patch | Auto-approve |
| Medium | multi-file patch, package install | Notify + optional approve |
| High | git commit, delete files, broad shell | Require approval |
| Critical | prod deploy, secrets, force push | Block or explicit admin approve |

## API Event Contract (All Clients)

Standardize one stream for CLI, IDE, and web:

```json
{"type": "tool.started", "run_id": "...", "tool": "RUN_TERMINAL", "input": {"command": "npm test"}}
{"type": "patch.proposed", "paths": ["src/App.tsx"], "diff_stats": {"additions": 12, "deletions": 3}}
{"type": "approval.required", "reason": "git commit", "risk_tier": "high"}
{"type": "gate.failed", "gate": "unit_tests", "category": "test_failure"}
{"type": "run.completed", "status": "success", "artifacts": {"patch_set_id": "..."}}
```

## worktual_codex Mapping (Start Here)

When enhancing this repo, map work to existing packages:

| Target capability | Start file / package |
|-------------------|----------------------|
| Live executor | `backend/agents/agent_runtime_loop.py` |
| LangGraph runtime | `backend/agents/graph_runtime/` |
| Tool implementations | `backend/agentic/tools/handlers.py` |
| Orchestrator | `backend/agents/orchestration/runner.py` |
| Approvals | `backend/agents/requirement_confirmation/` |
| Skills | `backend/skills/` |
| API entry | `backend/main.py` → `api/v1/` |
| Platform parity + phases | `backend/platform/` |
| Patch engine (Phase 1) | `backend/execution/patch/` |
| Universal file tools | `backend/agentic/tools/platform.py` |
| Persistence | `backend/storage/` |
| Preview/QA | `backend/runtime.py`, `backend/visual_qa/` |

**Keep:** `agent_runtime_loop`, `graph_runtime`, `agentic/tools`, `skills`, `storage`.

**Deprecate as executors:** `google_adk_runtime`, `langchain_runtime_impl` metadata-only paths.

**Replace gradually:** `local_helper` terminal → `backend/execution/terminal` service.

## Phased Backend Roadmap

Aligned with [plan.md](plan.md). **Tier 0 active; Tier 1 next.**

| Phase | Focus | Exit criteria | Tier |
|-------|-------|---------------|------|
| 0 | Stabilize runtime, live trace, `/v1/runs`, fix hierarchical tests | CI green on runtime graph | 0 |
| 0.5 | Episodic memory + context injection | Memory in every generation turn | 1 |
| 1 | Universal file tools + APPLY_PATCH in loop | Scoped update uses patches | 1–2 |
| 2 | Context engine (index + Qdrant + SEARCH_CODEBASE) | Large-repo retrieval | 2–3 |
| 3 | Terminal + git + test runner | Agent runs tests and fixes | 3 |
| 4 | MCP host + policy engine | External tools with permissions | 3–4 |
| 5 | IDE/CLI affordances (WS, worktrees, replay) | Extension-ready API | 4 |

## Anti-Patterns

- Letting the model write files without patch validation
- Multiple competing executors (ADK + LangChain + custom loop)
- Whole-repo prompt stuffing instead of retrieval
- Browser-only terminal helper as core execution path
- Metadata projection packages treated as source of truth
- Skipping gates for "speed"
- Per-client divergent run protocols

## Design Workflow

When asked to design or implement a feature:

1. **Classify** — context, execution, tool, gate, or persistence?
2. **Check parity** — which Codex/Cursor capability does this match?
3. **Pick orchestration** — supervisor default; justify if hierarchical/swarm
4. **Define tool contract** — schema, policy tier, timeout, audit event
5. **Map to worktual_codex** — extend existing package or add new module?
6. **Specify API event** — what does CLI/IDE stream?
7. **Add gate** — what must pass before commit?

## Output Templates

### Architecture proposal

```markdown
## Capability
[What Codex/Cursor feature this adds]

## Layer
[Context / Agent Core / Tool Executor / Gate / Persistence]

## Orchestration
[Supervisor | Pipeline | Hierarchical | Subgraph — and why]

## New tools/APIs
- Tools: ...
- Endpoints: ...
- Events: ...

## worktual_codex touchpoints
- Modify: ...
- Add: ...

## Risk policy
[tier + approval rules]

## Validation gates
[required checks before commit]

## Phase
[0–5]
```

### Implementation checklist

```markdown
- [ ] Tool schema + handler + policy tier
- [ ] Audit event types
- [ ] API route + stream event
- [ ] Storage schema migration
- [ ] Gate integration
- [ ] Test: happy path + policy deny + gate failure
```

## Additional Resources

- **Master implementation plan:** [plan.md](plan.md)
- Research synthesis (Codex CLI, Cursor, MCP, A2A, MAS patterns): [reference.md](reference.md)
- worktual_codex examples and mappings: [examples.md](examples.md)
- Web context + UX plan: [../web-agent-context-architecture/plan.md](../web-agent-context-architecture/plan.md)
- Project docs: `docs/vibe_coding_tool_architecture_presentation.md`, `backend/AGENTIC_EXECUTION_FLOW.md`
