"""Semantic code index for memory-driven update scoping."""

from .incremental import maybe_reindex_after_persist, reindex_project_paths
from .retriever import retrieve_code_context

__all__ = ["maybe_reindex_after_persist", "reindex_project_paths", "retrieve_code_context"]
