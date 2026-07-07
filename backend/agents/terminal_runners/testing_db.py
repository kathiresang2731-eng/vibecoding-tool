from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from backend.storage import PostgresStore, UserContext
from backend.storage.drivers import get_psycopg


TESTING_DATABASE_NAME = "vibe_builder_testing"
TERMINAL_USER_ID = "terminal-testing-user"
TERMINAL_PROJECT_ID = "terminal-testing-project"


@dataclass
class TerminalDatabaseContext:
  store: PostgresStore
  user: UserContext
  project_id: str
  chat_session_id: str
  database_name: str = TESTING_DATABASE_NAME


def database_url_for_name(database_url: str, database_name: str) -> str:
  parsed = urlsplit(database_url)
  return urlunsplit(
    (
      parsed.scheme,
      parsed.netloc,
      f"/{database_name}",
      parsed.query,
      parsed.fragment,
    )
  )


def ensure_testing_database(base_database_url: str) -> str:
  psycopg = get_psycopg()
  admin_url = database_url_for_name(base_database_url, "postgres")
  with psycopg.connect(admin_url, autocommit=True) as conn:
    with conn.cursor() as cursor:
      cursor.execute(
        "select 1 from pg_database where datname = %s",
        (TESTING_DATABASE_NAME,),
      )
      if cursor.fetchone() is None:
        identifier = psycopg.sql.Identifier(TESTING_DATABASE_NAME)
        cursor.execute(psycopg.sql.SQL("create database {}").format(identifier))
  return database_url_for_name(base_database_url, TESTING_DATABASE_NAME)


def initialize_terminal_database(
  base_database_url: str,
  *,
  project_name: str,
  local_path: str | None,
) -> TerminalDatabaseContext:
  testing_url = ensure_testing_database(base_database_url)
  store = PostgresStore(testing_url)
  store.bootstrap()
  user = UserContext(
    id=TERMINAL_USER_ID,
    email="terminal-testing@worktual.local",
    role="owner",
    display_name="Terminal Testing",
  )
  with store.connect() as conn:
    with conn.cursor() as cursor:
      cursor.execute(
        """
        insert into users (id, email, role, display_name, is_active)
        values (%s, %s, %s, %s, true)
        on conflict (id) do update set
          email = excluded.email,
          role = excluded.role,
          display_name = excluded.display_name,
          is_active = true
        """,
        (user.id, user.email, user.role, user.display_name),
      )
      cursor.execute(
        """
        insert into projects (id, owner_user_id, name, description, local_path)
        values (%s, %s, %s, %s, %s)
        on conflict (id) do update set
          name = excluded.name,
          local_path = excluded.local_path,
          updated_at = now()
        """,
        (
          TERMINAL_PROJECT_ID,
          user.id,
          project_name or "Terminal dry-run project",
          "Isolated backend orchestration testing project.",
          local_path,
        ),
      )
  session = store.ensure_active_chat_session(TERMINAL_PROJECT_ID, user)
  return TerminalDatabaseContext(
    store=store,
    user=user,
    project_id=TERMINAL_PROJECT_ID,
    chat_session_id=str(session["id"]),
  )
