from .engine import apply_patches_to_files, apply_unified_patch
from .diff_builder import build_unified_patches_from_file_changes
from .errors import PatchEngineError

__all__ = [
  "PatchEngineError",
  "apply_patches_to_files",
  "apply_unified_patch",
  "build_unified_patches_from_file_changes",
]
