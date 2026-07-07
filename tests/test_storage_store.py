from __future__ import annotations

import pytest

from backend.storage import PostgresStore, StorageError


def test_postgres_store_connect_wraps_driver_error_and_redacts_database_url(monkeypatch) -> None:
  database_url = "postgresql://vectone:secret-password@localhost:5432/vibe_builder"

  class FakePsycopg:
    def connect(self, url, **kwargs):
      _ = kwargs
      raise RuntimeError(f"could not connect using {url}")

  monkeypatch.setattr("backend.storage.store.get_psycopg", lambda: FakePsycopg())
  monkeypatch.setattr("backend.storage.store.get_dict_row", lambda: object())

  with pytest.raises(StorageError) as exc:
    PostgresStore(database_url).connect()

  message = str(exc.value)
  assert "Database connection failed" in message
  assert "[DATABASE_URL redacted]" in message
  assert "secret-password" not in message


def test_postgres_store_bootstrap_wraps_bootstrap_errors(monkeypatch) -> None:
  class FakeCursor:
    def __enter__(self):
      return self

    def __exit__(self, *_args):
      return False

    def execute(self, _statement):
      raise RuntimeError("bootstrap sql failed")

  class FakeConnection:
    def __enter__(self):
      return self

    def __exit__(self, *_args):
      return False

    def cursor(self):
      return FakeCursor()

  store = PostgresStore("postgresql://vectone:secret-password@localhost:5432/vibe_builder")
  monkeypatch.setattr(store, "connect", lambda: FakeConnection())

  with pytest.raises(StorageError) as exc:
    store.bootstrap()

  message = str(exc.value)
  assert "Database bootstrap failed" in message
  assert "bootstrap sql failed" in message
  assert "secret-password" not in message
