from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import load_dotenv, parse_timeout_seconds
from .errors import OpenAIToolCallingError


@dataclass
class OpenAIResponsesClient:
  api_key: str
  model: str = "gpt-4.1"
  timeout_seconds: int = 120

  @classmethod
  def from_env(cls) -> "OpenAIResponsesClient":
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL") or "gpt-4.1"
    timeout_seconds = parse_timeout_seconds(os.getenv("OPENAI_TIMEOUT_SECONDS"), fallback=120)
    if not api_key or api_key == "your_openai_api_key_here":
      raise OpenAIToolCallingError("Missing OPENAI_API_KEY in .env")
    return cls(api_key=api_key, model=model, timeout_seconds=timeout_seconds)

  def create_response(
    self,
    *,
    input_items: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    previous_response_id: str | None = None,
  ) -> dict[str, Any]:
    payload: dict[str, Any] = {
      "model": self.model,
      "input": input_items,
      "tools": tools,
    }
    if previous_response_id:
      payload["previous_response_id"] = previous_response_id
    return self._post_json("/v1/responses", payload)

  def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
      url=f"https://api.openai.com{path}",
      data=json.dumps(payload).encode("utf-8"),
      headers={
        "Authorization": f"Bearer {self.api_key}",
        "Content-Type": "application/json",
      },
      method="POST",
    )
    try:
      with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
      body = exc.read().decode("utf-8", errors="replace")
      raise OpenAIToolCallingError(f"OpenAI API error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
      if isinstance(exc.reason, (TimeoutError, socket.timeout)):
        raise OpenAIToolCallingError(f"OpenAI request timed out after {self.timeout_seconds}s.") from exc
      raise OpenAIToolCallingError(f"OpenAI network error: {exc.reason}") from exc
    except (TimeoutError, socket.timeout) as exc:
      raise OpenAIToolCallingError(f"OpenAI request timed out after {self.timeout_seconds}s.") from exc
