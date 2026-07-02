from __future__ import annotations

from .accounts import AccountStoreMixin
from .automated_testing import AutomatedTestingStoreMixin
from .agent_runtime import AgentRuntimeStoreMixin
from .bootstrap import BOOTSTRAP_STATEMENTS
from .chat import ChatHistoryStoreMixin
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
  MemoryStoreMixin,
  MemoryFrameworkStoreMixin,
  VersionEventStoreMixin,
  UsageLimitsStoreMixin,
  AutomatedTestingStoreMixin,
):
  def __init__(self, database_url: str) -> None:
    if not database_url:
      raise StorageError("DATABASE_URL is required.")
    self.database_url = database_url

  def connect(self):
    psycopg = get_psycopg()
    return psycopg.connect(self.database_url, row_factory=get_dict_row(), autocommit=True)

  def bootstrap(self) -> None:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        for statement in BOOTSTRAP_STATEMENTS:
          cursor.execute(statement)
    try:
      from .platform_bootstrap import run_platform_bootstrap_extras
    except ImportError:
      from storage.platform_bootstrap import run_platform_bootstrap_extras
    run_platform_bootstrap_extras(self)
