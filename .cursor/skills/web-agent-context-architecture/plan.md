# Web Agent Flow — Implementation Plan (worktual_codex)

**Parent plan:** [build-codex-cursor-agent-platform/plan.md](../build-codex-cursor-agent-platform/plan.md)  
**This skill covers:** Web client, context assembly, intent routing, memory in prompts, user-facing streams.

---

## Web-specific tiers

### Tier 0 — Context + stream reliability

| Task | File | User-visible outcome |
|------|------|----------------------|
| Chat persists every turn | `api/generation.py` → `storage/chat.py` | History survives refresh |
| Live files in prompt (not stale chat) | `agents/chat_history.py` | Updates target real code |
| v1 events optional on stream | `api/v1/runs.py` | CLI-ready same backend |
| Fix greeting `agent_run` contract | `api/generation.py` | "hi" never breaks response |
| Progress filters in UI | `src/main.jsx` `CHAT_PROGRESS_*` | Clean chat, no raw tool spam |

### Tier 1 — Memory + episodic context (#9)

| Task | File | User-visible outcome |
|------|------|----------------------|
| Write episodic summary after each run | `agents/memory/episodic.py` | Done |
| Inject episodic into context pack | `api/generation.py` | Done |
| Project memory + episodic in L2/L3 stack | `chat_history.py` | Smarter follow-up updates |
| Compaction for long chats | `chat_history.py` | No token blow-up |

**Context stack after Tier 1:**
```text
L6 User prompt (current)
L5 Skills (/skill + matcher)
L4 Episodic memory (last N runs)          ← NEW
L3 Enhancement + error from chat metadata
L2 Chat history (12 turns + summary)
L1 Live project files (authoritative)
L0 System prompts
```

### Tier 2 — Update UX + patch preview

| Task | File | User-visible outcome |
|------|------|----------------------|
| Update clarification flow | `routing.py`, failures | Clear "which file?" prompts |
| Show patch diff before commit | `src/main.jsx` + `patch.proposed` events | Partial (steps visible; diff panel next) |
| Scoped update → APPLY_PATCH | scoped update agents | Done |
| Gate failure messages in chat | `failures.py` → UI | Partial (`gate.failed` in chat progress) |
| Compaction for long chats | `chat_history.py` | Done |

### Tier 3 — Rich context (Phase 2)

| Task | Outcome |
|------|---------|
| SEARCH_CODEBASE in context pack | Partial — tool scaffold + codex registry |
| AGENTS.md in project root | Partial — default block injected when missing |
| Client hints (open file tab) | Future: selection-aware edits |

---

## Intent → flow checklist (every feature)

Before shipping a web feature, verify:

```text
- [ ] Correct intent (no file writes on greeting)
- [ ] Context pack includes live files + episodic (when Tier 1+)
- [ ] Stream events match v1 schema where applicable
- [ ] Chat + files + preview consistent after complete
- [ ] Error context attached for next turn (failures.py category)
```

---

## Terminal testing (phase-wise)

Run after each tier merge:

```bash
python backend/agents/terminal_runners/run_flow.py --list
python backend/agents/terminal_runners/run_flow.py --auto --prompt "generate farm website"
```

Then web smoke: create project → generate → update → chat only.

---

## Sync with platform skill

| Web concern | Platform skill owns |
|-------------|---------------------|
| What user sees | This skill |
| How agents run | `build-codex-cursor-agent-platform` |
| Tools, gates, MCP | Platform skill Phase 1–4 |
| Postgres schema | Both (memory tables shared) |

Update both skills when changing context layers or event contracts.
