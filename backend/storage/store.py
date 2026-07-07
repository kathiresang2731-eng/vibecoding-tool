from __future__ import annotations

from .accounts import AccountStoreMixin
from .automated_testing import AutomatedTestingStoreMixin
from .agent_runtime import AgentRuntimeStoreMixin
from .bootstrap import BOOTSTRAP_STATEMENTS
from .chat import ChatHistoryStoreMixin
from .chat_topics import ChatTopicStoreMixin
from .consistency_jobs import ConsistencyJobStoreMixin
from .drivers import get_dict_row, get_psycopg
from .errors import StorageError
from .memory import MemoryStoreMixin
from .memory_framework import MemoryFrameworkStoreMixin
from .projects import ProjectFileStoreMixin
from .usage_limits import UsageLimitsStoreMixin
from .versions_events import VersionEventStoreMixin


class PostgresStore(
  AccountStoreMixin,
  ProjectFileStoreMixin,
  AgentRuntimeStoreMixin,
  ChatHistoryStoreMixin,
  ChatTopicStoreMixin,
  MemoryStoreMixin,
  MemoryFrameworkStoreMixin,
  ConsistencyJobStoreMixin,
  VersionEventStoreMixin,
  UsageLimitsStoreMixin,
  AutomatedTestingStoreMixin,
):
  def __init__(self, database_url: str) -> None:
    if not database_url:
      raise StorageError("DATABASE_URL is required.")
    self.database_url = database_url

  def _safe_storage_error(self, prefix: str, exc: Exception) -> StorageError:
    detail = str(exc).strip() or exc.__class__.__name__
    if self.database_url and self.database_url in detail:
      detail = detail.replace(self.database_url, "[DATABASE_URL redacted]")
    return StorageError(f"{prefix}: {detail}")

  def connect(self):
    try:
      psycopg = get_psycopg()
      return psycopg.connect(self.database_url, row_factory=get_dict_row(), autocommit=True)
    except StorageError:
      raise
    except Exception as exc:
      raise self._safe_storage_error("Database connection failed", exc) from exc

  def bootstrap(self) -> None:
    try:
      with self.connect() as conn:
        with conn.cursor() as cursor:
          for statement in BOOTSTRAP_STATEMENTS:
            cursor.execute(statement)
    except StorageError:
      raise
    except Exception as exc:
      raise self._safe_storage_error("Database bootstrap failed", exc) from exc
    try:
      from .platform_bootstrap import run_platform_bootstrap_extras
    except ImportError:
      from storage.platform_bootstrap import run_platform_bootstrap_extras
    try:
      run_platform_bootstrap_extras(self)
    except StorageError:
      raise
    except Exception as exc:
      raise self._safe_storage_error("Database platform bootstrap failed", exc) from exc
