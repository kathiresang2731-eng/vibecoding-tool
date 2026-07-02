# Memory Framework Schema

Episodic memory for Worktual: per-chat-session continuity and cross-user platform learning.
Reference design: `MEMORY_FRAMEWORK/` (Meilisearch testbed — not production code).

## Use cases

1. **Session continuity** — Each `chat_session_id` keeps rolling summaries, changed paths, preview/error state, and structured episodes so long conversations do not lose project context.
2. **Platform learning** — Successful fix/workflow patterns from many users/projects are promoted (anonymized) into `memory_platform_patterns` to reduce tokens and time on similar builds.

## Tables

### `memory_user_profiles`

Per-user project profile (framework, domain, modules, goals).

| Column | Type | Notes |
|--------|------|-------|
| id | text PK | |
| user_id | text FK → users | |
| project_id | text | Empty string = account-wide |
| profile_json | jsonb | Full profile blob |
| framework | text | e.g. `vite` |
| domain | text | e.g. `crm`, `ecommerce` |
| created_at / updated_at | timestamptz | |

Unique: `(user_id, project_id)`

### `memory_user_preferences`

Durable coding preferences (style, testing depth, etc.).

| Column | Type | Notes |
|--------|------|-------|
| category, preference | text | Unique per user |
| polarity | text | `positive` / `negative` |
| confidence | numeric | 0–1 |
| durability | text | `long_term`, etc. |
| metadata_json | jsonb | |

### `memory_episodes`

Structured episodic records per run (personal or shared scope).

| Column | Type | Notes |
|--------|------|-------|
| project_id | text FK | |
| chat_session_id | text FK → project_chat_sessions | Nullable |
| generation_run_id | text FK | Nullable |
| scope | text | `personal` \| `shared` |
| memory_type | text | `workflow`, `fix_pattern`, `tool_pattern`, `conversation_improvement`, `update_checkpoint` |
| title, searchable_summary | text | For retrieval |
| situation, stack_tags, module_tags | text | Context tags |
| improved_behavior, avoid | text | Actionable guidance |
| outcome | text | `completed`, `failed`, etc. |
| changed_paths_json | jsonb | |
| metadata_json | jsonb | domain, modules, etc. |

Indexes: `(project_id, chat_session_id, created_at)`, `(scope, module_tags, created_at)`

### `memory_session_snapshots`

Append-only checkpoints after each generation run within a chat session.

| Column | Type | Notes |
|--------|------|-------|
| snapshot_kind | text | `update_checkpoint`, `code_manifest`, `error_recovery`, `session_summary` |
| content | text | Rolling summary text |
| changed_paths_json | jsonb | |
| file_manifest_json | jsonb | Path counts / manifest |
| preview_status, error_category | text | Last known build/preview state |

### `memory_chat_session_state`

One row per chat session — fast lookup for agents.

| Column | Type | Notes |
|--------|------|-------|
| chat_session_id | text PK FK | |
| rolling_summary | text | Accumulated session narrative |
| last_changed_paths_json | jsonb | |
| last_preview_status | text | |
| last_error_category | text | |
| file_count | int | |
| update_count | int | Incremented each checkpoint |
| last_generation_run_id | text | |
| metadata_json | jsonb | domain, modules |

### `memory_platform_patterns`

Anonymized cross-user patterns (learning phase).

| Column | Type | Notes |
|--------|------|-------|
| pattern_key | text UNIQUE | Hash of domain+module+type+title |
| domain, module, pattern_type | text | e.g. `crm` / `leads` / `fix_pattern` |
| memory_type | text | Same enum as episodes |
| title, summary | text | |
| situation, improved_behavior, avoid | text | |
| stack_tags | text | |
| source_count | int | Times seen across projects |
| confidence_score | numeric | Grows with repetitions |
| first_seen_at, last_seen_at | timestamptz | |

### `memory_platform_pattern_events`

Audit trail when patterns are reinforced.

| Column | Type |
|--------|------|
| pattern_id | text FK |
| domain, module, pattern_type | text |
| outcome | text |

## Isolation policy

| Layer | Scope | What is stored |
|-------|-------|----------------|
| Chat session memory | `chat_session_id` only | Rolling summary, changed paths, errors for **this chat only** — never other chats, even same user |
| Episodic memory (`memory_items`) | `chat_session_id` only | Run summaries tied to session; no cross-session merge |
| Structured episodes | `chat_session_id` + user | Personal session checkpoints |
| Platform patterns | Cross-user, anonymized | **Site update/error patterns only** — no chat text, prompts, or conversations |

Platform learning reuses **error handling and update patterns** (paths, error categories, fix/workflow behavior) so the next user benefits with lower token usage. It never stores or merges chat conversations from other users or sessions.

```
Generation completes
  → persist_generation_memory_checkpoint
       → memory_session_snapshots (append)
       → memory_chat_session_state (upsert, update_count++)
       → memory_episodes (insert personal episode when intent is code-changing)
       → memory_platform_patterns (upsert if promotable)
       → memory_user_profiles (upsert domain/modules)
       → prune older personal episodes (keep last 20 per session)

Next generation in same session
  → build_unified_memory_context_block
       → session state + episodic items + structured episodes + platform patterns
```

## Code locations

| Component | Path |
|-----------|------|
| DB bootstrap | `backend/storage/bootstrap.py` |
| Store CRUD | `backend/storage/memory_framework.py` |
| Session monitor | `backend/agents/memory/session_monitor.py` |
| Platform learning | `backend/agents/memory/platform_learning.py` |
| Prompt context | `backend/agents/memory/context.py` |
| Generation wiring | `backend/api/generation.py` |
| Chat API exposure | `backend/api/chat.py` (`session_memory_state`, `structured_episodes`) |
| Episodes API | `GET/DELETE /api/users/me/memory/episodes` via `backend/agents/memory/episodes_api.py` |
| Platform patterns API | `GET /api/v1/platform/memory/patterns` via `backend/agents/memory/platform_patterns_api.py` |

## Future (optional)

- Meilisearch hybrid search (reference in `MEMORY_FRAMEWORK/`)

### Learning phase env vars

| Variable | Default | Purpose |
|----------|---------|---------|
| `PLATFORM_PATTERN_MIN_SOURCE_COUNT` | `2` | Minimum repetitions before a platform pattern is injected into agent context |
| `ENABLE_PLATFORM_FAILED_RUN_LEARNING` | `true` | Promote anonymized `fix_pattern` rows from failed builds with an error category |

### Retrieval env vars (Sprint 9C)

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENABLE_EPISODIC_HYBRID_RETRIEVAL` | `true` | Rank episodes with 60% semantic-like + 40% token overlap |
| `ENABLE_LEGACY_EPISODIC_READ` | `false` | Opt-in fallback to legacy `memory_items` episodic rows |

### Vector episode search

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENABLE_EPISODIC_VECTOR_SEARCH` | auto when Qdrant URL set | Blend vector similarity into episodic ranking |
| `ENABLE_EPISODIC_VECTOR_MEMORY_FALLBACK` | `true` | In-memory vector index when Qdrant is not configured |
| `WORKTUAL_QDRANT_URL` | empty | Qdrant server URL for episode vectors |
| `WORKTUAL_QDRANT_API_KEY` | empty | Optional Qdrant API key |
| `WORKTUAL_QDRANT_EPISODES_COLLECTION` | `worktual_memory_episodes` | Qdrant collection name |
| `GEMINI_EMBEDDING_MODEL` | `text-embedding-004` | Embedding model when `GEMINI_API_KEY` is set |
| `EPISODE_VECTOR_SIZE` | `128` | Local hash embedding dimensions when Gemini is unavailable |
