from __future__ import annotations

import re
from typing import Any

from ...update_analysis import scoped_list_items_from_prompt, sanitize_pascal_component_name
from ...values import object_value, string_list, text_or_default

def deterministic_feature_items_for_task(task: dict[str, Any], update_analysis: dict[str, Any]) -> list[str]:
  feature_plan = object_value(update_analysis.get("feature_plan"))
  items = string_list(feature_plan.get("items"), [])
  if not items:
    items = scoped_list_items_from_prompt(text_or_default(task.get("prompt"), ""))
  if not items:
    items = scoped_list_items_from_prompt(text_or_default(update_analysis.get("summary"), ""))
  cleaned: list[str] = []
  seen: set[str] = set()
  for item in items:
    label = re.sub(r"\s+", " ", item.replace("\u2019", "'")).strip(" .;:-")
    if not label:
      continue
    key = label.lower()
    if key in seen:
      continue
    seen.add(key)
    cleaned.append(label[:80])
    if len(cleaned) >= 12:
      break
  return cleaned


def component_name_from_path(path: str) -> str:
  basename = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
  return sanitize_pascal_component_name(basename)


def deterministic_feature_component_code(
  *,
  component_name: str,
  items: list[str],
  feature_plan: dict[str, Any],
) -> str:
  title = text_or_default(feature_plan.get("name"), component_name)
  interaction = text_or_default(feature_plan.get("interaction"), "")
  tab_entries = ",\n".join(
    (
      "  { "
      f"id: \"{js_string_literal(slug_for_component_item(label))}\", "
      f"label: \"{js_string_literal(label)}\", "
      f"description: \"{js_string_literal(component_item_description(label))}\" "
      "}"
    )
    for label in items
  )
  subtitle = (
    js_string_literal(interaction)
    if interaction
    else "Review the selected record across the requested sections."
  )
  return (
    "import React, { useMemo, useState } from \"react\";\n\n"
    f"const detailTabs = [\n{tab_entries}\n];\n\n"
    f"export default function {component_name}({{ contact = {{}} }}) {{\n"
    "  const [activeTab, setActiveTab] = useState(detailTabs[0]?.id || \"\");\n"
    "  const activeDetail = useMemo(\n"
    "    () => detailTabs.find((item) => item.id === activeTab) || detailTabs[0],\n"
    "    [activeTab]\n"
    "  );\n\n"
    "  return (\n"
    "    <section className=\"contact-detail-page\">\n"
    "      <header className=\"contact-detail-header\">\n"
    f"        <p className=\"contact-detail-eyebrow\">{js_string_literal(title)}</p>\n"
    "        <h2>{contact.name || contact.company || \"Selected contact\"}</h2>\n"
    f"        <p>{subtitle}</p>\n"
    "      </header>\n"
    "      <nav className=\"contact-detail-tabs\" aria-label=\"Contact detail sections\">\n"
    "        {detailTabs.map((tab) => (\n"
    "          <button\n"
    "            key={tab.id}\n"
    "            type=\"button\"\n"
    "            className={tab.id === activeTab ? \"active\" : \"\"}\n"
    "            onClick={() => setActiveTab(tab.id)}\n"
    "          >\n"
    "            {tab.label}\n"
    "          </button>\n"
    "        ))}\n"
    "      </nav>\n"
    "      <article className=\"contact-detail-card\">\n"
    "        <h3>{activeDetail?.label}</h3>\n"
    "        <p>{activeDetail?.description}</p>\n"
    "      </article>\n"
    "    </section>\n"
    "  );\n"
    "}\n"
  )


def slug_for_component_item(value: str) -> str:
  slugged = re.sub(r"[^a-z0-9]+", "-", value.lower().replace("\u2019", "'")).strip("-")
  return slugged or "section"


def component_item_description(value: str) -> str:
  label = value.strip()
  return f"Review {label} details for the selected record."


def js_string_literal(value: str) -> str:
  return (
    str(value)
    .replace("\\", "\\\\")
    .replace("\"", "\\\"")
    .replace("\r", " ")
    .replace("\n", " ")
  )
