# Worktual AI Website Builder: Complete Flow Documentation

## 1. Executive Summary

Worktual AI Website Builder is an AI-native website generation and update platform. It is not a static template builder. The platform accepts a user prompt, routes the request, prepares project context, coordinates AI agents and backend tools, generates or patches React/Vite website files, validates the artifact, builds a preview, runs visual QA, persists files, and records runtime memory for future reuse.

The system has two major paths:

- Website generation: creates a new website from a prompt and project context.
- Website update: reads the existing project, analyzes the requested change, applies deterministic or scoped SEARCH/REPLACE edits, validates the result, and rebuilds the preview.

## 2. User Query Entry Points

The user interacts through the React application in `src/main.jsx`. Prompts are submitted from the chat/workspace panel and sent to backend generation endpoints. The backend request enters through the API layer in `backend/main.py` and `backend/api/generation.py`.

The key entry sequence is:

1. User selects or creates a project.
2. User types a website generation or update prompt.
3. Frontend sends the request to the backend generation API.
4. Backend loads project permissions, current files, local workspace state, and telemetry context.
5. Backend calls `generate_website` with Gemini providers and tool runtime context.
6. Runtime progress events stream back to the UI.

## 3. High-Level Runtime Flow

```text
User Prompt
  -> Frontend Workspace
  -> FastAPI generation endpoint
  -> Generation pipeline
  -> Gemini route_generation_action
  -> Orchestrator stage graph
  -> Real agent/tool runtime loop
  -> Backend tools
  -> Artifact validation
  -> Staged preview build
  -> Visual QA
  -> WRITE_PROJECT_FILES
  -> Local folder sync
  -> Runtime memory persistence
  -> UI progress + preview
```

## 4. What the Website Builder Does

The builder manages the entire lifecycle of an AI-created website:

- Creates backend or local-folder-linked projects.
- Imports existing browser-selected project folders when files are present.
- Allows empty local folders as valid new workspaces.
- Reads existing project files before updates.
- Routes prompts into greeting, clarification, generation, or update paths.
- Uses Gemini for control-plane decisions and artifact generation.
- Uses backend tools for file IO, validation, preview building, visual QA, and persistence.
- Generates React/Vite/Tailwind projects with modular components.
- Applies scoped updates using explicit SEARCH/REPLACE blocks.
- Builds previews from staged candidate files before writing final files.
- Persists agent runtime, tool calls, memory, and reusable dynamic agents.

## 5. Main AI Agents

The platform uses a mix of canonical agents, runtime agents, and dynamic specialist agents.

| Agent / Stage | Primary Responsibility |
| --- | --- |
| Intent Router Agent | Uses `route_generation_action` to classify greeting, needs-more-detail, generation, or update. |
| Greeting Handler Agent | Responds to greeting-only turns and requests a useful website brief. |
| Prompt Analyst Agent | Converts the user prompt and project context into a structured website brief. |
| Requirement Confirmation Agent | Prepares and evaluates confirmation briefs when a request needs explicit confirmation. |
| Domain Research Agent | Enriches vague or domain-specific prompts with audience, goal, style, sections, interactions, and sample domain data. |
| UX/Layout Agent | Plans website structure, page modules, content flow, interaction patterns, and responsive behavior. |
| Accessibility Agent | Checks semantic structure, contrast, keyboard flow, labels, and mobile fit. |
| Dynamic Task Decomposer | Breaks complex requests into capability tasks. |
| Dynamic Workflow Planner | Builds a guarded workflow plan and parallel execution groups. |
| Dynamic Specialist Agents | Execute bounded domain/capability tasks such as content strategy, component UI, CRM pipeline, RBAC, e-commerce catalog, or support flows. |
| Code Generator Agent | Produces the strict website artifact JSON and project files. |
| Scoped Update Agent | Produces explicit SEARCH/REPLACE edits for existing code updates. |
| Repair Agent | Repairs invalid artifacts, build failures, or preview QA failures where safe. |
| Memory Agent | Loads and persists project/user memory and reusable dynamic agent definitions. |

## 6. Dynamic Agents

Dynamic agents allow the system to create and reuse specialists for specific capabilities. They are implemented under `backend/agents/dynamic_agenting`.

### How dynamic agents are created

1. The runtime infers the website domain and request scope.
2. The task decomposer creates capability tasks.
3. The registry searches for an existing agent with matching capability and domain.
4. If no reusable agent exists and policy permits creation, the dynamic agent factory asks the model for a reusable agent definition.
5. Python sanitizes the definition so it is not project-specific, cannot write files directly, and can only use allowed backend tools.
6. The agent is registered as experimental and assigned to the workflow.

### How dynamic agents are reused

Reusable agents are stored per user. On future runs:

1. Project memory is loaded.
2. Stored dynamic agent definitions are hydrated into the runtime registry.
3. The registry scores agents by capability, supported domain, success rate, usage count, and lifecycle.
4. The best matching reusable agent is assigned to a task.
5. Successful agents can be promoted from experimental to reusable after meeting promotion thresholds.
6. Unsafe or project-specific agents are rejected during hydration or persistence.

### Dynamic agent safety boundaries

- Direct file writes are disabled for dynamic agents.
- Python remains the source of truth for tool execution.
- Candidate changes are bounded by file count and byte limits.
- Only whitelisted backend tools are available.
- Project-specific prompts are rejected or replaced with reusable generic prompts.
- Lifecycle states include core, experimental, reusable, and disabled.

## 7. Orchestrator Flow

The orchestrator lives primarily in `backend/agents/orchestration/runner.py` and the real runtime loop lives behind `backend/agents/agent_runtime_loop.py` and `backend/agents/agent_runtime`.

Core stages:

1. `route_generation_action`: classify intent.
2. `multi_agent_system`: prepare runtime metadata and selected agent model.
3. `gemini_tool_calling_setup`: describe Gemini tools and expected tool sequence.
4. `google_adk_usage`: attach Google ADK mapping and runtime metadata.
5. `orchestration_flow`: run conversation response or real artifact runtime.
6. `agent_to_agent_communication`: build handoff transcript and channel metadata.
7. `proactive_thinking`: attach execution trace, self-checks, and completion proof.

For generation/update requests with project context, the orchestrator runs the real tool loop:

```text
READ_PROJECT_FILES
LOAD_PROJECT_MEMORY
RUN_PROMPT_ANALYST or RUN_UPDATE_ANALYST
RUN_DYNAMIC_AGENT_PLANNER
RUN_DYNAMIC_SPECIALISTS
RUN_PLANNER
RUN_UX_REVIEW_AGENT
RUN_ACCESSIBILITY_AGENT
RUN_CODE_AGENT or RUN_SCOPED_UPDATE_AGENT
VALIDATE_PROJECT_ARTIFACT
BUILD_STAGED_PROJECT_PREVIEW
RUN_PREVIEW_VISUAL_QA
WRITE_PROJECT_FILES
PERSIST_PROJECT_MEMORY
```

## 8. Gemini Tool Calling Process

Gemini is used in two provider roles:

- Control provider: routing, analysis, planning, review, and tool decisions.
- Artifact provider: website artifact generation and scoped update patch generation.

The native Gemini tool-calling loop is implemented in `backend/agents/gemini_tool_calling/loop.py`.

Process:

1. Python converts backend tool schemas into Gemini function declarations.
2. Gemini receives conversation messages and available tools.
3. Gemini may return one or more function calls.
4. Python validates and executes the requested backend tool.
5. Tool result is appended as a function response.
6. Gemini continues until it returns final text or the max step limit is reached.
7. Python logs model calls, tool calls, results, failures, and token usage.

The safety principle is simple: Gemini can request tools, but Python validates and executes tools.

## 9. Google ADK Usage

Google ADK support is represented as runtime metadata and projection under `backend/agents/google_adk_runtime`.

It provides:

- ADK agent plan.
- ADK tool specifications.
- Session/event projection from real Python runtime steps.
- Validation of agent order, tool references, and events.
- Optional runner metadata when the `google-adk` package is installed.

ADK is not the sole execution engine. The current reliable execution path is Python-owned, with ADK used as a structured mapping/projection layer.

## 10. LangChain / LangGraph Usage

LangChain support lives under `backend/agents/langchain_runtime_impl`.

It provides:

- A compatibility projection of runtime steps into LangGraph-style nodes and edges.
- Thread IDs and thread configuration.
- LangChain message construction from prompt and memory.
- Validation of graph nodes and runtime contract.
- Optional actual LangGraph app creation when dependencies are installed.

LangChain is therefore an integration/projection layer, not the primary authority for file writes or validation.

## 11. Agent-to-Agent Communication

Agent-to-agent communication is implemented under `backend/agents/a2a`.

The A2A layer builds a transcript from runtime steps:

- Handoff messages.
- Acknowledgements.
- Canonical fields.
- Confidence scores.
- Channel routing.
- Validation of sequencing and acknowledgement rules.

The public response includes agent-to-agent communication so the UI and audit layer can explain how work moved from analyst to planner, specialist, code agent, validator, preview builder, and memory agent.

## 12. Backend Tool Registry

Backend tools live under `backend/agentic/tools`.

Important tools:

| Tool | Purpose |
| --- | --- |
| READ_PROJECT_FILES | Reads supported website files from backend store or linked local workspace. |
| LOAD_PROJECT_MEMORY | Loads persisted memory and reusable dynamic agent definitions. |
| PERSIST_PROJECT_MEMORY | Stores final project memory and dynamic agent registry snapshots. |
| WRITE_PROJECT_FILES | Commits validated files to the project store and linked local folder if available. |
| VALIDATE_PROJECT_ARTIFACT | Validates generated website structure, theme, files, and React file safety. |
| BUILD_STAGED_PROJECT_PREVIEW | Builds a preview from candidate files before commit. |
| RUN_PREVIEW_VISUAL_QA | Checks staged preview integrity. |
| SYNC_LOCAL_PROJECT | Pulls or pushes files between backend store and linked local workspace. |

## 13. Website Generation Contract

The generated website artifact uses a strict JSON contract:

- `generated_website.title`
- `headline`
- `subheadline`
- `primary_cta`
- `secondary_cta`
- `preview_html`
- `theme`
- `design_tokens`
- `component_manifest`
- `seo`
- `compliance`
- `sections`
- `files`
- `implementation_notes`

Generated projects are expected to be React/Vite/Tailwind projects. Modern generation requires modular component structure:

- `src/App.jsx` as a thin composition shell.
- `src/components/*` for reusable UI.
- `src/pages/*` for route-backed modules.
- `src/data/*` for realistic content/data.
- `src/theme/tokens.js` for design tokens.
- `src/seo/schema.js` or equivalent for JSON-LD/SEO.

## 14. Design Tokens and Brand Logic

The platform does not use a static color palette. Token selection follows this priority:

1. Use user-provided brand guidelines as the source of truth.
2. If unsafe, minimally adjust contrast and document the reason.
3. If no brand is provided, infer tokens dynamically from domain, audience, business maturity, region, and requested style.
4. Mark token source as `user`, `inferred`, or `adjusted_for_accessibility`.

Token categories:

- Colors: primary, secondary, accent, neutral dark, neutral light.
- Typography: font pairing, H1-H6 scale, body scale, tracking.
- Layout: philosophy, grid, max width, spacing, section padding.
- Motion: duration, easing, interaction pattern.

## 15. Website Update Flow

Update requests follow a stricter path than first generation:

1. Read the complete existing project files.
2. Analyze the update request.
3. Choose deterministic patch, scoped model patch, feature patch, or full workflow.
4. For scoped updates, Gemini must emit explicit SEARCH/REPLACE blocks.
5. Python parses and validates each edit against current file contents.
6. Candidate files are integrated.
7. Staged preview is built and QA is run.
8. Files are committed only after validation.

This prevents the earlier failure mode where a model asked the user for the top of `src/App.jsx` even though the backend should provide full current file context.

## 16. Local Workspace and Folder Handling

The builder supports:

- Backend-only projects.
- Browser-selected local folders.
- Browser-uploaded folders.
- Server-local folders under allowed workspace roots.
- Empty folder selection for new projects.
- Existing folder import when valid project files exist.

Empty folders are valid because users may want AI to generate the first project into a newly created folder. Existing projects with files are validated to ensure the root contains expected website files.

## 17. Validation, Preview, and Persistence

Validation and preview are Python-owned:

- Artifact validation checks required fields, allowed file paths, valid colors, required `src/App.jsx`, and React import safety.
- Staged preview builds before final commit.
- Visual QA checks preview readiness.
- File persistence writes to backend store and linked local folder.
- Runtime output persists agent runs, tool calls, memory, generated website metadata, local sync status, and reusable dynamic agent definitions.

## 18. Failure Handling

Failure classification is handled under `backend/api/failures.py`.

Common categories:

- Routing/control model failure.
- Gemini artifact failure.
- Scoped update guard failure.
- Local workspace sync failure.
- Preview build failure.
- Runtime timeout.
- Validation failure.

Failures are normalized into user-facing error payloads with category, code, model/provider hint, elapsed time, and last runtime step where available.

## 19. Important Source Map

| Area | Key Files |
| --- | --- |
| Frontend workspace and chat | `src/main.jsx` |
| API endpoints | `backend/main.py` |
| Generation API pipeline | `backend/api/generation.py`, `backend/api/generation_stream.py` |
| Prompt contracts | `backend/agents/prompting/*` |
| Gemini client | `backend/agents/gemini_client/*` |
| Gemini tool calling | `backend/agents/gemini_tool_calling/*` |
| Orchestrator | `backend/agents/orchestration/*`, `backend/agents/orchestrator.py` |
| Real runtime loop | `backend/agents/agent_runtime_loop.py`, `backend/agents/agent_runtime/*` |
| Dynamic agents | `backend/agents/dynamic_agenting/*` |
| Backend tools | `backend/agentic/tools/*` |
| Google ADK projection | `backend/agents/google_adk_runtime/*` |
| LangChain projection | `backend/agents/langchain_runtime_impl/*` |
| A2A projection | `backend/agents/a2a/*` |
| Artifact validation | `backend/agents/artifacts/*` |
| Local workspace sync | `backend/local_workspace/*`, `backend/api/local_workspaces.py` |
| Runtime persistence | `backend/agentic/runtime_persistence/*` |

## 20. Operational Summary

The website builder is an enterprise AI-native generation platform. The model is not trusted to directly mutate disk. Gemini reasons, routes, plans, and proposes outputs. Python validates, executes tools, builds previews, writes files, and persists runtime memory. Dynamic agents improve specialization over time through a guarded registry and user-scoped reuse. ADK, LangChain, and A2A projections make the runtime portable and explainable without taking authority away from the backend validation and execution layer.
