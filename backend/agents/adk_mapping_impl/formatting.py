from __future__ import annotations

import json

from .mapping import get_adk_mapping


def format_adk_mapping_for_prompt() -> str:
  return json.dumps(get_adk_mapping(), indent=2)
