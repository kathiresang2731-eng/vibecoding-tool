# Add Feature Procedure

## Purpose

Guide adding a feature (auth, API route, page, integration) in a vibe-coding session.

---

## Step 1: Scope the feature

Confirm:

- what the feature should do for the user
- which files or areas are likely touched
- constraints (existing auth, DB, design system)

Ask one question if scope is unclear.

---

## Step 2: Check memory

Review profile (stack, auth, database) and preferences (patterns, libraries to use or avoid).

Call `episode_retriever` with intent like `"add Clerk auth to Next.js app"` if similar work may exist for this user.

---

## Step 3: Plan before code

Outline:

1. files to create or edit
2. dependencies to add
3. validations (env vars, types, tests)

Keep the plan short; match user's preferred explanation depth.

---

## Step 4: Implement incrementally

- One logical chunk at a time
- Match project conventions from preferences
- Avoid drive-by refactors

---

## Step 5: Verify

Suggest how to verify: dev server, build, lint, or manual check.

If build fails, switch mentally to `fix_build_error` procedure.

---

## Rules

- Do not invent env vars or API keys.
- Reuse existing patterns in the project when known.
- Store durable stack facts in profile memory at session end — not mid-turn.
