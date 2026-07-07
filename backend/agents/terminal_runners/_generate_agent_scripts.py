#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from backend.agents.terminal_runners.catalog import AGENT_SCRIPT_NAMES, list_all_agents

TEMPLATE = '''#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from backend.agents.terminal_runners.executor import main_for_agent

AGENT_NAME = {agent_name!r}
{extra}

if __name__ == "__main__":
  raise SystemExit(main_for_agent(AGENT_NAME, sys.argv[1:]))
'''

EXTRAS: dict[str, str] = {
  "agent_registry_agent": (
    'if "--seed-mode" not in sys.argv:\n'
    '  sys.argv.extend(["--seed-mode", "dynamic_planner"])'
  ),
}


def main() -> None:
  root = Path(__file__).resolve().parent
  for agent in list_all_agents():
    script_name = AGENT_SCRIPT_NAMES.get(agent)
    if not script_name:
      continue
    extra = EXTRAS.get(script_name, "")
    (root / f"{script_name}.py").write_text(TEMPLATE.format(agent_name=agent, extra=extra), encoding="utf-8")
    (root / f"{script_name}.py").chmod(0o755)

  (root / "dynamic_specialists.py").write_text(
    '''#!/usr/bin/env python3
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
''',
    encoding="utf-8",
  )
  (root / "dynamic_specialists.py").chmod(0o755)


if __name__ == "__main__":
  main()
