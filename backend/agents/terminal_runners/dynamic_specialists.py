#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from backend.agents.terminal_runners.executor import main_for_agent

if __name__ == "__main__":
  if "--seed-mode" not in sys.argv:
    sys.argv.extend(["--seed-mode", "dynamic_specialists"])
  if "--action" not in sys.argv:
    sys.argv.extend(["--action", "RUN_DYNAMIC_SPECIALISTS"])
  raise SystemExit(main_for_agent("Agent Registry Agent", sys.argv[1:]))
