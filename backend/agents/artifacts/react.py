from __future__ import annotations

from .constants import (
  JSX_SYNTAX_RE,
  REACT_NAMED_IMPORT_RE,
  REACT_SOURCE_FILE_EXTENSIONS,
  REACT_VALUE_IMPORT_RE,
)


def normalize_generated_file_code(path: str, code: str) -> str:
  if not path.endswith(REACT_SOURCE_FILE_EXTENSIONS):
    return code
  if not generated_react_file_needs_import(code):
    return code
  if REACT_VALUE_IMPORT_RE.search(code):
    return code

  named_import = REACT_NAMED_IMPORT_RE.search(code)
  if named_import:
    replacement = (
      f"{named_import.group('indent')}import React, "
      f"{named_import.group('names')} from {named_import.group('quote')}react{named_import.group('quote')};"
    )
    return f"{code[:named_import.start()]}{replacement}{code[named_import.end():]}"

  return f'import React from "react";\n{code}'


def generated_react_file_needs_import(code: str) -> bool:
  return "React." in code or bool(JSX_SYNTAX_RE.search(code))
