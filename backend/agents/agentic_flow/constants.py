from __future__ import annotations


AGENTIC_RUNTIME_NAME = "worktual-python-agentic-flow"

AGENT_ROSTER = [
  {
    "name": "Intent Router Agent",
    "mode": "diagnostic",
    "responsibility": "Classify the user turn and choose the next backend branch.",
  },
  {
    "name": "Conversation Agent",
    "mode": "descriptive",
    "responsibility": "Reply to greetings or ask for missing website details without creating files.",
  },
  {
    "name": "Supervisor Agent",
    "mode": "diagnostic",
    "responsibility": "Choose the next specialist agent and tool set from current runtime state.",
  },
  {
    "name": "Prompt Analyst Agent",
    "mode": "descriptive",
    "responsibility": "Extract website goal, audience context, brand cues, and section requirements.",
  },
  {
    "name": "Planner Agent",
    "mode": "predictive",
    "responsibility": "Plan section order, interaction priorities, and conversion path.",
  },
  {
    "name": "UX Review Agent",
    "mode": "diagnostic",
    "responsibility": "Review the planned website for workflow, conversion clarity, responsive layout, and content gaps.",
  },
  {
    "name": "Accessibility Agent",
    "mode": "diagnostic",
    "responsibility": "Review planned UI for contrast, semantic structure, keyboard flow, and mobile text fit.",
  },
  {
    "name": "Code Agent",
    "mode": "prescriptive",
    "responsibility": "Produce project files and package editable code artifacts.",
  },
  {
    "name": "Validation Agent",
    "mode": "diagnostic",
    "responsibility": "Validate generated website structure, paths, theme, and preview readiness.",
  },
  {
    "name": "Preview Agent",
    "mode": "diagnostic",
    "responsibility": "Build the generated project preview through the backend runtime tool.",
  },
  {
    "name": "Visual QA Agent",
    "mode": "diagnostic",
    "responsibility": "Run backend preview integrity QA before generated files are committed.",
  },
  {
    "name": "Repair Agent",
    "mode": "prescriptive",
    "responsibility": "Regenerate and restore project files when validation or preview build fails.",
  },
  {
    "name": "Memory Agent",
    "mode": "descriptive",
    "responsibility": "Prepare concise project memory for future turns.",
  },
]
