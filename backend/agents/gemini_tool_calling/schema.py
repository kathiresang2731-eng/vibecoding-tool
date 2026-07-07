from __future__ import annotations

from typing import Any

from .values import string_value


def openai_tools_to_gemini_function_declarations(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
  declarations: list[dict[str, Any]] = []
  for tool in tools:
    declaration = openai_tool_to_gemini_function_declaration(tool)
    if declaration:
      declarations.append(declaration)
  return declarations


def openai_tool_to_gemini_function_declaration(tool: dict[str, Any]) -> dict[str, Any] | None:
  if not isinstance(tool, dict):
    return None
  source = tool.get("function") if isinstance(tool.get("function"), dict) else tool
  name = string_value(source.get("name"))
  if not name:
    return None
  declaration = {
    "name": name,
    "description": string_value(source.get("description")) or f"Execute backend tool {name}.",
    "parameters": sanitize_gemini_schema(source.get("parameters") or {"type": "object", "properties": {}}),
  }
  return declaration


def sanitize_gemini_schema(schema: Any) -> dict[str, Any]:
  if not isinstance(schema, dict):
    return {"type": "object", "properties": {}}

  allowed_keys = {"type", "description", "properties", "items", "required", "enum", "nullable"}
  cleaned: dict[str, Any] = {}
  for key, value in schema.items():
    if key not in allowed_keys:
      continue
    if key == "type":
      cleaned[key] = normalize_schema_type(value)
    elif key == "properties" and isinstance(value, dict):
      cleaned[key] = {
        str(prop_name): sanitize_gemini_schema(prop_schema)
        for prop_name, prop_schema in value.items()
        if isinstance(prop_schema, dict)
      }
    elif key == "items":
      cleaned[key] = sanitize_gemini_schema(value)
    elif key == "required" and isinstance(value, list):
      property_names = set(cleaned.get("properties", {}).keys())
      cleaned[key] = [str(item) for item in value if not property_names or str(item) in property_names]
    elif key == "enum" and isinstance(value, list):
      cleaned[key] = [item for item in value if isinstance(item, (str, int, float, bool))]
    elif key == "description" and isinstance(value, str):
      cleaned[key] = value
    elif key == "nullable" and isinstance(value, bool):
      cleaned[key] = value

  if "type" not in cleaned:
    cleaned["type"] = "object" if "properties" in cleaned else "string"
  if cleaned["type"] == "object" and "properties" not in cleaned:
    cleaned["properties"] = {}
  return cleaned


def normalize_schema_type(value: Any) -> str:
  if isinstance(value, list):
    non_null = [item for item in value if item != "null"]
    return normalize_schema_type(non_null[0]) if non_null else "string"
  if not isinstance(value, str):
    return "string"
  normalized = value.strip().lower()
  aliases = {
    "str": "string",
    "int": "integer",
    "number": "number",
    "float": "number",
    "bool": "boolean",
    "dict": "object",
    "list": "array",
  }
  return aliases.get(normalized, normalized or "string")
