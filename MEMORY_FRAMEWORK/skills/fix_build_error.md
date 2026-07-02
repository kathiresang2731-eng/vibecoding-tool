# Fix Build Error Procedure

## Purpose

Diagnose and fix compile, lint, runtime, or dependency errors systematically.

---

## Step 1: Capture the error

Get the exact error message, file, and line if available.

If the user pasted a stack trace, identify the **root** error, not downstream noise.

---

## Step 2: Retrieve similar fixes

Call `episode_retriever` with intent derived from the error, e.g.:

- `"module not found tsconfig paths"`
- `"React hydration mismatch Next.js"`
- `"Supabase RLS policy insert failed"`

Prioritize this user's personal episodes over generic advice.

---

## Step 3: Hypothesize causes

List 1–3 likely causes ordered by probability. Check:

- imports and path aliases
- missing dependencies or wrong versions
- env variables
- type mismatches
- framework-specific pitfalls (App Router, SSR, etc.)

---

## Step 4: Fix minimally

Apply the smallest change that addresses the root cause.

Explain what changed and why in one or two sentences unless the user prefers detail.

---

## Step 5: Confirm recovery

Ask the user to re-run build/dev or confirm the error is gone.

If the fix fails twice, step back and revise the hypothesis — do not repeat the same patch.

---

## Episodic learning

Sessions that resolve non-trivial errors are strong candidates for personal episodic memory at session end (fix_pattern).

Generalize the lesson; do not store secrets or full file contents in episodes.
