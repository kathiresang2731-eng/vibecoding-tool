from __future__ import annotations

from backend.agents.terminal_runners.chat import (
  build_brand_rename_proposal,
  is_targeted_brand_rename,
)


def test_brand_rename_proposal_requires_live_source_evidence() -> None:
  scope = {
    "candidate_files": [
      "index.html",
      "src/components/Footer.jsx",
      "src/pages/SidebarJsx.jsx",
    ],
    "candidate_new_files": [],
    "targeted_patch": {
      "kind": "brand_name_update",
      "old_value": "OptimaCRM",
      "new_value": "worktual-ai-crm",
    },
  }
  files = [
    {"path": "index.html", "content": "<title>Generte Crm And</title>"},
    {"path": "src/components/Footer.jsx", "content": "<p>OptimaCRM</p>"},
    {"path": "src/pages/SidebarJsx.jsx", "content": "const title = 'Horizon Suite'"},
  ]

  assert is_targeted_brand_rename(scope)
  proposal = build_brand_rename_proposal(scope=scope, project_files=files)

  assert [item["path"] for item in proposal["files"]] == [
    "index.html",
    "src/components/Footer.jsx",
  ]
