import pytest

from backend.llm.a2a_communication import (
  A2A_PROTOCOL_VERSION,
  CANONICAL_HANDOFF_REQUIRED_FIELDS,
  A2AProtocolError,
  build_a2a_communication,
  validate_a2a_transcript,
)
from backend.llm.agentic_flow import execute_agentic_flow


def website_response():
  return {
    "multi_agent_system": {
      "intent": "website_generation",
      "routing_result": {
        "intent": "website_generation",
        "next_tool": "analyze_prompt",
        "reason": "The user requested a website.",
      },
      "conversation_response": {"message": "Generated the website preview from the provided prompt."},
      "shared_state": {"prompt": "Generate a CRM website"},
    },
    "orchestration_flow": {
      "generated_website": {
        "title": "AI Native CRM",
        "headline": "Close deals faster",
        "subheadline": "CRM for AI native teams.",
        "primary_cta": "Start",
        "secondary_cta": "Demo",
        "sections": [{"name": "Hero"}, {"name": "Features"}],
        "files": [{"path": "src/App.jsx"}, {"path": "package.json"}],
      }
    },
    "proactive_thinking": {"self_checks": ["Includes src/App.jsx"]},
  }


def conversation_response():
  return {
    "multi_agent_system": {
      "intent": "greeting",
      "routing_result": {
        "intent": "greeting",
        "next_tool": "handle_greeting",
        "reason": "The user only greeted.",
      },
      "conversation_response": {
        "message": "Hello. Tell me what website you want to build.",
        "next_prompt_guidance": ["Share website type", "Share brand name"],
      },
      "shared_state": {"prompt": "hi"},
    },
    "orchestration_flow": {"generated_website": {"files": []}},
    "proactive_thinking": {},
  }


def test_build_a2a_communication_for_website_generation_transcript():
  flow = execute_agentic_flow(website_response())
  transcript = build_a2a_communication(flow)

  assert transcript["protocol"] == A2A_PROTOCOL_VERSION
  assert transcript["branch"] == "website_generation"
  assert transcript["message_count"] == len(flow["steps"]) - 1
  assert transcript["ack_count"] == transcript["message_count"]
  assert transcript["validation"]["status"] == "valid"
  assert [message["sequence"] for message in transcript["messages"]] == list(range(1, len(flow["steps"])))
  assert transcript["messages"][0]["from_agent"] == "Orchestrator"
  assert transcript["messages"][0]["to_agent"] == "Context Agent"
  assert transcript["messages"][0]["from_internal_agent"] == "Intent Router Agent"
  assert transcript["messages"][0]["to_internal_agent"] == "Prompt Analyst Agent"
  assert transcript["messages"][2]["channel"] == "ux_review"
  assert transcript["messages"][3]["channel"] == "accessibility"
  assert transcript["messages"][4]["channel"] == "artifact"
  assert transcript["messages"][5]["payload"]["requested_tool_calls"] == ["VALIDATE_PROJECT_ARTIFACT"]
  assert transcript["messages"][6]["channel"] == "preview"
  assert transcript["messages"][7]["channel"] == "visual_qa"
  assert transcript["messages"][9]["payload"]["requested_tool_calls"] == ["PERSIST_PROJECT_MEMORY"]
  for message in transcript["messages"]:
    for field in CANONICAL_HANDOFF_REQUIRED_FIELDS:
      assert field in message
    assert message["sender"] == message["from_agent"]
    assert message["receiver"] == message["to_agent"]
    assert message["next_action"] == message["intent"]
    assert isinstance(message["input"], dict)
    assert isinstance(message["output"], dict)
    assert 0 <= message["confidence"] <= 1
    assert message["payload"]["handoff_contract"]["next_action"] == message["next_action"]


def test_build_a2a_communication_for_conversation_never_hands_off_to_code_agent():
  flow = execute_agentic_flow(conversation_response())
  transcript = build_a2a_communication(flow)

  assert transcript["branch"] == "conversation"
  assert [message["to_agent"] for message in transcript["messages"]] == [
    "Orchestrator",
    "Context Agent",
  ]
  assert [message["to_internal_agent"] for message in transcript["messages"]] == [
    "Intent Router Agent",
    "Memory Agent",
  ]
  assert all(message["channel"] != "artifact" for message in transcript["messages"])


def test_build_a2a_communication_prefers_real_mas_handoffs():
  flow = {
    "runtime": "worktual-real-agent-runtime-loop",
    "branch": "website_generation",
    "steps": [
      {"agent": "Legacy Projection Agent", "action": "legacy_projection", "input": {}, "output": {}},
    ],
    "mas_runtime": {
      "handoffs": [
        {
          "from_agent": "Memory Agent",
          "to_agent": "Validation Agent",
          "from_action": "READ_PROJECT_FILES",
          "to_action": "VALIDATE_PROJECT_ARTIFACT",
          "input": {"action": "VALIDATE_PROJECT_ARTIFACT"},
          "output": {"file_count": 4},
          "requested_tool_calls": ["VALIDATE_PROJECT_ARTIFACT"],
          "source": "real_mas_runtime",
        }
      ]
    },
  }

  transcript = build_a2a_communication(flow)

  assert transcript["source_of_truth"] is True
  assert transcript["projection_source"] == "mas_runtime_handoffs"
  assert transcript["message_count"] == 1
  assert transcript["messages"][0]["from_agent"] == "Memory Agent"
  assert transcript["messages"][0]["to_agent"] == "Validation Agent"
  assert transcript["messages"][0]["channel"] == "validation"
  assert transcript["messages"][0]["payload"]["requested_tool_calls"] == ["VALIDATE_PROJECT_ARTIFACT"]
  assert transcript["validation"]["status"] == "valid"


def test_validate_a2a_transcript_rejects_missing_acknowledgement():
  flow = execute_agentic_flow(website_response())
  transcript = build_a2a_communication(flow)
  transcript["acknowledgements"] = transcript["acknowledgements"][1:]

  with pytest.raises(A2AProtocolError):
    validate_a2a_transcript(transcript)


def test_validate_a2a_transcript_rejects_missing_canonical_handoff_field():
  flow = execute_agentic_flow(website_response())
  transcript = build_a2a_communication(flow)
  transcript["messages"][0].pop("task")

  with pytest.raises(A2AProtocolError, match="canonical handoff field"):
    validate_a2a_transcript(transcript)
