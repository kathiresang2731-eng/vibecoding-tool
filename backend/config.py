from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
  pass


@dataclass(frozen=True)
class Settings:
  database_url: str
  frontend_origins: list[str]
  dev_user_email: str
  gemini_api_key: str
  gemini_model: str
  app_root: Path
  local_workspace_roots: list[Path]
  openai_api_key: str = ""
  openai_model: str = "gpt-4.1"
  backend_public_base_url: str = "http://127.0.0.1:8787"
  visual_qa_browser_command: str = ""
  screenshot_storage_root: Path = Path(".data/screenshots")
  audit_log_dir: str = "logs"
  audit_log_content_max_chars: int = 1000
  dynamic_agent_timeout_seconds: int = 60
  dynamic_agent_max_tool_calls: int = 6
  dynamic_agent_max_patch_files: int = 6
  dynamic_agent_max_patch_bytes: int = 262144
  dynamic_agent_promotion_min_successes: int = 3
  require_plan_confirmation: bool = True
  jwt_secret: str = ""
  auth_token_ttl_hours: int = 168
  auth_allow_dev_header: bool = False
  auth_allow_signup: bool = False
  default_daily_token_limit: int = 500_000
  default_weekly_token_limit: int = 3_000_000
  default_monthly_token_limit: int = 12_000_000


def load_settings(*, require_database: bool = True, env: dict[str, str] | None = None) -> Settings:
  app_root = Path(__file__).resolve().parents[1]
  if env is None:
    load_env_file(app_root / ".env")
    load_env_file(Path.cwd() / ".env")
  source = env if env is not None else os.environ
  database_url = get_env(source, "DATABASE_URL", "")
  if require_database and not database_url:
    raise ConfigError("DATABASE_URL is required for the local platform backend.")

  return Settings(
    database_url=database_url,
    frontend_origins=parse_csv(source.get("FRONTEND_ORIGINS"))
    or [
      "http://localhost:5173",
      "http://127.0.0.1:5173",
      "http://localhost:5174",
      "http://127.0.0.1:5174",
    ],
    dev_user_email=get_env(source, "DEV_USER_EMAIL", "dev@vibe.local"),
    gemini_api_key=get_env(source, "GEMINI_API_KEY", ""),
    gemini_model=get_env(source, "GEMINI_MODEL", "gemini-3.5-flash"),
    openai_api_key=get_env(source, "OPENAI_API_KEY", ""),
    openai_model=get_env(source, "OPENAI_MODEL", "gpt-4.1"),
    backend_public_base_url=get_env(source, "BACKEND_PUBLIC_BASE_URL", "http://127.0.0.1:8787").rstrip("/"),
    visual_qa_browser_command=get_env(source, "VISUAL_QA_BROWSER_COMMAND", ""),
    screenshot_storage_root=Path(
      get_env(source, "SCREENSHOT_STORAGE_ROOT", str(app_root / ".data" / "screenshots"))
    ).expanduser().resolve(),
    audit_log_dir=get_env(source, "AUDIT_LOG_DIR", "logs"),
    audit_log_content_max_chars=parse_positive_int(source.get("AUDIT_LOG_CONTENT_MAX_CHARS"), fallback=1000),
    dynamic_agent_timeout_seconds=parse_positive_int(source.get("DYNAMIC_AGENT_TIMEOUT_SECONDS"), fallback=60),
    dynamic_agent_max_tool_calls=parse_positive_int(source.get("DYNAMIC_AGENT_MAX_TOOL_CALLS"), fallback=6),
    dynamic_agent_max_patch_files=parse_positive_int(source.get("DYNAMIC_AGENT_MAX_PATCH_FILES"), fallback=6),
    dynamic_agent_max_patch_bytes=parse_positive_int(source.get("DYNAMIC_AGENT_MAX_PATCH_BYTES"), fallback=262144),
    dynamic_agent_promotion_min_successes=parse_positive_int(source.get("DYNAMIC_AGENT_PROMOTION_MIN_SUCCESSES"), fallback=3),
    require_plan_confirmation=parse_bool(source.get("REQUIRE_PLAN_CONFIRMATION"), fallback=True),
    jwt_secret=get_env(source, "JWT_SECRET", "worktual-dev-jwt-secret-change-me"),
    auth_token_ttl_hours=parse_positive_int(source.get("AUTH_TOKEN_TTL_HOURS"), fallback=168),
    auth_allow_dev_header=parse_bool(source.get("AUTH_ALLOW_DEV_HEADER"), fallback=False),
    auth_allow_signup=parse_bool(source.get("AUTH_ALLOW_SIGNUP"), fallback=False),
    default_daily_token_limit=parse_positive_int(source.get("DEFAULT_DAILY_TOKEN_LIMIT"), fallback=500_000),
    default_weekly_token_limit=parse_positive_int(source.get("DEFAULT_WEEKLY_TOKEN_LIMIT"), fallback=3_000_000),
    default_monthly_token_limit=parse_positive_int(source.get("DEFAULT_MONTHLY_TOKEN_LIMIT"), fallback=12_000_000),
    app_root=app_root,
    local_workspace_roots=parse_path_csv(source.get("LOCAL_WORKSPACE_ROOTS"), fallback=app_root / "vibe-sites"),
  )


def get_env(source: dict[str, str], key: str, fallback: str) -> str:
  value = source.get(key)
  if isinstance(value, str) and value.strip():
    return value.strip()
  return fallback


def parse_csv(value: str | None) -> list[str]:
  if not value:
    return []
  return [item.strip() for item in value.split(",") if item.strip()]


def parse_path_csv(value: str | None, *, fallback: Path) -> list[Path]:
  raw_items = parse_csv(value)
  if not raw_items:
    return [fallback.resolve()]
  return [Path(item).expanduser().resolve() for item in raw_items]


def parse_positive_int(value: str | None, *, fallback: int) -> int:
  try:
    parsed = int(str(value or "").strip())
  except ValueError:
    return fallback
  return parsed if parsed > 0 else fallback


def parse_bool(value: str | None, *, fallback: bool) -> bool:
  if value is None:
    return fallback
  normalized = value.strip().lower()
  if normalized in {"1", "true", "yes", "on"}:
    return True
  if normalized in {"0", "false", "no", "off"}:
    return False
  return fallback


def load_env_file(path: str | Path = ".env") -> None:
  env_path = Path(path)
  if not env_path.exists():
    return

  with env_path.open("r", encoding="utf-8") as env_file:
    for raw_line in env_file:
      line = raw_line.strip()
      if not line or line.startswith("#") or "=" not in line:
        continue
      key, value = line.split("=", 1)
      normalized_key = key.strip()
      if os.environ.get(normalized_key, "").strip():
        continue
      os.environ[normalized_key] = value.strip().strip("\"'")
