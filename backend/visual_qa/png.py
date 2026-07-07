from __future__ import annotations

import struct
from pathlib import Path


def read_png_dimensions(path: Path) -> tuple[int, int] | None:
  with path.open("rb") as file:
    header = file.read(24)
  if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
    return None
  return struct.unpack(">II", header[16:24])
