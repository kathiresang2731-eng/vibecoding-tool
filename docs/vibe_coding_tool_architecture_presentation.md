# Vibe Coding Tool Architecture Presentation

## Purpose
This PDF presents a production architecture for a vibe coding tool similar to Claude Code, Cursor, Codex, Windsurf, and Aider. It is designed for engineering handoff and stakeholder presentation.

## Core Architecture
- Client surfaces: IDE extension, browser workspace, CLI, and local desktop app.
- API boundary: authenticated WebSocket/HTTP gateway that owns sessions and streams.
- Orchestrator: classifies intent, confirms risky work, creates the run plan, and coordinates agents.
- MAS runtime: planner, context, code edit, test, repair, review, security, and commit-gate agents.
- A2A protocol: typed handoffs with objective, evidence, artifacts, risk, confidence, and next action.
- Context engine: repository index, semantic search, file graph, memory retrieval, and compression.
- Tool executor: permissioned filesystem, terminal, git, package manager, browser, preview, and MCP tools.
- Validation gates: syntax, dependency preflight, build, test, preview, visual QA, security, and diff review.
- Persistence: PostgreSQL for runs and audit, Redis for live state/pub-sub, Qdrant for vectors, object storage for artifacts, and workspace storage for file snapshots.

## Required Production Behaviors
- No generated code is committed before passing validation gates.
- The backend owns authority; the model proposes plans and patches.
- Destructive or broad actions require human approval.
- Every run emits traceable lifecycle events.
- Every agent handoff is durable and replayable.
- Failures are normalized into actionable categories with repair routing.
