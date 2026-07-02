# Web Agent Context Architecture — Full Reference

Complete flowcharts, context limits, and persistence map for worktual_codex web-only operation.

---

## 1. System Boundary Diagram

```mermaid
flowchart TB
  subgraph users [Users]
    B[Browser]
  end

  subgraph web [Web Application]
    VITE[Vite HTTPS :5174]
    REACT[src/main.jsx SPA]
  end

  subgraph backend [Backend — Python FastAPI :8787]
    API[api/ routes]
    GEN[api/generation.py]
    AGENTS[agents/ runtime]
    TOOLS[agentic/tools/]
    STORE[storage/ Postgres]
    SKILLS[skills/]
  end

  subgraph optional [Optional Client Machine]
    LH[local_helper :8799 skills + safe terminal]
  end

  subgraph runtime_dirs [Runtime Output]
    RT[.runtime/ preview builds]
    LOGS[logs/ audit JSONL]
  end

  B --> VITE --> REACT
  REACT -->|/api proxy| API
  API --> GEN --> AGENTS --> TOOLS
  GEN --> SKILLS
  AGENTS --> STORE
  TOOLS --> RT
  GEN --> LOGS
  REACT -.->|optional| LH
```

**No CLI or IDE in this diagram — web is the complete product.**

---

## 2. End-to-End Sequence (One User Message)

```mermaid
sequenceDiagram
  participant U as User
  participant W as Web UI main.jsx
  participant A as API main.py
  participant G as generation.py
  participant S as storage
  participant R as routing
  participant O as orchestrator
  participant L as agent_runtime_loop
  participant T as tools

  U->>W: Type message
  W->>A: POST /generate-stream {prompt}
  A->>G: run_generation_pipeline
  G->>G: acquire run lock
  G->>S: get_project, list_files, list_chat
  G->>G: build context pack + skills
  alt greeting fast path
    G->>G: LLM conversation only
    G->>S: record chat + generation_run
    G-->>W: complete no files
  else full path
    G->>R: route_generation_action
    R-->>G: intent
    G->>O: generate_website
    O->>L: execute_real_agent_runtime_loop
    loop agent steps
      L->>T: READ / WRITE / VALIDATE / PREVIEW / QA
      T-->>L: tool results
      L-->>W: progress NDJSON
    end
    L->>S: apply_generated_files
    G->>S: record chat messages
    G-->>W: complete + files + preview
  end
  W->>W: refresh editor + iframe
```

---

## 3. Context Pack Detail

### 3.1 Chat history compaction

From `backend/agents/chat_history.py`:

| Constant | Value | Meaning |
|----------|-------|---------|
| `RECENT_FULL_TURNS` | 12 | Full recent user/model pairs |
| `MAX_STORED_HISTORY_MESSAGES` | 80 | Loaded from DB |
| `MAX_OLDER_SUMMARY_CHARS` | 4000 | Summarized older turns |
| `MAX_RECENT_MESSAGE_CHARS` | 12000 | Per recent message trim |
| `MAX_PROJECT_CONTEXT_FILES` | 10 | Live files in context |
| `MAX_PROJECT_CONTEXT_CHARS_PER_FILE` | 3500 | Per file |
| `MAX_PROJECT_CONTEXT_TOTAL_CHARS` | 22000 | Total live code context |

### 3.2 Authoritative instruction

```
STATEFUL_CODE_CONTEXT_INSTRUCTION:
  Conversation history = historical evolution of thought
  CURRENT live code context = authoritative for changes
```

### 3.3 Skills resolution order

From `backend/skills/` discovery:

```text
1. Explicit /skill-name in user message
2. User home ~/.worktual-skills/{system}/
3. Project .worktual/skills/
4. Bundled skills1/ defaults
```

### 3.4 Enhancement and error context

Extracted from chat metadata for follow-up turns:
- `latest_enhancement_context` — prior build/enhance summaries
- `latest_error_context` — local env errors, failures, helper issues

Appended via `append_orchestrator_context()` before orchestrator.

---

## 4. Confirmation Sub-Flow

```mermaid
stateDiagram-v2
  [*] --> AnalyzePrompt
  AnalyzePrompt --> BriefReady: generation/update intent
  BriefReady --> WaitingUser: REQUIRE_PLAN_CONFIRMATION
  WaitingUser --> Confirmed: user says confirm
  WaitingUser --> Revised: user revises
  WaitingUser --> Cancelled: user cancels
  WaitingUser --> NewRequest: unrelated new ask
  Revised --> BriefReady
  Confirmed --> AgentLoop
  Cancelled --> [*]
  NewRequest --> AnalyzePrompt
  AgentLoop --> [*]
```

Module: `backend/agents/requirement_confirmation/`

---

## 5. Update Flow (Existing Code)

```mermaid
flowchart TD
  A[website_update intent] --> B[Update Analysis Agent]
  B --> C{update_mode}
  C -->|needs_clarification| D[Return question — no writes]
  C -->|scoped patch| E[Scoped Update Agent]
  E --> F[Validate paths + sizes]
  F --> G[Agent loop commit]
  D --> H[User provides detail]
  H --> A
```

Common failure: vague update → `update_clarification` category.

---

## 6. Streaming Event Bridge (Web + v1)

| Legacy stream `type` | v1 `type` | UI shows |
|---------------------|-----------|----------|
| `progress` step=* | `run.progress` / `tool.*` / `gate.*` | AgentProgressStream |
| `complete` | `run.completed` | Files + preview refresh |
| `error` | `run.failed` | ErrorBanner |
| `backend.waiting` | `run.heartbeat` | Thinking indicator |

Modules: `api/generation_stream.py`, `api/v1/events.py`

---

## 7. Persistence Map

| Data | Storage | When written |
|------|---------|--------------|
| Chat messages | Postgres `project_chat_messages` | Each user/model turn |
| Project files | Postgres `project_files` | Save / generation commit |
| Generation runs | Postgres `generation_runs` | Each API call |
| Agent runs | Postgres `agent_runs` | Full agent path |
| Tool calls | Postgres `tool_calls` | Each tool invocation |
| Project memory | Postgres + tool | After successful generation |
| Audit | `logs/YYYY-MM-DD/*.jsonl` | Telemetry events |
| Preview build | `.runtime/projects/` | Preview agent |

---

## 8. Web-Only Capability Matrix

| Task | Supported | Path |
|------|-----------|------|
| Create project | Yes | `POST /api/projects` |
| Auto-create on first message | Yes | `main.jsx` |
| ChatGPT-like chat | Yes | greeting / conversation |
| Generate website | Yes | website_generation |
| Update code | Partial | website_update + scoped |
| Simple code file | Yes | simple_code |
| Skills | Yes | `/skill` + matcher |
| Local folder sync | Yes | import / sync-local |
| Monaco edit | Yes | save file API |
| Preview | Yes | build-preview + iframe |
| Terminal in browser | Weak | local_helper only |
| Codebase @search | No | Phase 2 planned |

---

## 9. Context Maintenance Anti-Patterns

| Anti-pattern | Why bad | Fix |
|--------------|---------|-----|
| Use old chat code as live | Stale edits | Always load `list_files` |
| Skip recording user message | Broken continuity | `record_project_chat_message` |
| Route "hi" to generation | Unwanted file writes | Greeting fast path |
| Vague update without clarify | `update_clarification` failures | Ask file/component |
| Write skills paths in repair | Path policy deny | Validate allowed surface |
| Ignore confirmation state | Wrong commits | Check brief status |

---

## 10. Future Web Enhancements (Same Architecture)

```mermaid
flowchart LR
  WEB[Web UI] --> API[Unified API]
  API --> CTX[Context Engine search]
  API --> PATCH[APPLY_PATCH]
  API --> TERM[Terminal sandbox]
  CTX --> LOOP[Same agent loop]
  PATCH --> LOOP
  TERM --> LOOP
```

CLI/IDE later attach to same API — web path unchanged.
