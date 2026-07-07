"""Episode text embeddings for Qdrant vector search."""

from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.error
import urllib.request
from typing import Any

from .episodic import tokenize_for_relevance

DEFAULT_EMBEDDING_MODEL = "gemini-embedding-2"
DEFAULT_VECTOR_SIZE = 128


def embedding_model_name() -> str:
  return os.getenv("GEMINI_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL).strip() or DEFAULT_EMBEDDING_MODEL


def embedding_vector_size() -> int:
  raw = os.getenv("EPISODE_VECTOR_SIZE", "").strip()
  if raw:
    try:
      return max(32, min(int(raw), 3072))
    except ValueError:
      pass
  return DEFAULT_VECTOR_SIZE


def build_episode_embedding_text(
  *,
  searchable_summary: str = "",
  intent: str = "",
  outcome: str = "",
  changed_paths: list[str] | None = None,
  prompt: str = "",
) -> str:
  parts = [
    str(searchable_summary or "").strip(),
    f"intent:{intent}".strip() if intent else "",
    f"outcome:{outcome}".strip() if outcome else "",
    f"prompt:{prompt}".strip() if prompt else "",
  ]
  if changed_paths:
    parts.append("paths:" + ", ".join(str(path) for path in changed_paths[:12]))
  return "\n".join(part for part in parts if part).strip()


def _normalize_vector(values: list[float], *, dimensions: int) -> list[float]:
  if len(values) < dimensions:
    values = values + [0.0] * (dimensions - len(values))
  if len(values) > dimensions:
    values = values[:dimensions]
  norm = math.sqrt(sum(value * value for value in values)) or 1.0
  return [value / norm for value in values]


def _local_hash_embedding(text: str, *, dimensions: int | None = None) -> list[float]:
  size = dimensions or embedding_vector_size()
  vector = [0.0] * size
  tokens = tokenize_for_relevance(text)
  if not tokens:
    return vector
  for token in tokens:
    bucket = int.from_bytes(hashlib.sha256(token.encode("utf-8")).digest()[:8], "big") % size
    vector[bucket] += 1.0
  return _normalize_vector(vector, dimensions=size)


def local_embedding_model_name() -> str:
  return f"local-hash-v1:{embedding_vector_size()}"


def embed_local_text(text: str) -> list[float]:
  return _local_hash_embedding(str(text or "").strip(), dimensions=embedding_vector_size())


def embed_episode_text(text: str, *, api_key: str | None = None) -> list[float]:
  cleaned = str(text or "").strip()
  if not cleaned:
    return _local_hash_embedding("", dimensions=embedding_vector_size())

  key = str(api_key or os.getenv("GEMINI_API_KEY") or "").strip()
  if not key or key == "your_gemini_api_key_here":
    return _local_hash_embedding(cleaned, dimensions=embedding_vector_size())

  model = embedding_model_name()
  url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent?key={key}"
  payload = {
    "model": f"models/{model}",
    "content": {"parts": [{"text": cleaned[:8000]}]},
  }
  request = urllib.request.Request(
    url=url,
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
  )
  try:
    with urllib.request.urlopen(request, timeout=30) as response:
      body = json.loads(response.read().decode("utf-8"))
  except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
    return _local_hash_embedding(cleaned, dimensions=embedding_vector_size())

  embedding = body.get("embedding") if isinstance(body, dict) else None
  values = embedding.get("values") if isinstance(embedding, dict) else None
  if not isinstance(values, list) or not values:
    return _local_hash_embedding(cleaned, dimensions=embedding_vector_size())
  parsed = [float(value) for value in values if isinstance(value, (int, float))]
  if not parsed:
    return _local_hash_embedding(cleaned, dimensions=embedding_vector_size())
  return _normalize_vector(parsed, dimensions=len(parsed))
