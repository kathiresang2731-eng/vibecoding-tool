from __future__ import annotations

import os


def parse_timeout_seconds(value: str | None, *, fallback: int) -> int:
  if not value:
    return fallback
  try:
    timeout_seconds = int(value)
  except ValueError:
    return fallback
  return max(10, timeout_seconds)


def load_dotenv(path: str = ".env") -> None:
  if not os.path.exists(path):
    return

  with open(path, "r", encoding="utf-8") as env_file:
    for raw_line in env_file:
      line = raw_line.strip()
      if not line or line.startswith("#") or "=" not in line:
        continue
      key, value = line.split("=", 1)
      os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
