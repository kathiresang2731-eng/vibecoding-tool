# Reference: Codex/Cursor-Class Platform Research

Research synthesis for building agentic coding tools. Sources: OpenAI Codex (open-source harness), Cursor public docs/blog, MCP/A2A specs, MAS orchestration literature, arXiv terminal-agent paper, execution-engine patterns.

---

## 1. Product Landscape

| Product | Primary surface | Core differentiator |
|---------|-----------------|---------------------|
| **OpenAI Codex CLI** | Terminal + App Server | One Rust harness, SQ/EQ event queues, sandboxed shell, worktrees, subagents |
| **Cursor** | VS Code fork + Cloud/CLI | Codebase vector index, Composer multi-file edits, MCP/skills, SDK embed |
| **Claude Code** | Terminal | Strong agent loop, MCP, permission modes |
| **Windsurf / Cascade** | IDE | Flow-based agent + codebase awareness |
| **Aider** | Terminal | Git-centric patch workflow, repo map context |

**Convergence:** All use a **harness** (agent loop) + **tools** (files, shell, git) + **context** (repo awareness) + **gates** (tests before trust).

---

## 2. OpenAI Codex CLI Architecture

### 2.1 Harness (codex-rs/core)

- **Codex** = public API handle for a thread (conversation)
- **Session** = state machine for configuration + active turns
- **SQ/EQ pattern:** Client submits ops to Submission Queue; core emits Events to Event Queue
- **Turn loop:** input → context injection → model sampling → tool execution → repeat

### 2.2 App Server (multi-client)

OpenAI's App Server exposes the same harness via **JSON-RPC 2.0 over stdio**:
- CLI, IDE extension, TUI, macOS app = clients of one server process
- Bidirectional: server can request approvals mid-turn
- Thread manager spins one core session per conversation thread

**Implication for worktual_codex:** Extract a `HarnessService` that web UI and future CLI/IDE both call — do not duplicate generation logic per client.

### 2.3 Tool Orchestrator flow

```
approval check → sandbox selection → execution → retry-with-escalation on denial
```

### 2.4 Built-in tools (Codex)

| Tool | Purpose |
|------|---------|
| `shell` / `shell_command` | Sandboxed execution (bubblewrap / zsh_fork) |
| `apply_patch` | Structured edits (Lark grammar + freeform diff) |
| `list_dir` | Paginated directory listing |
| `view_image` | Multimodal input |
| `tool_search` | BM25 over tool catalog (for large MCP surfaces) |
| `spawn_agent` / `wait_agent` | Hierarchical subagents |
| `request_permissions` | Mid-turn sandbox escalation |
| MCP via `McpHandler` | stdio or Streamable HTTP transport |

### 2.5 Context assembly (prompt stack)

Bottom to top:
1. User message
2. Environment (cwd, shell)
3. `AGENTS.md` project instructions
4. Sandbox permission rules
5. Developer config
6. Model-specific instructions
7. Tool definitions
8. Skills/plugins (injected per turn)

### 2.6 Parallelism

- **Git worktrees** for parallel local tasks on same repo
- **Subagent manager** dispatches workers with isolated context windows
- Cloud sandboxes for isolated remote execution

### 2.7 Persistence

- SQLite rollout persistence
- Automatic **context compaction** when window fills
- Turn bookmarks (`response_id`) for resume

---

## 3. Cursor Architecture (Public Surface)

### 3.1 Multi-surface

- IDE (primary)
- Cloud Agents (remote VM)
- CLI
- Slack / GitHub PR review
- **Cursor SDK** — embed same harness in third-party products

### 3.2 Codebase indexing (@Codebase)

- Chunk source files → embed → vector index
- RAG retrieval per query (not whole-repo load)
- Incremental re-index on file changes
- Hybrid: some processing local, some server-side (privacy tiers)

**Limitation (community reports):** Chunk retrieval misses cross-file references. Mitigation: add **code-graph MCP** (`find_usages`, `get_callers`, `smart_context`).

### 3.3 Agent Window (Cursor 3 direction)

- Dedicated agent UI for parallel agents
- Marketplace plugins: MCP, skills, sub-agents
- Local + cloud + remote SSH workspaces

### 3.4 SDK integration pattern (Notion example)

- First message: create agent with repo, model, MCP servers, auto-PR
- Follow-ups: new runs, SSE stream, resume from last event
- Remote MCP for product-specific state (not coding in a vacuum)

---

## 4. Four-Layer Backend Model (Industry Pattern)

Synthesized from arXiv terminal-agent paper, agent-execution-engine, odylith execution engine:

### Context Engine
- Retrieval, memory, compaction, rules/skills injection
- Answers: **what is true and relevant**
- Does not execute tools

### Execution Engine / Agent Core
- State machine or graph runtime
- Admissibility: admit / deny / defer next action
- Answers: **what move is allowed next**

### Tool Executor
- Sandboxed filesystem, terminal, git, MCP proxy
- Typed contracts, timeouts, structured ToolResult
- Answers: **how to perform approved action**

### Validation Gates
- HITL approval, schema validation, lint/test/build/security
- At boundaries: input, tool call, tool response, output, commit
- Answers: **did the change pass required checks**

---

## 5. MAS Orchestration Patterns

### 5.1 Supervisor (centralized)

```
User → Supervisor → [Agent A | Agent B | Agent C] → Supervisor → ...
```

- **Use:** 3–8 agents, deterministic workflows (plan → code → test → repair)
- **Frameworks:** LangGraph supervisor node, Codex ToolRouter, CrewAI manager
- **Pros:** Predictable, easy audit
- **Cons:** Supervisor context grows; single routing bottleneck

### 5.2 Pipeline (sequential)

```
Stage1 → Stage2 → Stage3 → ... → Commit
```

- **Use:** Validation gates, CI-like flows
- **Pros:** Simple, testable
- **Cons:** No dynamic replanning mid-pipeline without branches

### 5.3 Swarm / Mesh (decentralized)

```
Agent A ↔ Agent B ↔ Agent C (peer handoffs)
```

- **Use:** Open-ended research, customer support, exploratory tasks
- **Pros:** Fault tolerant, flexible
- **Cons:** Hard to debug, non-deterministic

### 5.4 Hierarchical (tree)

```
Manager → Team Lead → Workers
         → Team Lead → Workers
```

- **Use:** 15+ agents, enterprise multi-domain (support + sales + IT)
- **Pros:** Scales organizationally, scope isolation
- **Cons:** Multi-hop latency, information loss via summarization

### 5.5 LangGraph Subgraphs

- Compiled subgraph = node in parent graph
- **Shared state keys:** seamless parent-child communication
- **Wrapper functions:** different schemas between parent and child
- **Per-invocation vs per-thread:** subagents usually per-invocation (stateless between calls)

**Coding agent recommendation:** Supervisor outer loop + pipeline gates + subgraphs for specialized teams (e.g. `research_subgraph`, `edit_subgraph`).

---

## 6. MCP (Model Context Protocol)

### Architecture
- **Host:** AI application (Cursor, Codex, custom)
- **Client:** 1:1 connection manager inside host
- **Server:** Exposes capabilities

### Primitives
| Primitive | Control | Purpose |
|-----------|---------|---------|
| Tools | Model | Executable functions |
| Resources | Application | Read-only context data |
| Prompts | User | Reusable templates |

### Transport
- stdio (local processes)
- Streamable HTTP / SSE (remote)

### Design rules
- Capability negotiation at session init
- OAuth 2.1 for remote HTTP servers
- N servers × M hosts (not N×M custom integrations)

### Coding-agent MCP servers (examples)
- GitHub, Linear, Sentry, Postgres
- Code-graph (Gortex-style): `find_usages`, `get_call_chain`
- Custom indexer: `codebase_search` (separate index CLI from search MCP)

---

## 7. A2A (Agent2Agent Protocol)

### Purpose
Peer agent collaboration across frameworks/vendors — **not** a replacement for MCP.

| | MCP | A2A |
|---|-----|-----|
| Connects | Agent → tool/resource | Agent → agent |
| Discovery | tools/list | Agent Card (/.well-known/agent.json) |
| Transport | stdio, HTTP | JSON-RPC, gRPC, HTTP |

### Three-layer architecture
1. **Canonical data model** (Task, Message, AgentCard — protobuf)
2. **Abstract operations** (SendMessage, GetTask, SubscribeToTask)
3. **Protocol bindings** (JSON-RPC over HTTP, gRPC)

### Handoff fields (align with worktual_codex A2A package)
- objective, evidence, artifacts, risk, confidence, next_action

---

## 8. Context Engineering Disciplines

### Layers
1. **System context** — persona, safety, tool policy
2. **Task context** — objective, constraints, success criteria
3. **Response context** — output format, citation rules

### Techniques
- Progressive disclosure (don't load all skills upfront)
- Hierarchical summarization (L3 system → L2 entity → L1 detail)
- Tool result compaction (truncate logs, keep stderr tail)
- System reminders (injected mid-session when drift detected)
- Dual-memory: short-term working + long-term project memory

### Retrieval hybrid
```
semantic_search(query) ∪ ripgrep(query) ∪ symbol_graph(seed_files)
→ rank → dedupe → token budget trim
```

---

## 9. Validation Gate Catalog

| Gate | When | Failure routing |
|------|------|-----------------|
| Schema | Tool I/O | Reject call, no retry |
| Path policy | Before write | Deny + explain allowed surface |
| Syntax/lint | After patch | Repair agent |
| Typecheck | After patch | Repair agent |
| Unit tests | Before commit | Repair or escalate |
| Build | Before commit | Repair |
| Security scan | Before commit | Block + human review |
| Diff review | High-risk | Approval required |
| Visual QA | UI projects | Repair agent |

---

## 10. Persistence Stack (Production)

| Store | Purpose |
|-------|---------|
| PostgreSQL | Projects, runs, messages, tool_calls, approvals, index metadata |
| Redis | Live run events, pub/sub, session locks |
| Qdrant / pgvector | Code embeddings |
| Object storage | Snapshots, large artifacts, terminal logs |
| SQLite (optional) | Local CLI rollout persistence (Codex pattern) |

---

## 11. Security Model

### Defense in depth (terminal-agent paper)
1. Prompt-level guardrails
2. Schema-level tool gating
3. Runtime approval system
4. Tool-level validation
5. User-defined lifecycle hooks

### Sandbox
- bubblewrap/containers for shell
- cwd locked to workspace root
- env var allowlist
- network policy per tier
- secret file denylist (`.env`, credentials)

---

## 12. Key Repos & References

| Resource | URL |
|----------|-----|
| OpenAI Codex (Rust) | https://github.com/openai/codex |
| Codex protocol v1 | https://github.com/openai/codex/blob/main/codex-rs/docs/protocol_v1.md |
| Codex App Server blog | https://openai.com/index/unlocking-the-codex-harness/ |
| Cursor SDK / Notion | https://cursor.com/blog/notion |
| MCP specification | https://modelcontextprotocol.io/specification/2025-11-25 |
| A2A protocol | https://a2a-protocol.org/dev/ |
| LangGraph subgraphs | https://docs.langchain.com/oss/python/langgraph/use-subgraphs |
| Terminal agents arXiv | https://arxiv.org/html/2603.05344v1 |

---

## 13. worktual_codex Gap Analysis

| Capability | Current | Target |
|------------|---------|--------|
| Executor | `agent_runtime_loop` + LangGraph | Keep, simplify |
| Tools | 7 website tools | 20+ general coding tools |
| Context | File read + memory | Index + semantic search + graph |
| Terminal | local_helper :8799 | Backend sandbox service |
| API | project/generate-stream | /v1/sessions, /v1/runs |
| Clients | Web only | + CLI + IDE via harness RPC |
| MCP | None | MCP host in backend |
| Patch model | Whole-file write | apply_patch primary |
| Metadata bloat | ADK/LangChain projection | Optional decoration only |
