from __future__ import annotations

from typing import Any, Callable

from ..gemini_client import GeminiClientError
from ..providers import LLMProvider
from ..schema import ResponseContractError
from .service import generate_website


def generate_website_or_error(
  user_prompt: str,
  *,
  provider: LLMProvider | None = None,
  gemini_client: Any | None = None,
  control_provider: LLMProvider | None = None,
  artifact_provider: LLMProvider | None = None,
  progress_callback: Callable[[dict[str, Any]], None] | None = None,
  project_id: str | None = None,
  tool_context: Any | None = None,
  user: Any | None = None,
  allow_legacy_fallback: bool = False,
) -> tuple[int, dict[str, Any]]:
  try:
    return 200, generate_website(
      user_prompt,
      provider=provider,
      gemini_client=gemini_client,
      control_provider=control_provider,
      artifact_provider=artifact_provider,
      progress_callback=progress_callback,
      project_id=project_id,
      tool_context=tool_context,
      user=user,
      allow_legacy_fallback=allow_legacy_fallback,
    )
  except ResponseContractError as exc:
    return 502, {"error": str(exc)}
  except GeminiClientError as exc:
    return 502, {"error": str(exc)}
  except ValueError as exc:
    return 400, {"error": str(exc)}
  except Exception as exc:
    return 500, {"error": f"Unexpected generation error: {exc}"}
