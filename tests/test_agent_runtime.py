from backend.agent_runtime import build_agent_run_input, persist_agent_runtime_output


class FakeRuntimeStore:
  def __init__(self):
    self.messages = []
    self.tool_calls = []
    self.checkpoints = []
    self.memories = []

  def record_agent_message(self, agent_run_id, user, **kwargs):
    self.messages.append({"agent_run_id": agent_run_id, **kwargs})
    return self.messages[-1]

  def record_tool_call(self, agent_run_id, user, **kwargs):
    self.tool_calls.append({"agent_run_id": agent_run_id, **kwargs})
    return self.tool_calls[-1]

  def record_generation_checkpoint(self, agent_run_id, user, **kwargs):
    self.checkpoints.append({"agent_run_id": agent_run_id, **kwargs})
    return self.checkpoints[-1]

  def upsert_memory_item(self, user, **kwargs):
    self.memories.append(kwargs)
    return self.memories[-1]


def test_build_agent_run_input_uses_auditable_messages_without_private_thinking():
  payload = build_agent_run_input(
    project={"id": "project-1", "name": "CRM", "local_path": None},
    prompt="Generate a CRM website",
    provider="gemini",
    model="gemini-3.1-pro-preview",
  )

  assert payload["project"]["id"] == "project-1"
  assert payload["provider"] == "gemini"
  assert payload["messages"][0]["role"] == "system"
  assert payload["messages"][1] == {"role": "user", "content": "Generate a CRM website"}
  assert "thinking" not in str(payload).lower()


def test_persist_agent_runtime_output_records_messages_tools_checkpoint_and_memory():
  store = FakeRuntimeStore()
  user = type("User", (), {"id": "user-1"})()
  generation = {
    "multi_agent_system": {
      "intent": "website_generation",
      "active_agent": "Prompt Analyst Agent",
      "routing_result": {
        "intent": "website_generation",
        "next_action": "generate_website",
        "next_tool": "analyze_prompt",
        "reason": "The user asked for a website.",
      },
      "conversation_response": {"message": "Generated the website preview from the provided prompt."},
    },
    "gemini_tool_calling_setup": {
      "tool_call_sequence": [
        "route_generation_action",
        "analyze_prompt",
        "generate_website_files",
        "validate_generated_website",
      ]
    },
    "orchestration_flow": {
      "generated_website": {
        "title": "AI Native CRM",
        "sections": [{"name": "Hero"}, {"name": "Features"}],
        "files": [{"path": "src/App.jsx"}],
      }
    },
    "agent_to_agent_communication": {
      "message_contract": {
        "from_agent": "Prompt Analyst Agent",
        "to_agent": "Prescriptive Builder Agent",
        "task": "Build the website artifact from the routed prompt.",
      }
    },
  }

  persist_agent_runtime_output(
    store,
    agent_run_id="agent-run-1",
    user=user,
    prompt="Generate the website for AI native CRM",
    generation=generation,
    generation_run={"id": "run-1", "project_id": "project-1"},
    files=[{"path": "src/App.jsx", "content": "export default function App() {}"}],
    local_sync=None,
    local_sync_error=None,
  )

  assert [message["role"] for message in store.messages] == ["user", "agent", "assistant"]
  assert [call["tool_name"] for call in store.tool_calls] == [
    "route_generation_action",
    "analyze_prompt",
    "generate_website_files",
    "validate_generated_website",
  ]
  assert store.checkpoints[0]["thread_id"] == "run-1"
  assert store.checkpoints[0]["state"]["intent"] == "website_generation"
  assert store.memories[0]["namespace"] == "project"
  assert store.memories[0]["key"] == "latest_generation_summary"
  assert "AI Native CRM" in store.memories[0]["content"]
  assert "thinking" not in store.memories[0]["content"].lower()


def test_persist_agent_runtime_output_records_agentic_handoffs_as_agent_messages():
  store = FakeRuntimeStore()
  user = type("User", (), {"id": "user-1"})()
  generation = {
    "multi_agent_system": {
      "intent": "greeting",
      "active_agent": "Conversation Agent",
      "routing_result": {
        "intent": "greeting",
        "next_tool": "handle_greeting",
        "reason": "Greeting only.",
      },
      "conversation_response": {"message": "Hello. Share your website brief."},
    },
    "gemini_tool_calling_setup": {
      "runtime_trace": {
        "tool_calls": [
          {
            "call_id": "route-1",
            "name": "route_generation_action",
            "arguments": {"message": "hi"},
            "output": {"intent": "greeting"},
          }
        ]
      }
    },
    "orchestration_flow": {"generated_website": {"files": []}},
    "agent_to_agent_communication": {
      "agentic_handoffs": [
        {
          "from_agent": "Intent Router Agent",
          "to_agent": "Conversation Agent",
          "status": "completed",
          "message": {"next_action": "respond_without_file_generation"},
        }
      ]
    },
  }

  persist_agent_runtime_output(
    store,
    agent_run_id="agent-run-1",
    user=user,
    prompt="hi",
    generation=generation,
    generation_run={"id": "run-1", "project_id": "project-1"},
    files=[],
    local_sync=None,
    local_sync_error=None,
  )

  agent_messages = [message for message in store.messages if message["role"] == "agent"]
  assert len(agent_messages) == 1
  assert agent_messages[0]["from_agent"] == "Intent Router Agent"
  assert agent_messages[0]["to_agent"] == "Conversation Agent"
  assert agent_messages[0]["content"] == "respond_without_file_generation"


def test_persist_agent_runtime_output_records_a2a_messages_before_legacy_handoffs():
  store = FakeRuntimeStore()
  user = type("User", (), {"id": "user-1"})()
  generation = {
    "multi_agent_system": {
      "intent": "website_generation",
      "active_agent": "Prompt Analyst Agent",
      "routing_result": {
        "intent": "website_generation",
        "next_tool": "analyze_prompt",
        "reason": "Website request.",
      },
      "conversation_response": {"message": "Generated the website preview from the provided prompt."},
    },
    "gemini_tool_calling_setup": {"tool_call_sequence": ["route_generation_action"]},
    "orchestration_flow": {
      "generated_website": {
        "title": "AI Native CRM",
        "sections": [{"name": "Hero"}],
        "files": [{"path": "src/App.jsx"}],
      }
    },
    "agent_to_agent_communication": {
      "a2a_runtime": {
        "messages": [
          {
            "message_id": "a2a-1-intent-router-agent-to-prompt-analyst-agent",
            "from_agent": "Intent Router Agent",
            "to_agent": "Prompt Analyst Agent",
            "intent": "extract_website_brief",
          }
        ]
      },
      "agentic_handoffs": [
        {
          "from_agent": "Legacy Agent",
          "to_agent": "Legacy Target",
          "message": {"next_action": "legacy_handoff"},
        }
      ],
    },
  }

  persist_agent_runtime_output(
    store,
    agent_run_id="agent-run-1",
    user=user,
    prompt="Generate a CRM website",
    generation=generation,
    generation_run={"id": "run-1", "project_id": "project-1"},
    files=[{"path": "src/App.jsx", "content": "export default function App() {}"}],
    local_sync=None,
    local_sync_error=None,
  )

  agent_messages = [message for message in store.messages if message["role"] == "agent"]
  assert len(agent_messages) == 1
  assert agent_messages[0]["from_agent"] == "Intent Router Agent"
  assert agent_messages[0]["to_agent"] == "Prompt Analyst Agent"
  assert agent_messages[0]["content"] == "extract_website_brief"
  assert agent_messages[0]["payload"]["message_id"] == "a2a-1-intent-router-agent-to-prompt-analyst-agent"
