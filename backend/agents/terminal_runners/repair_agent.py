#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from backend.agents.terminal_runners.executor import main_for_agent

AGENT_NAME = 'Repair Agent'


if __name__ == "__main__":
  raise SystemExit(main_for_agent(AGENT_NAME, sys.argv[1:]))
