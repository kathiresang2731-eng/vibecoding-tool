from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UpdateScope:
  """Normalized update scope from ScopeEngine."""

  update_mode: str
  candidate_files: list[str]
  candidate_new_files: list[str]
  summary: str
  scope_rationale: str
  scoped_update_tasks: list[dict[str, Any]]
  preflight_source: str
  llm_analysis_used: bool
  code_search_match_count: int = 0
  memory_items_loaded: int = 0
  clarification_question: str | None = None
  request_kind: str = "other"
  target_files: list[str] = field(default_factory=list)
  reference_files: list[str] = field(default_factory=list)
  style_reference_snippets: list[dict[str, str]] = field(default_factory=list)
  scope_enrichment_snippets: list[dict[str, str]] = field(default_factory=list)
  enrichment_profile: str = "general_scoped"
  interaction_summary: str = ""
  interaction: dict[str, str] = field(default_factory=dict)
  raw_analysis: dict[str, Any] = field(default_factory=dict)

  def to_update_analysis(self) -> dict[str, Any]:
    payload = dict(self.raw_analysis) if self.raw_analysis else {}
    payload.update(
      {
        "update_mode": self.update_mode,
        "candidate_files": list(self.candidate_files),
        "candidate_new_files": list(self.candidate_new_files),
        "summary": self.summary,
        "scope_rationale": self.scope_rationale,
        "scoped_update_tasks": list(self.scoped_update_tasks),
        "preflight_source": self.preflight_source,
        "request_kind": self.request_kind,
        "target_files": list(self.target_files),
        "reference_files": list(self.reference_files),
        "style_reference_snippets": list(self.style_reference_snippets),
        "scope_enrichment_snippets": list(self.scope_enrichment_snippets),
        "enrichment_profile": self.enrichment_profile,
        "interaction_summary": self.interaction_summary,
        "interaction": dict(self.interaction),
      }
    )
    if self.clarification_question:
      payload["clarification_question"] = self.clarification_question
    return payload

  def to_preflight_payload(self) -> dict[str, Any]:
    return {
      "update_analysis": self.to_update_analysis(),
      "preflight_source": self.preflight_source,
      "code_search_match_count": self.code_search_match_count,
      "memory_items_loaded": self.memory_items_loaded,
      "llm_analysis_used": self.llm_analysis_used,
      "scope_rationale": self.scope_rationale,
      "request_kind": self.request_kind,
      "target_files": list(self.target_files),
      "reference_files": list(self.reference_files),
      "scope_enrichment_snippets": list(self.scope_enrichment_snippets),
      "enrichment_profile": self.enrichment_profile,
      "interaction_summary": self.interaction_summary,
      "interaction": dict(self.interaction),
    }


@dataclass
class CommitResult:
  """Outcome of persisting agent edits."""

  saved_paths: list[str]
  rejected_writes: list[dict[str, Any]]
  persisted: bool
  user_message: str
  preview_status: str = "skipped"
  rejection_reason: str = ""
  rejection_gate: str = ""
