from __future__ import annotations


SCOPED_UPDATE_RESPONSE_SCHEMA = {
  "type": "OBJECT",
  "properties": {
    "status": {
      "type": "STRING",
      "enum": ["completed", "needs_scope_expansion", "needs_clarification", "blocked"],
    },
    "summary": {"type": "STRING"},
    "edits": {
      "type": "ARRAY",
      "items": {
        "type": "OBJECT",
        "properties": {
          "path": {"type": "STRING"},
          "search_replace": {"type": "STRING"},
          "search_replace_block": {"type": "STRING"},
          "search": {"type": "STRING"},
          "replace": {"type": "STRING"},
          "expected_replacements": {"type": "INTEGER"},
        },
        "required": ["path"],
      },
    },
    "changed_files": {
      "type": "ARRAY",
      "items": {
        "type": "OBJECT",
        "properties": {
          "path": {"type": "STRING"},
          "code": {"type": "STRING"},
        },
        "required": ["path", "code"],
      },
    },
    "requested_files": {
      "type": "ARRAY",
      "items": {"type": "STRING"},
    },
    "clarification_question": {"type": "STRING"},
  },
  "required": [
    "status",
    "summary",
    "edits",
    "changed_files",
    "requested_files",
    "clarification_question",
  ],
}
