from backend.agents.requirement_confirmation.routing import confirmed_routing_result
from backend.agents.streaming.streaming_parity import clarification_stream_result


def test_confirmed_route_preserves_update_for_greenfield_like_update_brief() -> None:
  pending = {
    "operation": "website_update",
    "summary": "Build AI native farm website.",
    "planned_changes": ["Create scaffold and pages."],
  }
  route = confirmed_routing_result(pending, project_files=[])
  assert route["intent"] == "website_update"
  assert route["next_tool"] == "analyze_update_request"


def test_confirmed_route_preserves_standalone_code_update() -> None:
  pending = {
    "operation": "website_update",
    "summary": "Update the standalone Java neon number program.",
    "planned_changes": ["Simplify the Java code."],
  }
  route = confirmed_routing_result(
    pending,
    project_files=[{"path": "NeonNumber.java", "content": "public class NeonNumber {}"}],
  )
  assert route["intent"] == "simple_code"
  assert route["next_tool"] == "generate_simple_code_file"


def test_clarification_stream_result_includes_subheadline() -> None:
  result = clarification_stream_result("Which page should change?")
  assert result["generated_website"]["subheadline"] == "Which page should change?"
