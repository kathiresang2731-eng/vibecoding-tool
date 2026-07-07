# Domain research

This package provides lightweight category hints and optional LLM-driven domain research for website generation.

- `profiles.py` holds keyword hints only (no static layouts, sections, or sample content).
- `context.py` builds a minimal hint context from prompt, memory, and brief text.
- `enrichment.py` merges LLM `applied` research into a prompt-analysis brief; hints do not inject templates.
- `inference.py` contains category detection and generic/no-specification predicates.
- `values.py` contains small safe extraction helpers.

When Gemini Google Search is enabled, the domain research agent returns an LLM-authored plan (`status: applied`). Otherwise only category hints are used and the generation LLM decides layout and design.

Import from `backend.agents.domain_research`; `__init__.py` keeps the previous public names stable.
