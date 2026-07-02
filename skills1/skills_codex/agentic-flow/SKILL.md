---
name: agentic-flow
description: Design, review, and implement adaptive agentic workflows for software engineering systems. Use when Codex needs to create or improve chief-orchestrator routing, dynamic workflow selection, agent registries, agent spawning policies, domain orchestrators, approval gates, validation loops, memory layers, observability, or migration plans away from fixed linear pipelines.
---

# Agentic Flow

Use this skill to turn a fixed agent pipeline into an adaptive, chief-orchestrated flow. Optimize for choosing the minimum capable workflow, escalating only when complexity or risk requires it, and keeping every agent decision explainable.

## Core Model

Represent the platform as:

```text
User Request
-> Chief Orchestrator
-> Agent Selection Policy
-> Dynamic Workflow Builder
-> Main Agents / Domain Orchestrators / Spawned Specialists
-> Validation + Review
-> Final Response + Memory Update
```

The Chief Orchestrator decides what should happen. It should not perform specialist work directly when an existing or spawned agent is more appropriate.

## Decision Workflow

For every request:

1. Normalize the request and preserve the original text.
2. Identify task type: `simple_code`, `repo_question`, `repo_edit`, `debug`, `large_feature`, `test`, `review`, `deploy`, `security_sensitive`, or `chat`.
3. Estimate complexity, risk, repo-context need, write need, command need, and approval need.
4. Select the smallest safe workflow.
5. Assign agents with clear inputs and expected outputs.
6. Execute with progress state and failure handling.
7. Validate results before final delivery.
8. Write decision memory: selected route, reason, tools, risks, files changed, validation result.

## Routing Rules

Use deterministic shortcuts before model-heavy orchestration:

```text
simple standalone code -> simple writer or local template
general chat -> response only
repo question -> context -> responder
small repo edit -> context -> writer -> diff
debug -> context -> debug/coding -> writer -> test
large feature -> planner -> context -> coding -> test -> review
security-sensitive change -> planner -> security -> approval -> writer -> review
deployment -> planner -> security -> approval -> deployment -> verification
```

Prefer no spawning for low-risk simple work. Prefer existing agents for common tasks. Spawn specialists only when the task requires expertise, parallel investigation, or a risk review not covered by existing agents.

## Agent Registry Contract

Each registered agent should declare:

```text
id
role
capabilities
inputs
outputs
can_write_files
can_run_commands
risk_level
cost_level
latency_level
approval_requirements
fallback_behavior
```

Agent selection should be policy-driven, not hardcoded inside every node.

## Agent Spawning Policy

Spawn a specialist only when at least one condition is true:

- The task mentions a specific framework, language, platform, or domain not covered by a main agent.
- The task has high blast radius and needs independent review.
- The task can be safely parallelized into independent investigations.
- The existing workflow lacks a required capability.

Never spawn for obvious simple code, plain chat, or single-file low-risk edits.

## Approval Gates

Require approval before:

- Deleting files or large code sections.
- Editing secrets, credentials, `.env`, auth, payment, security, or production config.
- Installing dependencies.
- Running migrations, deploys, shell commands with side effects, or infrastructure changes.
- Performing large multi-file writes.

The orchestrator must pause with a concise reason, requested action, expected files/commands, and rollback plan.

## Validation Loop

After execution:

```text
writer result
-> syntax/lint/test check when available
-> diff review
-> security review if flagged
-> repair loop if validation fails
-> final summary
```

Do not claim success unless the requested outcome and validation criteria are satisfied.

## Memory Layers

Maintain four memory layers when implementing the system:

- Working memory: current workflow state, active agents, intermediate outputs.
- Project memory: repo structure, active files, user project goals.
- Decision memory: route selected, why, risk, approvals, validation results.
- Knowledge memory: reusable patterns promoted only after review.

## Reference

For an implementation roadmap, read `references/eight-phase-blueprint.md`.
