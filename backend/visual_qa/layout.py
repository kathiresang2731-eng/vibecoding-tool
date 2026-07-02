from __future__ import annotations

from typing import Any


DEFAULT_LAYOUT_VIEWPORTS = [
  {"name": "mobile", "width": 390, "height": 844},
  {"name": "tablet", "width": 768, "height": 1024},
  {"name": "desktop", "width": 1440, "height": 1000},
]


def skipped_layout_viewport_results(reason: str) -> list[dict[str, Any]]:
  return [
    {
      "name": viewport["name"],
      "width": viewport["width"],
      "height": viewport["height"],
      "status": "skipped",
      "reason": reason,
      "issues": [],
    }
    for viewport in DEFAULT_LAYOUT_VIEWPORTS
  ]


def analyze_layout_snapshot(snapshot: dict[str, Any], *, viewport: dict[str, Any]) -> dict[str, Any]:
  width = int(viewport.get("width") or snapshot.get("viewport_width") or 0)
  height = int(viewport.get("height") or snapshot.get("viewport_height") or 0)
  issues: list[dict[str, Any]] = []
  elements = [
    normalize_layout_element(item)
    for item in snapshot.get("elements", [])
    if isinstance(item, dict)
  ]
  elements = [item for item in elements if item["visible"]]

  scroll_width = int(snapshot.get("scroll_width") or width)
  if width and scroll_width > width + 1:
    issues.append(
      {
        "type": "horizontal_overflow",
        "severity": "high",
        "message": f"Document scroll width {scroll_width}px exceeds viewport width {width}px.",
      }
    )

  for element in elements:
    if width and (element["left"] < -1 or element["right"] > width + 1):
      issues.append(layout_issue("offscreen_element", "high", element, "Element extends outside the viewport width."))
    if element["text"] and element["client_width"] and element["scroll_width"] > element["client_width"] + 1:
      issues.append(layout_issue("text_overflow", "high", element, "Text content overflows its container."))
    if element["text"] and element["client_height"] and element["scroll_height"] > element["client_height"] + 1:
      issues.append(layout_issue("clipped_text", "high", element, "Text content is clipped vertically."))
    if is_structural_element(element) and (element["width"] <= 1 or element["height"] <= 1):
      issues.append(layout_issue("zero_size_element", "medium", element, "Structural element has no useful rendered size."))

  for index, first in enumerate(elements):
    if not is_overlap_candidate(first):
      continue
    for second in elements[index + 1 :]:
      if not is_overlap_candidate(second):
        continue
      overlap = intersection_area(first, second)
      if overlap < 64:
        continue
      smaller = max(1.0, min(first["area"], second["area"]))
      if overlap / smaller > 0.9:
        continue
      if overlap / smaller >= 0.25:
        issues.append(
          {
            "type": "overlap",
            "severity": "high",
            "message": "Visible elements overlap significantly.",
            "elements": [element_ref(first), element_ref(second)],
            "overlap_area": round(overlap, 2),
          }
        )

  severity = layout_severity(issues)
  return {
    "name": viewport.get("name") or f"{width}x{height}",
    "width": width,
    "height": height,
    "status": "failed" if severity == "high" else "passed",
    "severity": severity,
    "issues": issues,
  }


def normalize_layout_element(item: dict[str, Any]) -> dict[str, Any]:
  left = float(item.get("left") or item.get("x") or 0)
  top = float(item.get("top") or item.get("y") or 0)
  width = max(0.0, float(item.get("width") or 0))
  height = max(0.0, float(item.get("height") or 0))
  text = str(item.get("text") or "").strip()
  return {
    "selector": str(item.get("selector") or item.get("tag") or "element")[:160],
    "tag": str(item.get("tag") or "").lower(),
    "text": text[:120],
    "left": left,
    "top": top,
    "width": width,
    "height": height,
    "right": left + width,
    "bottom": top + height,
    "area": width * height,
    "visible": bool(item.get("visible", True)),
    "scroll_width": float(item.get("scroll_width") or item.get("scrollWidth") or width),
    "client_width": float(item.get("client_width") or item.get("clientWidth") or width),
    "scroll_height": float(item.get("scroll_height") or item.get("scrollHeight") or height),
    "client_height": float(item.get("client_height") or item.get("clientHeight") or height),
  }


def is_structural_element(element: dict[str, Any]) -> bool:
  tag = element["tag"]
  selector = element["selector"].lower()
  return tag in {"main", "section", "article", "header", "footer", "nav", "button"} or any(
    marker in selector for marker in ("card", "panel", "modal", "drawer", "hero")
  )


def is_overlap_candidate(element: dict[str, Any]) -> bool:
  if element["area"] < 100 or element["width"] < 8 or element["height"] < 8:
    return False
  return element["tag"] in {"button", "a", "input", "section", "article", "header", "nav", "main", "div"} or bool(element["text"])


def intersection_area(first: dict[str, Any], second: dict[str, Any]) -> float:
  width = max(0.0, min(first["right"], second["right"]) - max(first["left"], second["left"]))
  height = max(0.0, min(first["bottom"], second["bottom"]) - max(first["top"], second["top"]))
  return width * height


def layout_issue(kind: str, severity: str, element: dict[str, Any], message: str) -> dict[str, Any]:
  return {
    "type": kind,
    "severity": severity,
    "message": message,
    "element": element_ref(element),
  }


def element_ref(element: dict[str, Any]) -> dict[str, Any]:
  return {
    "selector": element["selector"],
    "tag": element["tag"],
    "text": element["text"],
    "box": {
      "left": round(element["left"], 2),
      "top": round(element["top"], 2),
      "width": round(element["width"], 2),
      "height": round(element["height"], 2),
    },
  }


def layout_severity(issues: list[dict[str, Any]]) -> str:
  if any(issue.get("severity") == "high" for issue in issues):
    return "high"
  if any(issue.get("severity") == "medium" for issue in issues):
    return "medium"
  return "none"
