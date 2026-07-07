MAX_LOCAL_FILE_BYTES = 512 * 1024
REQUIRED_PROJECT_ROOT_FILES = {"index.html", "package.json"}
REQUIRED_PROJECT_SOURCE_PREFIX = "src/"

IGNORED_FILE_NAMES = {
  ".DS_Store",
  ".env",
  ".env.development",
  ".env.local",
  ".env.production",
  "Thumbs.db",
}

BINARY_PUBLIC_ASSET_EXTENSIONS = {
  ".avif",
  ".gif",
  ".ico",
  ".jpeg",
  ".jpg",
  ".otf",
  ".pdf",
  ".png",
  ".ttf",
  ".webp",
  ".woff",
  ".woff2",
}

IGNORED_DIRECTORIES = {
  ".git",
  ".runtime",
  ".worktual-staging",
  ".venv",
  "__pycache__",
  "dist",
  "node_modules",
}

ALLOWED_DOT_DIRECTORIES = {
  ".worktual",
  ".cursor",
  ".agents",
}
