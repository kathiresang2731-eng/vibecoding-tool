---
name: vibe-coding-ui-research
description: Research and design UI/UX for AI coding, vibe-coding, agentic software engineering, and multi-agent builder tools. Use when Codex must benchmark competitors such as Cursor, Claude Code, Codex, Replit Agent, Lovable, Bolt, v0, GitHub Copilot, Devin, Windsurf, or similar products; perform web research; compare features, screens, workflows, interaction patterns, pricing/cost cues, agent transparency, approvals, code preview, deployment, and collaboration UX; or translate competitor findings into frontend requirements, wireframes, IA, component specs, and implementation plans.
---

# Vibe Coding UI Research

Use this skill to research the current UI patterns of AI coding tools and turn the findings into product decisions for a Worktual-style software engineering platform.

## Workflow

1. Clarify the product surface: request intake, planning, coding workspace, agent dashboard, approvals, blackboard/artifacts, cost dashboard, deployment, or settings.
2. Browse current sources before making competitor claims. Prefer official docs, product pages, changelogs, release notes, help centers, and first-party screenshots. Use reputable third-party reviews only to understand user perception.
3. Create a competitor matrix with source links, date accessed, feature evidence, UI pattern, strength, weakness, and relevance to the target product.
4. Extract UX patterns, not branding. Do not copy competitor layouts, copy, names, icons, or trade dress.
5. Convert findings into product requirements: screens, states, components, data contracts, empty/error/loading states, mobile behavior, and governance affordances.
6. Mark anything not verified by browsing as an assumption.

Read [competitor-ui-playbook.md](references/competitor-ui-playbook.md) when the task requires web research, competitor analysis, a feature matrix, or UI requirements derived from the market.

## What To Look For

Benchmark these UX dimensions:

- First-run and prompt intake.
- Plan mode, requirement clarification, and approval before changes.
- Code workspace, file tree, diff review, terminal, preview, and design canvas.
- Agent status, task queue, logs, background sessions, and multi-agent coordination.
- Context controls: repository indexing, file mentions, docs, rules, memory, MCP/connectors.
- Human control: pause, approve, reject, revise, rollback, checkpoints, permissions.
- Cost and resource visibility: tokens, modes, model choices, budgets, limits.
- Collaboration: teams, shared workspaces, PRs, issue handoff, chat integrations.
- Delivery: deploy, publish, download, GitHub sync, pull request, release notes.
- Trust: security, privacy, audit, enterprise controls, sandboxes, production safeguards.

## Output Standards

For a research answer, include:

1. Competitors researched and source links.
2. Feature and UX matrix.
3. Patterns to adopt.
4. Patterns to avoid.
5. Worktual-specific UI recommendations.
6. Implementation implications.
7. Open questions and assumptions.

For an implementation task, first summarize the research basis, then build or modify the UI using the project’s existing frontend stack and design rules.
