from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from typing import Any

from .errors import GeminiClientError
try:
  from ...runtime_control import raise_if_runtime_cancelled
except ImportError:
  from runtime_control import raise_if_runtime_cancelled
try:
  from ...audit_logging import log_query_event
except ImportError:
  try:
    from audit_logging import log_query_event
  except ImportError:
    log_query_event = None


def post_generate_content(
  payload: dict[str, Any],
  *,
  api_key: str,
  model: str,
  timeout_seconds: int,
) -> dict[str, Any]:
  url = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{model}:generateContent?key={api_key}"
  )
  request = urllib.request.Request(
    url=url,
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
  )

  attempts = network_retry_attempts()
  last_error: Exception | None = None
  for attempt in range(1, attempts + 1):
    raise_if_runtime_cancelled()
    try:
      with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        result = json.loads(response.read().decode("utf-8"))
        raise_if_runtime_cancelled()
        return result
    except urllib.error.HTTPError as exc:
      body = exc.read().decode("utf-8", errors="replace")
      last_error = exc
      if attempt < attempts and is_retryable_http_status(exc.code):
        delay = retry_delay_seconds(exc.headers, attempt)
        log_retry_event(
          model=model,
          attempt=attempt,
          max_attempts=attempts,
          reason=f"http_{exc.code}",
          delay_seconds=delay,
        )
        cancellation_aware_sleep(delay)
        continue
      raise GeminiClientError(f"Gemini API error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
      if isinstance(exc.reason, (TimeoutError, socket.timeout)):
        last_error = exc
        if attempt < attempts:
          delay = network_retry_backoff_seconds(attempt)
          log_retry_event(
            model=model,
            attempt=attempt,
            max_attempts=attempts,
            reason="url_timeout",
            delay_seconds=delay,
          )
          cancellation_aware_sleep(delay)
          continue
        raise GeminiClientError(timeout_message(timeout_seconds)) from exc
      last_error = exc
      if attempt < attempts and is_transient_network_error(exc.reason):
        delay = network_retry_backoff_seconds(attempt)
        log_retry_event(
          model=model,
          attempt=attempt,
          max_attempts=attempts,
          reason=exc.reason.__class__.__name__ if exc.reason is not None else "network_error",
          delay_seconds=delay,
        )
        cancellation_aware_sleep(delay)
        continue
      raise GeminiClientError(f"Gemini network error: {exc.reason}") from exc
    except (TimeoutError, socket.timeout) as exc:
      last_error = exc
      if attempt < attempts:
        delay = network_retry_backoff_seconds(attempt)
        log_retry_event(
          model=model,
          attempt=attempt,
          max_attempts=attempts,
          reason="socket_timeout",
          delay_seconds=delay,
        )
        cancellation_aware_sleep(delay)
        continue
      raise GeminiClientError(timeout_message(timeout_seconds)) from exc

  if last_error is not None:
    raise GeminiClientError(f"Gemini network error: {last_error}") from last_error
  raise GeminiClientError("Gemini network error: request failed without a response.")


def network_retry_attempts() -> int:
  raw = os.getenv("GEMINI_NETWORK_RETRY_ATTEMPTS", "3").strip()
  try:
    value = int(raw)
  except ValueError:
    value = 3
  return max(1, min(value, 5))


def network_retry_backoff_seconds(attempt: int) -> float:
  return min(8.0, 0.75 * (2 ** max(0, attempt - 1)))


def is_retryable_http_status(status_code: int) -> bool:
  return int(status_code) in {408, 429, 500, 502, 503, 504}


def retry_delay_seconds(headers: Any, attempt: int) -> float:
  retry_after = headers.get("Retry-After") if headers is not None and hasattr(headers, "get") else None
  try:
    if retry_after not in (None, ""):
      return max(0.0, min(float(retry_after), 8.0))
  except (TypeError, ValueError):
    pass
  return network_retry_backoff_seconds(attempt)


def cancellation_aware_sleep(seconds: float) -> None:
  deadline = time.monotonic() + max(0.0, seconds)
  while True:
    raise_if_runtime_cancelled()
    remaining = deadline - time.monotonic()
    if remaining <= 0:
      return
    time.sleep(min(remaining, 0.1))


def log_retry_event(
  *,
  model: str,
  attempt: int,
  max_attempts: int,
  reason: str,
  delay_seconds: float,
) -> None:
  if log_query_event is None:
    return
  log_query_event(
    "model.call.retry",
    status="running",
    payload={
      "attempt": attempt,
      "next_attempt": attempt + 1,
      "max_attempts": max_attempts,
      "reason": reason,
      "delay_seconds": round(delay_seconds, 3),
    },
    provider="gemini",
    model=model,
  )


def is_transient_network_error(reason: BaseException | None) -> bool:
  if reason is None:
    return False
  if isinstance(reason, (TimeoutError, socket.timeout, ConnectionResetError, ConnectionRefusedError)):
    return True
  if isinstance(reason, OSError):
    transient_errnos = {
      getattr(socket, "EAI_AGAIN", -3),
      getattr(socket, "EAI_NONAME", -2),
      getattr(socket, "ENETUNREACH", 101),
      getattr(socket, "EHOSTUNREACH", 113),
    }
    if reason.errno in transient_errnos:
      return True
  message = str(reason).lower()
  return any(
    marker in message
    for marker in (
      "temporary failure in name resolution",
      "name or service not known",
      "network is unreachable",
      "connection reset by peer",
      "connection refused",
      "temporarily unavailable",
    )
  )


def timeout_message(timeout_seconds: int) -> str:
  return (
    f"Gemini request timed out after {timeout_seconds}s while waiting for model output. "
    "Try a shorter prompt or increase GEMINI_TIMEOUT_SECONDS."
  )
