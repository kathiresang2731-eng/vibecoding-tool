from __future__ import annotations

from typing import Any


TODO_PATH = "todo.md"
WEBSITE_DESCRIPTION_PATH = "WEBSITE.md"


def _paths(task: dict[str, Any]) -> list[str]:
  return [str(path) for path in (task.get("paths") or []) if str(path or "").strip()]


def build_todo_markdown(
  *,
  prompt: str,
  work_plan: dict[str, Any],
  completed: bool = False,
  validation: dict[str, Any] | None = None,
  preview_status: str = "",
) -> str:
  mark = "x" if completed else " "
  lines = [
    "# Website Generation Plan",
    "",
    "## User requirement",
    "",
    str(prompt or "").strip()[:4_000] or "Generate a website.",
    "",
    "## Execution",
    "",
    f"- [{mark}] Detect intent and select website generation",
    f"- [{mark}] Create the project tree and shared route/export contract",
    f"- [{mark}] Run exactly three coding workers concurrently",
    f"- [{mark}] Merge worker output into the selected project workspace",
    f"- [{mark}] Run the production build in the backend terminal",
    f"- [{mark}] Test planned pages in the generated preview",
    f"- [{mark}] Perform at most one repair-and-retest iteration",
    f"- [{mark}] Publish the preview and final website description",
    "",
    "## Worker ownership",
    "",
  ]
  for task in work_plan.get("tasks") or []:
    if not isinstance(task, dict):
      continue
    lines.append(f"### {task.get('id')}")
    lines.extend(f"- `{path}`" for path in _paths(task))
    lines.append("")
  if validation:
    lines.extend(
      [
        "## Final verification",
        "",
        f"- Deliverable complete: `{bool(validation.get('complete'))}`",
        f"- Page count: `{validation.get('page_count', 0)}`",
        f"- Preview status: `{preview_status or 'not available'}`",
      ]
    )
    issues = [str(issue) for issue in (validation.get("issues") or []) if str(issue)]
    if issues:
      lines.append(f"- Remaining issues: `{', '.join(issues)}`")
  return "\n".join(lines).strip() + "\n"


def build_website_description_markdown(
  *,
  prompt: str,
  work_plan: dict[str, Any],
  validation: dict[str, Any],
  runtime: dict[str, Any],
) -> str:
  route_contract = work_plan.get("route_contract") or []
  final_output = runtime.get("final_output") if isinstance(runtime.get("final_output"), dict) else {}
  preview_url = str(final_output.get("preview_url") or "")
  lines = [
    "# Generated Website",
    "",
    "## Brief",
    "",
    str(prompt or "").strip()[:4_000] or "Generated website.",
    "",
    "## Architecture",
    "",
    "- React + Vite application",
    "- Thin `src/App.jsx` routing shell",
    "- Pages and shared components split by responsibility",
    "- Build and browser QA executed by the backend",
    "- Generation outcome persisted to episodic project memory",
    "",
    "## Routes and pages",
    "",
  ]
  for route in route_contract:
    if not isinstance(route, dict):
      continue
    lines.append(
      f"- `{route.get('route')}` → `{route.get('file_path')}` "
      f"(`{route.get('component')}`)"
    )
  lines.extend(
    [
      "",
      "## Verification",
      "",
      f"- Deliverable: `{'complete' if validation.get('complete') else 'incomplete'}`",
      f"- Preview: `{final_output.get('preview_status') or 'not available'}`",
      f"- Preview URL: `{preview_url or 'not available'}`",
      f"- Browser QA: `{final_output.get('visual_qa_status') or 'not available'}`",
      f"- Repair iterations: `{runtime.get('repair_iterations', 0)}`",
      "",
      "See `todo.md` for the executed generation plan and worker ownership.",
    ]
  )
  return "\n".join(lines).strip() + "\n"


def initial_plan_files(*, prompt: str, work_plan: dict[str, Any]) -> list[dict[str, str]]:
  return [
    {
      "path": TODO_PATH,
      "content": build_todo_markdown(prompt=prompt, work_plan=work_plan),
    }
  ]


def completed_plan_files(
  *,
  prompt: str,
  work_plan: dict[str, Any],
  validation: dict[str, Any],
  runtime: dict[str, Any],
) -> list[dict[str, str]]:
  final_output = runtime.get("final_output") if isinstance(runtime.get("final_output"), dict) else {}
  preview_status = str(final_output.get("preview_status") or "")
  return [
    {
      "path": TODO_PATH,
      "content": build_todo_markdown(
        prompt=prompt,
        work_plan=work_plan,
        completed=bool(validation.get("complete")) and preview_status == "ready",
        validation=validation,
        preview_status=preview_status,
      ),
    },
    {
      "path": WEBSITE_DESCRIPTION_PATH,
      "content": build_website_description_markdown(
        prompt=prompt,
        work_plan=work_plan,
        validation=validation,
        runtime=runtime,
      ),
    },
  ]
