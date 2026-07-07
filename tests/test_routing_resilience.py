from backend.agents.gemini_client.parsing import parse_json_text, salvage_json_string_fields
from backend.agents.orchestration.routing import (
  heuristic_routing_result,
  normalize_routing_result,
  routing_fallback_after_model_error,
  salvage_routing_from_error,
)


MALFORMED_ROUTING_JSON = """{
  "intent": "website_generation",
  "next_action": "generate_website",
  "next_tool": "analyze_prompt",
  "reason": "The user has provided concrete specifications for the Aiccaas website, including specific pages, 7 communication channels, a color scheme, and a Python backend stack."
."
."
."
"
}"""


def test_salvage_json_string_fields_recovers_routing_object() -> None:
  salvaged = salvage_json_string_fields(
    MALFORMED_ROUTING_JSON,
    fields=("intent", "next_action", "next_tool", "reason"),
    required=("intent",),
  )
  assert salvaged is not None
  assert salvaged["intent"] == "website_generation"
  assert salvaged["next_tool"] == "analyze_prompt"
  assert "Python backend stack" in salvaged["reason"]


def test_parse_json_text_salvages_trailing_garbage() -> None:
  parsed = parse_json_text(MALFORMED_ROUTING_JSON)
  assert parsed["intent"] == "website_generation"


def test_normalize_routing_result_truncates_long_reason() -> None:
  normalized = normalize_routing_result(
    {
      "intent": "website_generation",
      "next_action": "generate_website",
      "next_tool": "analyze_prompt",
      "reason": "x" * 300,
    }
  )
  assert len(normalized["reason"]) <= 220


def test_heuristic_routing_is_disabled_for_detailed_website_spec() -> None:
  prompt = (
    "we have 7 communication channels (call,email,sms, instagram,whatsapp,facebook,webchat)\n"
    "primary color - black\nsecondary color - purple\n"
    "i want to website with backend in python because this website full of Ai based website"
  )
  result = heuristic_routing_result(prompt)
  assert result is None


def test_routing_fallback_after_model_error_uses_salvaged_json() -> None:
  exc = Exception(f"Gemini returned invalid JSON: {MALFORMED_ROUTING_JSON}")
  result = routing_fallback_after_model_error("build ai ccaas website", exc)
  assert result is not None
  assert result["intent"] == "website_generation"


def test_salvage_routing_from_error_extracts_from_exception_text() -> None:
  exc = Exception(f"Gemini returned invalid JSON: {MALFORMED_ROUTING_JSON}")
  salvaged = salvage_routing_from_error(exc)
  assert salvaged is not None
  assert salvaged["intent"] == "website_generation"
