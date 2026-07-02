from __future__ import annotations

import importlib

from .errors import StorageError


def get_psycopg():
  try:
    return importlib.import_module("psycopg")
  except ModuleNotFoundError as exc:
    raise StorageError("psycopg is not installed. Install backend dependencies from requirements.txt.") from exc


def get_dict_row():
  return importlib.import_module("psycopg.rows").dict_row
