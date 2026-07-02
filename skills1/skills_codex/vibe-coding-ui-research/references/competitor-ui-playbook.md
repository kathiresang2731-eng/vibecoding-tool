# Competitor UI Research Playbook

Use this reference for current web research and UI planning for AI coding, vibe-coding, and agentic software engineering tools.

## Research Rule

Competitor UI and product features change quickly. Browse current sources for every serious recommendation. Prefer primary sources:

- Official docs.
- Product pages.
- Help centers.
- Changelogs and release notes.
- Official screenshots and videos.
- Official pricing or plan pages when cost or mode controls matter.

Use third-party reviews, news, social posts, or community threads only as perception signals. Label them separately from first-party feature evidence.

## Seed Competitors And Sources

Use this list as a starting point, then expand based on the user's product category.

| Product | Source starting points | Research focus |
| --- | --- | --- |
| Cursor | `cursor.com`, `cursor.com/docs` | AI IDE, codebase context, rules, agent tools, inline editing, diff review. |
| Claude Code | `code.claude.com/docs`, `claude.ai/code` | Terminal/IDE/web/desktop surfaces, multi-session work, permissions, plans, diffs, MCP, skills, background agents. |
| OpenAI Codex | `developers.openai.com/codex`, `chatgpt.com/codex` | Cloud coding agents, tasks, review loops, tools, background/streaming concepts, developer handoff. |
| GitHub Copilot | `docs.github.com/en/copilot` | Cloud agent, pull request workflow, issue assignment, IDE chat, CLI, sandbox, enterprise controls. |
| Replit Agent | `docs.replit.com/references/agent/overview` | Plain-language app generation, plan mode, agent modes, design canvas, checkpoints, task board, publishing. |
| Lovable | `docs.lovable.dev` | Natural-language full-stack app building, shared workspaces, GitHub sync, enterprise governance. |
| Bolt | `support.bolt.new` | Chatbox, code view, plan mode, token efficiency, design systems, integrations, publishing. |
| v0 | `v0.app/docs` | Prompt-to-UI/full-stack apps, design mode, Figma/screenshots/files, previews, deploy, PR, real-time feedback. |
| Devin / Cognition | `cognition.ai`, product docs and release notes when available | Autonomous software engineering tasks, planning, execution, review, status and artifact transparency. |
| Windsurf | Official Windsurf/Cognition docs and changelog | AI IDE workflows, repo context, agent/task UX, editor integration. |

## Web Search Query Patterns

Use specific current queries:

- `site:docs.<vendor-domain> agent mode plan mode UI`
- `<product> docs plan mode approvals checkpoints`
- `<product> AI coding agent dashboard task status`
- `<product> release notes agent UI preview deploy`
- `<product> official docs web search MCP GitHub sync`
- `<product> pricing token usage modes agent`

When official docs are sparse, search product pages and changelogs before blog posts.

## Competitor Matrix Template

Create a matrix like this:

| Competitor | Source | User journey | Key screens | Feature evidence | UX strength | UX weakness | Worktual implication |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Replit Agent | official docs URL | prompt -> plan -> build -> publish | chat, plan, editor, preview, task board | plan mode, modes, checkpoints | beginner-friendly, end-to-end | can hide technical risk | show plan approval and rollback clearly |

Add `accessed_date` when the research will be reused in docs.

## Feature Taxonomy

Classify findings under these groups:

### Request Intake

- Large prompt composer.
- Templates and examples.
- Attachments, screenshots, Figma, repository URL/path.
- Project type selector.
- Knowledge/recent-project suggestions.
- Privacy or PII notice.

### Planning And Approval

- Plan mode.
- Clarifying questions.
- Task list with accept/revise controls.
- Complexity and cost estimate.
- Human approval gates.
- Risk warnings.

### Workspace

- File tree.
- Code editor.
- Diff viewer.
- Terminal.
- Live preview.
- Design canvas.
- Logs and timeline.
- Artifact list.

### Agent Transparency

- Current task.
- Progress.
- Reasoning summary.
- Tool calls.
- Terminal commands.
- Background sessions.
- Queue and concurrency.
- Error recovery.

### Context And Memory

- Repository indexing.
- File mentions.
- Rules/instructions.
- MCP/connectors.
- Docs and knowledge base.
- Project memory.
- Scope selectors.

### Cost And Control

- Token usage.
- Model selection.
- Speed/quality/cost modes.
- Budget limits.
- Pause/resume/cancel.
- Retry and rollback.
- Checkpoints.

### Delivery

- GitHub sync.
- Pull request creation.
- One-click deploy/publish.
- Download/clone.
- Release notes.
- Test report.
- Share link.

### Enterprise Trust

- Roles and permissions.
- SSO/SCIM.
- Audit logs.
- Sandboxes.
- Secret handling.
- Data retention.
- Production safeguards.
- Compliance statements.

## Worktual Translation Rules

Translate competitor patterns into Worktual-specific design decisions:

- Keep the Chief Orchestrator visible as the owner of analysis and planning.
- Show all 10 MAS phases as a persistent workflow map, but disable phases not implemented yet.
- Make human approvals first-class UI elements, not modal afterthoughts.
- Surface cost and token budget early.
- Show repository/context sources with trust level and freshness.
- Show agent status with clear boundaries: pending, running, blocked, waiting approval, failed, completed.
- Separate `Plan`, `Build`, `Review`, and `Deploy` actions.
- Keep audit, rollback, and production-safety controls visible near risky actions.
- Prefer dense operational UI over marketing hero composition for app surfaces.

## Output Templates

### Research Summary

```markdown
## Sources Checked

| Source | Type | Accessed | Notes |
| --- | --- | --- | --- |

## Competitor Matrix

| Product | Intake | Planning | Workspace | Agent Transparency | Delivery | Governance |
| --- | --- | --- | --- | --- | --- | --- |

## Recommended Worktual Patterns

- ...

## Avoid

- ...

## UI Requirements

- Screen:
- Components:
- States:
- Data needed:
- Backend dependency:

## Open Questions

- ...
```

### UI Implementation Brief

```markdown
## Goal

## Research Basis

## User Journey

## Screens

## Component Inventory

## Data Contracts

## Responsive Behavior

## Accessibility And Trust

## Acceptance Criteria
```

## Quality Checklist

- Use at least three current sources for competitor benchmarking unless the user asks for one competitor only.
- Include source links beside competitor claims.
- Distinguish verified facts from design inference.
- Do not copy visual branding, exact UI copy, icons, or proprietary interaction details.
- Convert research into concrete UI requirements, not only observations.
- Include mobile and empty/loading/error states.
- Include security, cost, and human-control implications for autonomous coding tools.
