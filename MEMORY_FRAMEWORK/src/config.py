"""Configuration for the vibe-coding memory testbed."""

MEILISEARCH_URL = "http://127.0.0.1:7700"
MEILISEARCH_KEY = "jayesh"

INDEX_PROFILE = "user_profile"
INDEX_PREFERENCE = "user_preference"
INDEX_EPISODE = "episode"

# Episodic memory scopes
SCOPE_PERSONAL = "personal"  # per user_id — default for retrieval
SCOPE_SHARED = "shared"      # anonymized platform patterns — opt-in retrieval

# When True, episode_retriever also searches shared episodes after personal hits
INCLUDE_SHARED_EPISODES = False

PROCEDURE_FILES = {
    "initial_session": "skills/initial_session.md",
    "add_feature": "skills/add_feature.md",
    "fix_build_error": "skills/fix_build_error.md",
    "scaffold_component": "skills/scaffold_component.md",
}
