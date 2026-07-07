from __future__ import annotations

from __future__ import annotations

from .fallbacks import deterministic_routing_result
from .fallbacks import heuristic_routing_result
from .fallbacks import non_website_routing_fallback
from .fallbacks import routing_fallback_after_model_error
from .fallbacks import routing_user_message
from .fallbacks import salvage_routing_from_error
from .markers import looks_like_simple_code_request
from .markers import looks_like_document_artifact_request
from .markers import looks_like_research_or_planning_request
from .markers import looks_like_time_sensitive_research_request
from .markers import looks_like_website_generation_request

__all__ = [
  "routing_user_message",
  "deterministic_routing_result",
  "looks_like_simple_code_request",
  "looks_like_document_artifact_request",
  "looks_like_research_or_planning_request",
  "looks_like_time_sensitive_research_request",
  "looks_like_website_generation_request",
  "heuristic_routing_result",
  "non_website_routing_fallback",
  "salvage_routing_from_error",
  "routing_fallback_after_model_error",
]
