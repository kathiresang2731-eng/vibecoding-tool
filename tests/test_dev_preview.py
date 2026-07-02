from __future__ import annotations

from backend.dev_preview import _public_dev_preview_base


def test_public_dev_preview_base_uses_request_host() -> None:
  url = _public_dev_preview_base(
    public_base_url="http://127.0.0.1:8787",
    port=5175,
    request_host="192.168.13.107:5174",
  )
  assert url == "http://192.168.13.107:5175/"


def test_public_dev_preview_base_falls_back_to_public_base_url() -> None:
  url = _public_dev_preview_base(
    public_base_url="http://192.168.13.107:8787",
    port=5188,
    request_host=None,
  )
  assert url == "http://192.168.13.107:5188/"
