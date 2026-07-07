# worktual_codex — Master Implementation Plan

**Strategy:** Web-first. One harness (`agent_runtime_loop` + LangGraph). Model proposes; backend executes.  
**Skills:** This plan is shared by `build-codex-cursor-agent-platform` (platform/backend) and `web-agent-context-architecture` (web UX + context).

Query live parity: `GET /api/v1/platform/capabilities`

---

## Foundation: 9 Core Concepts

| # | Concept | Target | Status | Primary modules |
|---|---------|--------|--------|-----------------|
| 1 | **A2A** — agent-to-agent communication | Structured handoffs, spawn messages, acknowledgements | Partial | `agents/a2a/`, `graph_runtime/a2a/bus.py` |
| 2 | **MAS** — multi-agent system | Contracts, runtime state, dynamic registry | Partial | `agents/mas/`, `agents/dynamic_agents/` |
| 3 | **LangGraph** — nodes, edges, conditional routing | Chief → teams → actions; dynamic Send subgraph | Done (team-based) | `graph_runtime/hierarchical_*` |
| 4 | **LangChain** | Trace/projection from live runtime (not parallel executor) | Partial | `orchestration/trace_projections.py` |
| 5 | **Orchestration** | Pipeline: route → confirm → loop → persist | Done | `orchestration/runner.py`, `api/generation.py` |
| 6 | **Multi-threading** | Parallel bootstrap, reviews, dynamic specialists | Partial | `parallel_file_workers.py`, `update_preflight.py` |
| 7 | **Hierarchical flow** (not slow sequential) | Default at parity ≥ 90 | Done (tests pending) | `runtime_config.py`, hierarchical graph |
| 8 | **Remove unused files** | No dead executors or orphan assets | Done (ongoing audit) | — |
| 9 | **Memory** — Postgres, project scope, chat, episodic | Chat + memory_items + episodic write/read | Partial | `storage/chat.py`, `agents/memory/episodic.py` |

---

## Extended Requirements (beyond the 9)

For Codex/Cursor-class **output quality**, also implement:

| Area | Requirements | Phase |
|------|--------------|-------|
| **Context engine** | Episodic memory, compaction, SEARCH_CODEBASE, AGENTS.md | 1–2 |
| **Tool executor** | APPLY_PATCH in loop, terminal, git, MCP | 1–4 |
| **Validation gates** | lint → test → build → repair routing | 1–2 |
| **API / product** | v1 events in UI, patch.proposed, approval.required | 0–2 |
| **Observability** | Live trace, terminal runners, CI green | 0–1 |

---

## Phased Roadmap

### Tier 0 — Harness stabilization (Phase 0) `ACTIVE`

**Goal:** Reliable generation; one event schema; live trace is source of truth.

| Task | Module | Exit test |
|------|--------|-----------|
| Live runtime trace (no projection executors) | `orchestration/live_runtime_trace.py` | `test_llm_contract` projection tests |
| v1 runs API + event schema | `api/v1/` | `test_v1_runs_api` |
| Platform capabilities API | `platform/`, `GET /api/v1/platform/capabilities` | `test_v1_platform_api` |
| Fix hierarchical runtime tests | `tests/test_agent_runtime_loop.py` | 11 failures → 0 |
| Failure → repair routing | `platform/repair_routing.py`, `api/failures.py` | category + `repair_route` in payload |

**Skill updates when done:** Mark Phase 0 parity items `[x]` in `build-codex-cursor-agent-platform/SKILL.md`.

---

### Tier 1 — Foundation complete (Phase 0.5 + Phase 1 start)

**Goal:** All 9 concepts working end-to-end on web.

| Task | Maps to concept | Module |
|------|-----------------|--------|
| Episodic memory layer | #9 | `storage/memory.py`, `agents/memory/episodic.py` (new) |
| Memory in context pack every turn | #9 | `api/generation.py`, `chat_history.py` |
| Wire APPLY_PATCH into update/scoped flows | Tool quality | `execution/patch/`, scoped update agents |
| Emit `patch.proposed` v1 events | API | `api/v1/events.py`, generation stream |
| Expand parallel teams | #6 | `parallel_actions.py`, team batch configs |
| A2A ack completeness in evals | #1 | `agentic_evals/a2a.py` |
| Terminal phase-wise validation | #3,#5,#7 | `terminal_runners/run_flow.py` |

**Episodic memory design:**
```text
memory_items.kind = episodic
namespace = project | user | run
content = compact run summary (intent, files changed, gates, outcome)
retrieval = last N episodic + semantic match on user prompt (Phase 2)
```

**Exit criteria:** Tier 1 checklist green; terminal `--auto` passes generation + update smoke.

---

### Tier 2 — Output quality (Phase 1 complete + Phase 2 start)

**Goal:** Better edits, verified code, smarter context.

| Task | Module |
|------|--------|
| Patch-first default for `website_update` | `agent_runtime/actions/`, repair agents |
| Gate pipeline: lint + test hooks | `backend/execution/gates/` (new) |
| `gate.passed` / `gate.failed` in stream + UI | `api/v1/events.py`, `src/main.jsx` |
| Context compaction on token budget | `agents/agent_runtime/compaction.py` |
| AGENTS.md bootstrap per project | `backend/skills/bootstrap.py` |
| SEARCH_CODEBASE scaffold | `backend/context/search/` (new) |

**Exit criteria:** Scoped update uses patch; failed gate routes to repair with category.

---

### Tier 3 — Codex/Cursor parity (Phases 2–4)

| Task | Phase |
|------|-------|
| Codebase indexer + Qdrant | 2 |
| RUN_TERMINAL sandbox | 3 |
| GIT_STATUS / GIT_DIFF / GIT_COMMIT (approval) | 3 |
| RUN_TESTS / RUN_LINT in gate pipeline | 3 |
| MCP host | 4 |
| General approval engine (beyond plan confirm) | 4 |

---

### Tier 4 — Multi-client product (Phase 5)

| Task | Module |
|------|--------|
| CLI client on `/v1/runs/stream` | external |
| Run replay from LangGraph checkpoints | `graph_runtime/checkpointer.py` |
| WebSocket option for IDE | `api/v1/` |
| Worktrees for parallel tasks | `backend/execution/worktrees/` (new) |

---

## Implementation Order (recommended)

```text
Sprint A (done):  Tier 0 — fix tests, episodic memory schema + write path
Sprint B (done):  Tier 1 — APPLY_PATCH in loop, v1 patch events
Sprint C (done):  Tier 2 — gates + compaction + AGENTS.md + SEARCH_CODEBASE scaffold
Sprint D (done):  Tier 3 — terminal sandbox, git tools, test/lint gates, code index
Sprint E:        Tier 4 — CLI/IDE clients
```

---

## Per-task skill workflow

When implementing any task from this plan:

1. Read **both** skills: `web-agent-context-architecture` + `build-codex-cursor-agent-platform`
2. Classify layer: Context | Agent Core | Tool Executor | Gate | Persistence
3. Map to concept #1–9 or extended requirement
4. Update `platform/parity.py` status when capability changes
5. Add tests before marking phase exit criteria met
6. Update this `plan.md` status column and skill checklists

---

## Module ownership map

```text
Web UX + context assembly     → web-agent-context-architecture skill
Agent core + MAS + LangGraph  → graph_runtime/, agent_runtime_loop.py
Tools + patches + terminal    → agentic/tools/, execution/
Memory + chat Postgres        → storage/, agents/memory/
API + streaming               → api/generation.py, api/v1/
Platform parity tracking      → platform/
Skills injection              → backend/skills/
```

---

## Current snapshot (update as work completes)

| Metric | Value |
|--------|-------|
| Tests passing | ~473/473 Sprint A targets green |
| Default topology | `hierarchical` at parity ≥ 90 |
| Live trace | Yes — `live_runtime_trace.py` |
| Episodic memory | Write + context injection (Tier 1 partial) |
| APPLY_PATCH in main loop | Wired (scoped update + codex tool executor) |
| patch.proposed v1 events | Emitted on stage + commit |
| Validation gates | artifact + syntax lint in runtime loop |
| Chat compaction | Budget-based in generation pipeline |
| AGENTS.md context | Bootstrap block in orchestrator context |
| SEARCH_CODEBASE | Scaffold + memory index (Qdrant optional) |
| Parallel file workers | ✅ Greenfield + update preflight + build/visual gates | `parallel_file_workers.py`, `update_preflight.py` |
| Dynamic agenting thread safety | ✅ Per-thread provider clone | `providers/thread_clone.py`, `dynamic_agenting/execution.py` |
| v1 parallel stream events | ✅ `execution_engine: parallel` on wave/analysis steps | `api/v1/events.py` |

### Multithreading phased roadmap (2026-06)

| Phase | Focus | Status |
|-------|-------|--------|
| **MT-1** | Parallel worker safety (memory, per-thread LLM, timeouts, path overlap) | Done |
| **MT-2** | Update preflight before parallel workers | Done |
| **MT-3** | Dynamic agenting thread-safe providers + dead code cleanup | Done |
| **MT-4** | v1 stream parallel event tagging + parity flags | Done |
| **MT-5** | LLM update preflight in staging (`ENABLE_PARALLEL_UPDATE_LLM_ANALYSIS`, memory-aware, timeout fallback) | Done |
| **MT-6** | LangGraph vs streaming path parity (Visual QA, scoped patch on default) | Done |
| **MT-7** | Worktrees for concurrent project runs (Tier 4) | Pending |

**MT-6 deliverables:** `backend/agents/streaming/streaming_parity.py` — deterministic scoped patch routing, patch approval gate before commit, build-gate rollback on failure; wired through `parallel_orchestrator`, `parallel_file_workers`, `file_agent`, and `runner` streaming branch; flag `ENABLE_STREAMING_PATH_PARITY` (default on).

---

## Related files

- Web context skill: `../web-agent-context-architecture/SKILL.md`
- Platform skill: `SKILL.md`
- Examples: `examples.md`
- Backend parity: `backend/platform/parity.py`
