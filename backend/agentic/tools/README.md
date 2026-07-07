# Agentic Website Tools

The runtime loop executes all project-affecting actions through this package.

- `definitions.py`: tool dataclasses and runtime context.
- `registry.py`: public tool registry, OpenAI schemas, and execution wrapper.
- `handlers.py`: concrete tool implementations for files, memory, preview builds, visual QA, and local sync.
- `validators.py`: shared argument validation and file payload normalization.

`backend.agent_tools` is a compatibility facade. Keep new tool behavior in this package.
