# Agent System

This is the source of truth for the backend AI and agent runtime.

## Start Here

- `runtime_agents/`: agent-wise map, action ownership, and handler entrypoints.
- `tools/`: canonical facade for tools used by runtime agents.
- `orchestration/`: coordinates routing, conversation, generation, and final responses.
- `agent_runtime/`: executes supervised tool actions and scoped project updates.
- `providers/`: provider-neutral interfaces and Gemini/OpenAI implementations.
- `generator/`: normalizes and validates website-generation results.
- `artifacts/`: validates generated project files and paths.
- `prompting/`: prompt contracts, builders, and shared instructions.
- `schema/`: response contracts and JSON-safe serialization.

## Advanced Runtime

- `graph_runtime/`: LangGraph-backed orchestration and resumable state.
- `dynamic_agenting/`: creates and manages bounded specialist agents.
- `agentic_flow/`: agent handoffs, memory, and flow projection.
- `agentic_evals/`: deterministic quality and failure evaluation.
- `mas/`: multi-agent-system contracts and execution controls.
- `a2a/`: agent-to-agent message contracts and transcripts.

## Provider Integrations

- `gemini_client/`: Gemini transport, parsing, and token usage.
- `gemini_tool_calling/`: Gemini tool-call loop.
- `openai_tool_calling/`: OpenAI tool-call loop.
- `google_adk_runtime/`: Google ADK projection and execution.
- `langchain_runtime_impl/`: LangChain runtime integration.
- `adk_mapping_impl/`: ADK response mapping.

Compatibility facades remain for established imports such as
`backend.agents.orchestrator` and `backend.agents.agent_runtime_loop`. The old
`backend.llm.*` namespace is also supported, but new code should use
`backend.agents.*`.
