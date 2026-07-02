# Eight-Phase Agentic Flow Blueprint

Use this reference when planning or implementing a production-grade adaptive agentic workflow.

## Phase 1: Chief Orchestrator Core

Goal: replace fixed pipeline entry with a central decision layer.

Build:

- `ChiefOrchestrator`
- `TaskUnderstanding`
- `TaskDecision`
- `RiskAssessment`
- `WorkflowDecision`

Decision output should include:

```json
{
  "task_type": "repo_edit",
  "complexity": "medium",
  "risk": "low",
  "needs_repo_context": true,
  "needs_write": true,
  "needs_approval": false,
  "workflow": ["context", "writer", "validation"],
  "reason": "Small repo edit requiring existing file context"
}
```

Success criteria:

- Simple tasks bypass heavy orchestration.
- Read-only tasks never reach writer.
- High-risk tasks identify approval needs before execution.

## Phase 2: Agent Registry

Goal: make agent selection data-driven.

Create an `AgentRegistry` with static built-in agents first:

- Intent or requirement analyzer
- Planner
- Context retriever
- Writer
- Tester
- Reviewer
- Security reviewer
- Deployment agent
- Documentation agent

Each agent metadata record should define:

```text
id
description
capabilities
accepted_task_types
required_inputs
outputs
can_write_files
can_run_commands
risk_level
cost_level
latency_level
approval_requirements
fallback_agent
```

Success criteria:

- The orchestrator selects agents from registry metadata.
- Adding a new agent does not require editing every workflow branch.

## Phase 3: Dynamic Workflow Builder

Goal: build runtime workflows from task decisions.

Common workflow templates:

```text
simple_code -> simple_writer
chat -> responder
repo_question -> context -> responder
small_edit -> context -> writer -> diff
debug -> context -> debug_agent -> writer -> tester
feature -> planner -> context -> writer -> tester -> reviewer
deploy -> planner -> security -> approval -> deployment -> verification
```

Implementation guidance:

- Keep workflow templates declarative.
- Allow conditional nodes such as approval, testing, and review.
- Store workflow state separately from user session memory.

Success criteria:

- The system can explain why a workflow was chosen.
- Workflow changes do not require rewriting agent internals.

## Phase 4: Domain Orchestrators

Goal: avoid overloading the Chief Orchestrator with specialist coordination.

Introduce domain orchestrators when workflows become complex:

- `CodingOrchestrator`
- `TestingOrchestrator`
- `ResearchOrchestrator`
- `SecurityOrchestrator`
- `DeploymentOrchestrator`

The Chief Orchestrator delegates goals, constraints, and success criteria. Domain orchestrators select specialists and return structured results.

Success criteria:

- Large tasks are decomposed by domain.
- Chief Orchestrator remains focused on route, risk, approvals, and delivery.

## Phase 5: Agent Spawning

Goal: create temporary specialists only when useful.

Spawn conditions:

- Missing capability in registry.
- Framework-specific expert needed.
- Independent parallel investigation is safe.
- High-risk change needs independent review.

Spawn record should include:

```text
spawn_id
parent_workflow_id
specialty
mission
inputs
allowed_tools
write_permissions
time_budget
expected_output_schema
termination_condition
```

Examples:

- React UI specialist
- FastAPI backend specialist
- SQL migration specialist
- Docker deployment specialist
- Security reviewer
- Performance reviewer

Success criteria:

- Simple tasks never spawn agents.
- Spawned agents have bounded scope and explicit output contracts.

## Phase 6: Approval Gates And Safety Policy

Goal: make risky actions explicit and user-approved.

Require approval for:

- File deletion.
- Large multi-file rewrites.
- Secret, auth, payment, production, or security changes.
- Dependency installation.
- Shell commands with side effects.
- Database migrations.
- Deployment.

Approval request should include:

```text
requested action
why it is needed
files/commands affected
risk
rollback plan
continue/cancel options
```

Success criteria:

- The workflow pauses before risky actions.
- Approval state is recorded in decision memory.

## Phase 7: Validation, Testing, And Review Loop

Goal: deliver verified outcomes, not just generated code.

Validation flow:

```text
writer result
-> syntax check
-> unit/integration tests when available
-> diff review
-> security review if flagged
-> repair loop if validation fails
-> final response
```

Validation result should record:

```text
checks_run
passed
failed
failure_reason
repair_attempts
remaining_risk
```

Success criteria:

- The final response distinguishes verified work from unverified work.
- Failed validation can route back to writer or tester with clear context.

## Phase 8: Memory, Observability, And Learning

Goal: make the system debuggable and improvable.

Memory layers:

- Working memory: current workflow state and intermediate artifacts.
- Project memory: repo facts, active files, user goals, recent edits.
- Decision memory: selected route, reason, risk, approvals, validation.
- Knowledge memory: reusable patterns promoted after review.

Observability events:

```text
request_received
decision_made
agent_selected
agent_started
agent_finished
tool_called
approval_requested
approval_resolved
validation_finished
workflow_finished
workflow_failed
```

Metrics:

```text
latency_by_agent
token_or_api_cost
workflow_success_rate
validation_failure_rate
approval_frequency
repair_attempt_count
fallback_frequency
```

Success criteria:

- Each workflow can be replayed or audited from logs.
- Routing quality can be improved using observed failures.

## Recommended Migration Order

For an existing fixed pipeline:

1. Add Chief Orchestrator decision object.
2. Add registry metadata around existing agents.
3. Add dynamic workflow templates.
4. Move simple-task shortcuts into Chief Orchestrator.
5. Add approval gates.
6. Add validation/test loop.
7. Add domain orchestrators.
8. Add bounded agent spawning.
9. Add observability and decision memory.

Do not begin with spawning. Without registry, workflow policy, and approval gates, spawning becomes hard to reason about and hard to test.
