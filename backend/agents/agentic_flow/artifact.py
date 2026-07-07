from __future__ import annotations

from typing import Any

from .memory import generation_memory_content
from .steps import agent_step
from .values import list_value, text_value


def build_artifact_steps(
  *,
  intent: str,
  routing_result: dict[str, Any],
  generated_website: dict[str, Any],
  proactive: dict[str, Any],
  start_index: int,
) -> list[dict[str, Any]]:
  is_update = intent == "website_update"
  is_simple_code = intent == "simple_code"
  sections = list_value(generated_website.get("sections"))
  files = list_value(generated_website.get("files"))
  if is_simple_code:
    return [
      agent_step(
        index=start_index,
        agent="Simple Code Writer Agent",
        action="generate_simple_code_file",
        input_payload={"routing_result": routing_result},
        output_payload={
          "file_count": len(files),
          "paths": [file_item.get("path") for file_item in files if isinstance(file_item, dict)],
        },
        tool_calls=["generate_simple_code_file"],
      ),
      agent_step(
        index=start_index + 1,
        agent="Validation Agent",
        action="validate_standalone_code_artifact",
        input_payload={"file_count": len(files)},
        output_payload={
          "status": "valid",
          "self_checks": list_value(proactive.get("self_checks")),
        },
        tool_calls=["VALIDATE_STANDALONE_CODE_ARTIFACT"],
      ),
      agent_step(
        index=start_index + 2,
        agent="Commit Agent",
        action="write_standalone_code_file",
        input_payload={"file_count": len(files)},
        output_payload={
          "status": "commit_requested",
          "tool": "WRITE_PROJECT_FILES",
        },
        tool_calls=["WRITE_PROJECT_FILES"],
      ),
      agent_step(
        index=start_index + 3,
        agent="Memory Agent",
        action="persist_project_memory",
        input_payload={"title": generated_website.get("title")},
        output_payload={
          "memory_kind": "simple_code_summary",
          "content": generation_memory_content(generated_website, files),
        },
        tool_calls=["PERSIST_PROJECT_MEMORY"],
      ),
    ]
  return [
    agent_step(
      index=start_index,
      agent="Simple Code Writer Agent" if is_simple_code else "Prompt Analyst Agent",
      action="extract_code_request" if is_simple_code else "extract_update_brief" if is_update else "extract_website_brief",
      input_payload={"routing_result": routing_result},
      output_payload={
        "title": generated_website.get("title"),
        "headline": generated_website.get("headline"),
        "subheadline": generated_website.get("subheadline"),
        "section_count": len(sections),
      },
    ),
    agent_step(
      index=start_index + 1,
      agent="Simple Code Writer Agent" if is_simple_code else "Planner Agent",
      action="plan_standalone_code_file" if is_simple_code else "plan_sections_and_conversion_path",
      input_payload={"title": generated_website.get("title"), "sections": sections},
      output_payload={
        "section_order": [
          text_value(section.get("name"), f"Section {index}")
          for index, section in enumerate(sections, start=1)
          if isinstance(section, dict)
        ],
        "primary_cta": generated_website.get("primary_cta"),
        "secondary_cta": generated_website.get("secondary_cta"),
      },
    ),
    agent_step(
      index=start_index + 2,
      agent="Simple Code Writer Agent" if is_simple_code else "UX Review Agent",
      action="review_code_request_fit" if is_simple_code else "review_ux_plan",
      input_payload={"title": generated_website.get("title"), "sections": sections},
      output_payload={
        "status": "reviewed",
        "recommendations": ["Keep primary workflows clear and responsive."],
      },
    ),
    agent_step(
      index=start_index + 3,
      agent="Validation Agent" if is_simple_code else "Accessibility Agent",
      action="review_code_artifact_contract" if is_simple_code else "review_accessibility_plan",
      input_payload={"title": generated_website.get("title"), "sections": sections},
      output_payload={
        "status": "reviewed",
        "recommendations": ["Maintain contrast, semantic sections, and mobile text fit."],
      },
    ),
    agent_step(
      index=start_index + 4,
      agent="Simple Code Writer Agent" if is_simple_code else "Code Agent",
      action="generate_simple_code_file" if is_simple_code else "generate_update_artifact" if is_update else "generate_project_artifact",
      input_payload={"section_count": len(sections)},
      output_payload={
        "file_count": len(files),
        "paths": [file_item.get("path") for file_item in files if isinstance(file_item, dict)],
      },
    ),
    agent_step(
      index=start_index + 5,
      agent="Validation Agent",
      action="validate_generated_artifact_contract",
      input_payload={"file_count": len(files), "section_count": len(sections)},
      output_payload={
        "status": "valid",
        "required_entry": "src/App.jsx",
        "self_checks": list_value(proactive.get("self_checks")),
      },
      tool_calls=["VALIDATE_PROJECT_ARTIFACT"],
    ),
    agent_step(
      index=start_index + 6,
      agent="Preview Agent",
      action="build_preview_candidate",
      input_payload={"file_count": len(files)},
      output_payload={
        "status": "preview_build_requested",
        "tool": "BUILD_STAGED_PROJECT_PREVIEW",
      },
      tool_calls=["BUILD_STAGED_PROJECT_PREVIEW"],
    ),
    agent_step(
      index=start_index + 7,
      agent="Visual QA Agent",
      action="run_preview_visual_qa",
      input_payload={"file_count": len(files)},
      output_payload={
        "status": "preview_integrity_qa_requested",
        "tool": "RUN_PREVIEW_VISUAL_QA",
        "browser_rendered": False,
      },
      tool_calls=["RUN_PREVIEW_VISUAL_QA"],
    ),
    agent_step(
      index=start_index + 8,
      agent="Code Agent",
      action="write_project_files",
      input_payload={"file_count": len(files)},
      output_payload={
        "status": "commit_requested_after_preview_qa",
        "tool": "WRITE_PROJECT_FILES",
      },
      tool_calls=["WRITE_PROJECT_FILES"],
    ),
    agent_step(
      index=start_index + 9,
      agent="Memory Agent",
      action="persist_project_memory",
      input_payload={"title": generated_website.get("title")},
      output_payload={
        "memory_kind": "generation_summary",
        "content": generation_memory_content(generated_website, files),
      },
      tool_calls=["PERSIST_PROJECT_MEMORY"],
    ),
  ]
