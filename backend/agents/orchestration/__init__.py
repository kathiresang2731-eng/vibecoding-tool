from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from .runner import WorktualGenerationOrchestrator
  from .state import GenerationPipelineState

__all__ = [
  "GenerationPipelineState",
  "WorktualGenerationOrchestrator",
]


def __getattr__(name: str) -> object:
  if name == "WorktualGenerationOrchestrator":
    from .runner import WorktualGenerationOrchestrator

    return WorktualGenerationOrchestrator
  if name == "GenerationPipelineState":
    from .state import GenerationPipelineState

    return GenerationPipelineState
  raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
