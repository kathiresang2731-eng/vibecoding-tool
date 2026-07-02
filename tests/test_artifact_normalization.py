import pytest

from backend.agents.orchestration.artifact_response import normalize_simple_code_artifact
from backend.agents.schema import ResponseContractError
from backend.llm.artifacts import normalize_generated_file_code, validate_project_artifact


def test_jsx_without_react_import_gets_default_import():
  code = "export default function App() { return <main />; }"

  normalized = normalize_generated_file_code("src/App.jsx", code)

  assert normalized.startswith('import React from "react";\n')
  assert code in normalized


def test_named_react_import_becomes_default_plus_named_import():
  code = 'import { useState } from "react";\nexport default function App() { return <main />; }'

  normalized = normalize_generated_file_code("src/App.jsx", code)

  assert normalized.startswith('import React, { useState } from "react";')
  assert normalized.count('from "react"') == 1


def test_js_file_using_react_api_gets_default_import():
  code = 'export const Card = () => React.createElement("article", null, "Fresh produce");'

  normalized = normalize_generated_file_code("src/Card.js", code)

  assert normalized.startswith('import React from "react";\n')
  assert code in normalized


def test_ts_file_using_react_api_gets_default_import():
  code = 'export const Card = () => React.createElement("article", null, "Fresh produce");'

  normalized = normalize_generated_file_code("src/Card.ts", code)

  assert normalized.startswith('import React from "react";\n')
  assert code in normalized


def test_tsx_without_react_import_gets_default_import():
  code = "export default function App() { return <main />; }"

  normalized = normalize_generated_file_code("src/App.tsx", code)

  assert normalized.startswith('import React from "react";\n')
  assert code in normalized


def test_existing_react_default_import_is_unchanged():
  code = 'import React from "react";\nexport default function App() { return <main />; }'

  normalized = normalize_generated_file_code("src/App.jsx", code)

  assert normalized == code


def test_non_react_file_is_unchanged():
  code = "body { margin: 0; }"

  normalized = normalize_generated_file_code("src/index.css", code)

  assert normalized == code


def test_validate_project_artifact_normalizes_generated_jsx_files():
  artifact = {
    "title": "Farm",
    "headline": "Fresh produce",
    "subheadline": "A farm website.",
    "primary_cta": "Shop",
    "secondary_cta": "Visit",
    "preview_html": "",
    "theme": {
      "colors": {
        "primary": "#000000",
        "secondary": "#7c3aed",
        "accent": "#111827",
        "background": "#ffffff",
        "text": "#111827",
      }
    },
    "sections": [{"name": "Hero", "purpose": "Intro", "content": "Hero copy"}],
    "files": [
      {
        "path": "src/App.jsx",
        "purpose": "App",
        "code": "export default function App() { return <main />; }",
      }
    ],
  }

  normalized = validate_project_artifact(artifact)

  assert normalized["files"][0]["code"].startswith('import React from "react";')


def test_validate_project_artifact_allows_static_website_root_files_without_react_entry():
  artifact = {
    "title": "Static",
    "headline": "Simple site",
    "subheadline": "A plain HTML, CSS, and JS website.",
    "primary_cta": "Open",
    "secondary_cta": "Learn",
    "preview_html": "",
    "theme": {
      "colors": {
        "primary": "#000000",
        "secondary": "#7c3aed",
        "accent": "#111827",
        "background": "#ffffff",
        "text": "#111827",
      }
    },
    "sections": [{"name": "Hero", "purpose": "Intro", "content": "Hero copy"}],
    "files": [
      {"path": "index.html", "purpose": "Entry", "code": '<link rel="stylesheet" href="./style.css"><script src="./script.js"></script>'},
      {"path": "style.css", "purpose": "Styles", "code": "body { margin: 0; }"},
      {"path": "script.js", "purpose": "Behavior", "code": "console.log('static site');"},
    ],
  }

  normalized = validate_project_artifact(artifact)

  assert [file_item["path"] for file_item in normalized["files"]] == ["index.html", "style.css", "script.js"]


def test_validate_project_artifact_allows_root_standalone_code_file():
  artifact = {
    "title": "Standalone Python Code",
    "headline": "Reverse number",
    "subheadline": "A plain Python script.",
    "primary_cta": "Open code",
    "secondary_cta": "Run code",
    "preview_html": "",
    "theme": {
      "colors": {
        "primary": "#000000",
        "secondary": "#7c3aed",
        "accent": "#111827",
        "background": "#ffffff",
        "text": "#111827",
      }
    },
    "sections": [{"name": "Generated File", "purpose": "Code", "content": "reverse_number.py"}],
    "files": [
      {
        "path": "reverse_number.py",
        "purpose": "Standalone Python program.",
        "code": "print(str(input()).strip()[::-1])",
      }
    ],
  }

  normalized = validate_project_artifact(artifact)

  assert normalized["files"][0]["path"] == "reverse_number.py"


def test_simple_code_artifact_rejects_website_scaffold_files():
  response = {
    "generated_website": {
      "title": "Standalone Code",
      "headline": "Standalone Code",
      "subheadline": "Generated code.",
      "primary_cta": "Open code",
      "secondary_cta": "Run code",
      "preview_html": "",
      "theme": {
        "colors": {
          "primary": "#000000",
          "secondary": "#7c3aed",
          "accent": "#111827",
          "background": "#ffffff",
          "text": "#111827",
        }
      },
      "sections": [{"name": "Generated File", "purpose": "Code", "content": "index.html"}],
      "files": [
        {"path": "index.html", "purpose": "Web scaffold", "code": "<div id='root'></div>"},
        {"path": "package.json", "purpose": "Dependencies", "code": '{"dependencies":{"vite":"latest"}}'},
      ],
    }
  }

  with pytest.raises(ResponseContractError, match="standalone code files"):
    normalize_simple_code_artifact(response)
