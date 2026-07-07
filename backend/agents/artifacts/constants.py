from __future__ import annotations

import re


ALLOWED_EXACT_PATHS = {
  "index.html",
  "app.js",
  "index.js",
  "main.js",
  "script.js",
  "main.css",
  "style.css",
  "styles.css",
  "package.json",
  "package-lock.json",
  "requirements.txt",
  "pyproject.toml",
  "poetry.lock",
  "Pipfile",
  "Pipfile.lock",
  "Dockerfile",
  "docker-compose.yml",
  "docker-compose.yaml",
  ".env.example",
  "vite.config.js",
  "vite.config.mjs",
  "vite.config.cjs",
  "vite.config.ts",
  "tailwind.config.js",
  "tailwind.config.mjs",
  "tailwind.config.cjs",
  "tailwind.config.ts",
  "postcss.config.js",
  "postcss.config.mjs",
  "postcss.config.cjs",
  "eslint.config.js",
  "eslint.config.mjs",
  "eslint.config.cjs",
  "tsconfig.json",
  "tsconfig.app.json",
  "tsconfig.node.json",
  "jsconfig.json",
  "components.json",
  "vercel.json",
  "todo.md",
  "README.md",
  "CHANGELOG.md",
  "NOTES.md",
  "WEBSITE.md",
}
ALLOWED_PREFIXES = (
  "src/",
  "public/",
  "docs/",
  "reports/",
  "research/",
  "plans/",
  "notes/",
  "backend/",
  "api/",
  "app/",
  "server/",
  "database/",
  "db/",
  "migrations/",
  "alembic/",
  "scripts/",
  "tests/",
  ".worktual/skills/",
)
ROOT_STANDALONE_CODE_EXTENSIONS = (
  ".c",
  ".cpp",
  ".cs",
  ".go",
  ".java",
  ".kt",
  ".php",
  ".py",
  ".rb",
  ".rs",
  ".sh",
  ".swift",
)
ROOT_DOCUMENT_EXTENSIONS = (
  ".csv",
  ".md",
  ".pdf",
  ".txt",
)
REQUIRED_APP_ENTRY = "src/App.jsx"

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
REACT_SOURCE_FILE_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx")
JSX_SYNTAX_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9:._-]*(?:\s|/?>)|<>|</>")
REACT_VALUE_IMPORT_RE = re.compile(
  r"^\s*import\s+(?:React\b|\*\s+as\s+React\b).*?\s+from\s+['\"]react['\"]\s*;?",
  re.MULTILINE,
)
REACT_NAMED_IMPORT_RE = re.compile(
  r"^(?P<indent>\s*)import\s+(?P<names>\{[^}]+\})\s+from\s+(?P<quote>['\"])react(?P=quote)\s*;?",
  re.MULTILINE | re.DOTALL,
)
