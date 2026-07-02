# Scaffold Component Procedure

## Purpose

Create new UI components or layouts consistent with the user's project and preferences.

---

## Step 1: Requirements

Clarify:

- component purpose and name
- props or data it needs
- placement (page, layout, storybook-only)

One question if anything critical is missing.

---

## Step 2: Style and library alignment

From preference memory, respect:

- UI library (shadcn, MUI, plain Tailwind)
- naming conventions
- functional vs class components
- file colocation patterns

From profile memory, match framework (React, Vue, etc.).

---

## Step 3: Structure the component

Default structure:

1. types/props interface
2. component implementation
3. export
4. optional usage example in comment or sibling file

Keep components focused; split if responsibility grows.

---

## Step 4: Accessibility and states

Include loading, empty, and error states when the component displays data.

Use semantic HTML and labels for interactive elements.

---

## Step 5: Handoff

Tell the user where the file lives and how to import it.

If episodic memory shows a successful scaffold pattern for this stack, follow that shape.

---

## Rules

- Do not scaffold unrelated files in the same turn unless requested.
- Prefer composition over duplication of existing components.
