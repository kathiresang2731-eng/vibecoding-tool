from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path
from typing import TextIO

from loguru import logger


class TeeStream:
  def __init__(self, console: TextIO, *, level: str) -> None:
    self.console = console
    self.level = level
    self._buffer = ""

  def write(self, value: str) -> int:
    self.console.write(value)
    self.console.flush()
    self._buffer += value
    while "\n" in self._buffer:
      line, self._buffer = self._buffer.split("\n", 1)
      if line.strip():
        logger.opt(depth=1).log(self.level, line)
    return len(value)

  def flush(self) -> None:
    self.console.flush()
    if self._buffer.strip():
      logger.opt(depth=1).log(self.level, self._buffer)
      self._buffer = ""

  def discard_buffer(self) -> None:
    self._buffer = ""

  def isatty(self) -> bool:
    return bool(getattr(self.console, "isatty", lambda: False)())

  def fileno(self) -> int:
    return self.console.fileno()


def configure_terminal_logging() -> Path:
  root = Path(os.getenv("WORKTUAL_TERMINAL_LOG_DIR") or "logs").expanduser()
  root.mkdir(parents=True, exist_ok=True)
  log_path = root / f"teminal_testinh_{date.today().isoformat()}.log"

  logger.remove()
  logger.add(
    log_path,
    level="DEBUG",
    format="{message}",
    encoding="utf-8",
    enqueue=False,
    backtrace=False,
    diagnose=False,
  )
  if not isinstance(sys.stdout, TeeStream):
    sys.stdout = TeeStream(sys.stdout, level="INFO")
  if not isinstance(sys.stderr, TeeStream):
    sys.stderr = TeeStream(sys.stderr, level="ERROR")

  return log_path


def log_user_input(user_input: str) -> None:
  if isinstance(sys.stdout, TeeStream):
    sys.stdout.discard_buffer()
  logger.bind(event="user_input").info(f"You> {user_input}")
