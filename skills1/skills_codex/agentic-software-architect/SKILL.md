---
name: agentic-software-architect
description: Design, review, and evolve production-grade agentic software engineering platforms and hybrid multi-agent systems. Use when Codex is asked to create or assess architecture, workflows, orchestrators, agent responsibilities, execution lifecycles, approval gates, memory layers, delivery processes, or implementation plans for systems similar to Codex, Claude Code, Cursor, Devin, OpenHands, or Worktual MAS.
---

# Agentic Software Architect

Use this skill to turn broad agentic-engineering ideas into a structured architecture, execution plan, or review. Optimize for scalable orchestration, clear agent boundaries, human approval gates, validation, observability, maintainability, and continuous learning.

## Core Workflow

Run every architecture or implementation-planning task through this lifecycle unless the user explicitly narrows the scope:

1. Goal analysis
2. Requirement understanding
3. Gap analysis
4. Complexity assessment
5. Planning
6. Human approval checkpoints
7. Task decomposition
8. Agent selection
9. Task distribution
10. Execution approach
11. Validation
12. Testing
13. Review
14. Deployment or delivery
15. Learning loop

If a stage is not applicable, state why briefly. Do not skip missing-information checks.

## Architecture Model

Use a hierarchical orchestration model:

- Chief Orchestrator owns goal understanding, workflow creation, task planning, agent coordination, progress monitoring, risk management, human approval management, and final delivery.
- Domain orchestrators own specialized areas such as coding, research, testing, deployment, security, knowledge, and operations.
- Specialist agents perform domain work such as backend development, frontend development, API design, database engineering, infrastructure, research, test engineering, security review, documentation, and release management.
- The Chief Orchestrator should coordinate and delegate instead of doing specialized work directly when a suitable agent or orchestrator exists.

For full policy details, read [architecture-policy.md](references/architecture-policy.md) when the task involves platform design, workflow design, agent taxonomy, governance, or a full architecture review.

## Planning Rules

Before recommending implementation, identify:

- The user goal and project outcome.
- Missing requirements, unknown constraints, and assumptions.
- Architecture gaps and dependency risks.
- Complexity, blast radius, and operational risk.
- Success criteria and validation strategy.
- Responsible orchestrators and agents.
- Human approval checkpoints for architecture, planning completion, major code generation, security-sensitive changes, infrastructure changes, and production deployment.

During implementation planning, prefer incremental delivery with reviewable milestones. Keep business logic, security policy, integration behavior, and agent behavior tied to explicit requirements.

## Memory And Learning

Design or review four logical memory layers when relevant:

- Working memory: current execution state.
- Project memory: requirements, architecture, milestones, and progress.
- Knowledge memory: reusable solutions, patterns, best practices, and lessons learned.
- Decision memory: architectural decisions, trade-offs, approvals, and rationale.

Continuous learning must be gated by review, evaluation, and promotion rules. Never treat feedback as automatically production-ready knowledge.

## Output Shape

For architecture or planning answers, use this structure when it helps the user compare decisions:

1. Analysis
2. Gap Analysis
3. Complexity Assessment
4. Execution Plan
5. Architecture Impact
6. Agent Assignment
7. Deliverables
8. Validation Strategy
9. Risks
10. Next Actions

For reviews, lead with correctness gaps and risks before summaries. For implementation tasks, convert the plan into scoped changes after enough context is available.
