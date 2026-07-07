from __future__ import annotations

from backend.agents.streaming.line_refs import (
  line_delta_for_replace,
  line_range_for_substring,
  read_range_for_content,
  tool_location_detail,
)


def test_line_range_for_substring() -> None:
  content = "line1\nline2\nline3\n"
  start, end = line_range_for_substring(content, "line2")
  assert start == 2
  assert end == 2


def test_line_range_multiline_match() -> None:
  content = "a\nb\nc\nd\n"
  start, end = line_range_for_substring(content, "b\nc")
  assert start == 2
  assert end == 3


def test_line_delta_for_replace() -> None:
  added, removed = line_delta_for_replace("old\nline", "new\nline\nextra")
  assert added == 3
  assert removed == 2


def test_read_range_truncated() -> None:
  content = "one\ntwo\nthree\nfour\nfive"
  visible = "one\ntwo\nthree"
  start, end = read_range_for_content(content, truncated=True, visible_content=visible)
  assert start == 1
  assert end == 3


def test_tool_location_detail_shape() -> None:
  detail = tool_location_detail(
    path="src/App.jsx",
    action="read",
    start_line=10,
    end_line=42,
    tool="read_file",
  )
  assert detail["path"] == "src/App.jsx"
  assert detail["start_line"] == 10
  assert detail["end_line"] == 42
