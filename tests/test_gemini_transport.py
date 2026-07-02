import socket
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from backend.agents.gemini_client.errors import GeminiClientError
from backend.agents.gemini_client.transport import (
  is_transient_network_error,
  network_retry_attempts,
  post_generate_content,
)


def test_is_transient_network_error_detects_dns_failure():
  assert is_transient_network_error(socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution"))
  assert is_transient_network_error(OSError("Temporary failure in name resolution"))


def test_post_generate_content_retries_transient_network_error(monkeypatch):
  monkeypatch.setenv("GEMINI_NETWORK_RETRY_ATTEMPTS", "3")
  attempts = {"count": 0}

  def fake_urlopen(request, timeout):
    attempts["count"] += 1
    if attempts["count"] < 3:
      raise urllib.error.URLError(socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution"))
    response = MagicMock()
    response.read.return_value = b'{"candidates":[{"content":{"parts":[{"text":"{}"}]}}]}'
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response

  with patch("backend.agents.gemini_client.transport.urllib.request.urlopen", side_effect=fake_urlopen):
    with patch("backend.agents.gemini_client.transport.time.sleep"):
      payload = post_generate_content(
        {"contents": []},
        api_key="test-key",
        model="gemini-3.5-flash",
        timeout_seconds=30,
      )

  assert payload["candidates"]
  assert attempts["count"] == 3


def test_post_generate_content_raises_after_retry_budget(monkeypatch):
  monkeypatch.setenv("GEMINI_NETWORK_RETRY_ATTEMPTS", "2")

  def fake_urlopen(request, timeout):
    raise urllib.error.URLError(socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution"))

  with patch("backend.agents.gemini_client.transport.urllib.request.urlopen", side_effect=fake_urlopen):
    with patch("backend.agents.gemini_client.transport.time.sleep"):
      with pytest.raises(GeminiClientError, match="Gemini network error"):
        post_generate_content(
          {"contents": []},
          api_key="test-key",
          model="gemini-3.5-flash",
          timeout_seconds=30,
        )


def test_network_retry_attempts_is_bounded(monkeypatch):
  monkeypatch.setenv("GEMINI_NETWORK_RETRY_ATTEMPTS", "99")
  assert network_retry_attempts() == 5
