from backend.agents.memory.episode_embeddings import DEFAULT_EMBEDDING_MODEL
from backend.api.constants import SUPPORTED_GENERATION_MODELS


def test_supported_generation_models_use_only_current_flash_and_pro_models():
  assert SUPPORTED_GENERATION_MODELS == {
    "gemini-3.1-pro-preview",
    "gemini-3.5-flash",
  }


def test_episode_embeddings_use_gemini_embedding_2():
  assert DEFAULT_EMBEDDING_MODEL == "gemini-embedding-2"
