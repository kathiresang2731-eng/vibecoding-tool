# Context Maintenance Examples

## Example 1: First message (no project yet)

**User:** "Hi, I want to build a portfolio site"

**Context state:**
- No project until web creates one
- No files, empty chat

**Flow:**
```text
main.jsx → create/open project → streamGeneration
→ greeting OR needs_details OR website_generation
```

**Agent checklist:**
- [ ] Project created and project_id set
- [ ] Do not assume files exist
- [ ] If brief too short → ask details, no writes

---

## Example 2: Pure chat (ChatGPT mode)

**User:** "What is the difference between let and const?"

**Context:**
- Existing project with files — ignore files for this turn
- Routing should stay conversation/greeting

**Flow:** `greeting` or conversational routing → **no WRITE_PROJECT_FILES**

**Response:** Explain in chat only; live files unchanged.

---

## Example 3: New website generation

**User:** "Build a B2B SaaS landing page for invoice automation"

**Context to load:**
```text
L1: [] empty or scaffold files
L2: prior chat if any
L4: matched skill e.g. greenfield-website if /skill used
```

**Flow:**
```text
website_generation → confirmation brief → user confirm → agent loop → preview → commit
```

**UI:** File tree populates, previewUrl set.

---

## Example 4: Update existing project

**User:** "Make the hero section background dark blue"

**Context to load:**
```text
L1: index.html, src/App.jsx, package.json, ... (live)
L2: "Built landing page yesterday" (historical)
L3: enhancement_context from last generation
```

**Flow:**
```text
website_update → update analysis → scoped patch → validate → preview → commit
```

**If vague ("make it better"):**
→ `update_clarification` — ask which section/file.

---

## Example 5: Confirmation pause

**User (first):** "Add authentication to the app"  
**System:** Execution brief — lists planned files, asks confirm

**User (second):** "confirm"

**Context:**
- Pending brief in `requirement_confirmation` storage
- Must NOT treat "confirm" as new unrelated prompt

**Flow:** Resume → agent loop with brief as authority.

---

## Example 6: Skill invocation

**User:** "/session-code-edit update the pricing table to show 3 tiers"

**Context:**
```text
skills/runtime.py → explicit match session-code-edit
injector builds skills_block into effective_prompt
L1: live files required for edit
```

**Flow:** `website_update` or scoped update with skill-guided prompts.

---

## Example 7: Error recovery turn

**Previous turn failed:** `backend_generation` — repair tried to write `.worktual/skills/...`

**User:** "Try again"

**Context:**
```text
error_context from chat metadata
L1: unchanged live files (rollback)
```

**Agent action:**
- Diagnose path policy failure
- Do not repeat invalid paths
- Propose edits only under allowed project surface

---

## Example 8: Developer implementing a feature

**User (developer):** "Add greeting detection for 'good morning'"

**Using skill template:**

```markdown
## User intent
chat routing enhancement

## Active context
- Module: api/generation.py is_simple_greeting_prompt
- Also: orchestration/routing.py for full path

## Flow path
Master diagram → GREET node → expand patterns

## Expected outcome
"good morning" → greeting fast path, no file writes

## If implementing
- api/generation.py is_simple_greeting_prompt
- tests in test_requirement_confirmation or new test file
```

---

## Example 9: Maintaining agent context in Cursor chat

When user asks about worktual_codex in Cursor IDE chat:

1. Read skill `web-agent-context-architecture`
2. Identify: web-only, which intent, which modules
3. Cite live code paths from Module Map
4. Never suggest CLI/IDE unless user explicitly asks for future clients
5. Always state what context layers apply to their scenario

---

## Example 10: Progress stream → user-facing narrative

**Internal step:** `tool.completed` READ_PROJECT_FILES  
**Web filter:** `CHAT_PROGRESS_VISIBLE_STEPS` in main.jsx  
**User sees:** "Reading project files" in AgentProgressStream  
**Chat memory:** Model response summarized after complete event

Keep internal steps out of chat (`shouldHideChatProgress`).
