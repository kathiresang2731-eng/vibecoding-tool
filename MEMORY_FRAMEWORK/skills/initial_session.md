# Initial Session Procedure

## Purpose

Handle the first messages in a workspace: greet the builder, learn project intent, and load context before making changes.

---

## Step 1: Greet and orient

Warm, brief greeting. If profile memory has `display_name` or `project_name`, use it naturally.

Do not ask for stack details already in profile or preference memory.

---

## Step 2: Clarify intent

Determine whether the user wants to:

- start a new project or continue an existing one
- add a feature
- fix an error
- understand or refactor existing code
- change styling or UX

Infer from their message; do not assume.

---

## Step 3: Confirm stack (if unknown)

If profile memory lacks framework/language/database, ask **one** focused question, e.g.:

- "Are you on Next.js or Vite?"
- "TypeScript or JavaScript?"

---

## Step 4: Retrieve episodic memory

When you know enough about the task (stack + goal), call `episode_retriever` with a short intent, e.g.:

- "bootstrap Next.js app with Tailwind"
- "user prefers minimal explanations"

Use hits to avoid repeating past mistakes for **this user**.

---

## Step 5: Propose next step

End with one clear next action: scaffold, read context, load another procedure (`add_feature`, `fix_build_error`, `scaffold_component`), or ask one clarifying question.

---

## Rules

- One follow-up question per turn.
- Prefer small verifiable steps.
- Call `get_project_context` when file-level context would help (stub in testbed).
