from __future__ import annotations


def build_runtime_thread_id(*, project_id: str, run_id: str) -> str:
  cleaned_project = str(project_id or "").strip()
  cleaned_run = str(run_id or "").strip()
  if not cleaned_project or not cleaned_run:
    raise ValueError("project_id and run_id are required to build a runtime thread_id.")
  return f"{cleaned_project}:{cleaned_run}"


def build_graph_invoke_config(*, project_id: str, run_id: str) -> dict[str, dict[str, str]]:
  thread_id = build_runtime_thread_id(project_id=project_id, run_id=run_id)
  return {"configurable": {"thread_id": thread_id}}


def parse_runtime_thread_id(thread_id: str) -> tuple[str, str]:
  cleaned = str(thread_id or "").strip()
  if ":" not in cleaned:
    raise ValueError("thread_id must use the format project_id:run_id")
  project_id, run_id = cleaned.split(":", 1)
  if not project_id.strip() or not run_id.strip():
    raise ValueError("thread_id must use the format project_id:run_id")
  return project_id.strip(), run_id.strip()
