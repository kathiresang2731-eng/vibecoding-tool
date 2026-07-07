from __future__ import annotations


def line_count(content: str) -> int:
  if not content:
    return 0
  return len(content.splitlines())


def line_range_for_index(content: str, index: int, *, length: int = 0) -> tuple[int, int]:
  if index < 0:
    return 0, 0
  prefix = content[:index]
  start_line = prefix.count("\n") + 1
  if length <= 0:
    return start_line, start_line
  end_index = index + length
  end_line = content[:end_index].count("\n") + 1
  return start_line, max(start_line, end_line)


def line_range_for_substring(content: str, substring: str) -> tuple[int, int]:
  if not substring:
    return 0, 0
  index = content.find(substring)
  if index < 0:
    return 0, 0
  return line_range_for_index(content, index, length=len(substring))


def line_delta_for_replace(old_string: str, new_string: str) -> tuple[int, int]:
  old_lines = old_string.count("\n") + (1 if old_string else 0)
  new_lines = new_string.count("\n") + (1 if new_string else 0)
  removed = max(0, old_lines)
  added = max(0, new_lines)
  return added, removed


def read_range_for_content(content: str, *, truncated: bool = False, visible_content: str | None = None) -> tuple[int, int]:
  if not content:
    return 1, 1
  total_lines = line_count(content)
  if truncated and visible_content is not None:
    visible_lines = line_count(visible_content)
    return 1, max(1, visible_lines)
  return 1, max(1, total_lines)


def tool_location_detail(
  *,
  path: str,
  action: str,
  start_line: int | None = None,
  end_line: int | None = None,
  added: int | None = None,
  removed: int | None = None,
  pattern: str | None = None,
  **extra: object,
) -> dict[str, object]:
  detail: dict[str, object] = {"path": path, "action": action, **extra}
  if start_line:
    detail["start_line"] = start_line
  if end_line:
    detail["end_line"] = end_line
  if added is not None:
    detail["added"] = added
  if removed is not None:
    detail["removed"] = removed
  if pattern:
    detail["pattern"] = pattern
  return detail
