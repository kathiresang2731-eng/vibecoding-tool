from backend.agents.chat_history import (
  clean_update_prompt,
  enrich_same_topic_referential_prompt,
  enrich_website_modification_prompt,
  has_prior_chat_messages,
  is_referential_followup_prompt,
  merge_update_prompt_with_chat_context,
  model_chat_history_messages_for_prompt,
  prior_rename_target_suggestion,
  prior_rename_target_suggestion_from_memories,
  prompt_already_has_update_continuity,
  recover_update_clarification_prompt,
  should_include_chat_continuity_for_prompt,
  should_include_error_context_for_prompt,
  should_include_session_memory_for_prompt,
)
from backend.api.generation_parts.contextual import append_orchestrator_context


def test_direct_update_keeps_latest_user_prompt_only() -> None:
  merged = merge_update_prompt_with_chat_context(
    "change the website theme to red & black",
    [
      {"role": "user", "content": "Fix testimonialData import error"},
      {"role": "model", "content": "I repaired mockData exports."},
    ],
  )
  assert merged == "change the website theme to red & black"
  assert "testimonialData" not in merged
  assert "Conversation continuity" not in merged


def test_legacy_env_restores_raw_prompt_continuity(monkeypatch) -> None:
  monkeypatch.setenv("ENABLE_LEGACY_UPDATE_CHAT_CONTINUITY", "true")
  merged = merge_update_prompt_with_chat_context(
    "Fix the button alignment",
    [
      {"role": "user", "content": "Add a contact form"},
      {"role": "model", "content": "Updated Contact.jsx with a validated form."},
    ],
  )
  assert "Contact.jsx" in merged
  assert "Conversation continuity" in merged


def test_merge_skips_when_no_prior_messages() -> None:
  prompt = "Add a hero section with a CTA"
  assert merge_update_prompt_with_chat_context(prompt, []) == prompt


def test_merge_skips_when_continuity_already_present() -> None:
  prompt = "Update header\n\nConversation continuity — earlier chat in this session still applies"
  assert merge_update_prompt_with_chat_context(prompt, [{"role": "user", "content": "older"}]) == "Update header"


def test_legacy_merge_skips_when_continuity_already_present(monkeypatch) -> None:
  monkeypatch.setenv("ENABLE_LEGACY_UPDATE_CHAT_CONTINUITY", "true")
  prompt = "Update header\n\nConversation continuity — earlier chat in this session still applies"
  assert merge_update_prompt_with_chat_context(prompt, [{"role": "user", "content": "older"}]) == prompt


def test_enrich_alias_matches_clean_merge() -> None:
  messages = [{"role": "user", "content": "Make the footer sticky"}]
  prompt = "Also add social icons"
  assert enrich_website_modification_prompt(prompt, messages) == merge_update_prompt_with_chat_context(prompt, messages)


def test_relevance_policy_uses_memory_for_followups_not_direct_updates() -> None:
  assert not should_include_chat_continuity_for_prompt("change the website theme to red & black")
  assert not should_include_session_memory_for_prompt("change the website theme to red & black")
  assert should_include_chat_continuity_for_prompt("continue the onboarding update")
  assert should_include_session_memory_for_prompt("continue the onboarding update")
  assert should_include_error_context_for_prompt("try again fix this error")
  assert should_include_chat_continuity_for_prompt("i want more detailed information about him")
  assert should_include_session_memory_for_prompt("give me this detailed as pdf")


def test_referential_followup_detection_catches_pronouns_and_pdf_handoff() -> None:
  assert is_referential_followup_prompt("i want more detailed information about him")
  assert is_referential_followup_prompt("give me this detailed as pdf")
  assert not is_referential_followup_prompt("tell me about apj abdul kalam")


def test_referential_followup_prompt_inherits_same_topic_context() -> None:
  enriched = enrich_same_topic_referential_prompt(
    "give me this detailed as pdf",
    [
      {"role": "user", "content": "i want to know more detailed history of APJ kalam"},
      {"role": "model", "content": "Dr. A.P.J. Abdul Kalam was an Indian aerospace scientist and statesman."},
    ],
  )

  assert "APJ kalam" in enriched
  assert "resolve referential phrases" in enriched
  assert "give me this detailed as pdf" in enriched


def test_batch_update_prompt_stays_latest_user_input_only() -> None:
  prompt = "change the theme to red & black and update the CTA text to Start Now"
  messages = [
    {"role": "user", "content": "Earlier: fix Auth import"},
    {"role": "model", "content": "Assistant completed intent: website_update."},
  ]
  assert enrich_website_modification_prompt(prompt, messages) == prompt
  assert model_chat_history_messages_for_prompt(prompt, messages) == []


def test_model_chat_history_disabled_by_default_and_legacy_restores(monkeypatch) -> None:
  messages = [{"role": "user", "content": "older requirement"}]
  assert model_chat_history_messages_for_prompt("change theme", messages) == []
  monkeypatch.setenv("ENABLE_LEGACY_UPDATE_CHAT_CONTINUITY", "true")
  assert model_chat_history_messages_for_prompt("change theme", messages) == messages


def test_primary_clean_prompt_strips_legacy_continuity_block() -> None:
  prompt = "Update header\n\nConversation continuity — earlier chat in this session still applies\n- older"
  assert clean_update_prompt(prompt) == "Update header"


def test_direct_update_does_not_append_old_error_or_enhancement_context() -> None:
  prompt = append_orchestrator_context(
    "change the website theme to red & black",
    error_context="Uncaught SyntaxError: old testimonialData export failure",
    enhancement_context="Previously add an onboarding button to the dashboard",
  )
  assert prompt == "change the website theme to red & black"
  assert "testimonialData" not in prompt
  assert "onboarding button" not in prompt


def test_vague_retry_can_append_relevant_error_context() -> None:
  prompt = append_orchestrator_context(
    "try again fix this error",
    error_context="Uncaught SyntaxError: testimonialData export failure",
    enhancement_context=None,
  )
  assert "Previous runtime/build error context" in prompt
  assert "testimonialData" in prompt


def test_has_prior_chat_messages() -> None:
  assert not has_prior_chat_messages([])
  assert has_prior_chat_messages([{"role": "user", "content": "hello"}])
  assert prompt_already_has_update_continuity("foo\n\nConversation continuity — earlier")


def test_recover_rename_clarification_reply_into_update_prompt() -> None:
  recovered = recover_update_clarification_prompt(
    "CRM-ai-native",
    [
      {"role": "user", "content": "i want to change the website name"},
      {
        "role": "model",
        "content": "What new name should I use? Please share the exact website, app, or brand name you want applied.",
      },
    ],
  )

  assert recovered == "i want to change the website name to CRM-ai-native"


def test_recover_rename_clarification_reply_normalizes_explicit_name_sentence() -> None:
  recovered = recover_update_clarification_prompt(
    "website name is worktual-ai crm-v1",
    [
      {"role": "user", "content": "i want to change the website name"},
      {
        "role": "model",
        "content": "What new name should I use? Please share the exact website, app, or brand name you want applied.",
      },
    ],
  )

  assert recovered == "i want to change the website name to worktual-ai crm-v1"


def test_recover_rename_clarification_reply_normalizes_redundant_full_request_sentence() -> None:
  recovered = recover_update_clarification_prompt(
    "i want to change the website name to website name is worktual-ai crm-v1",
    [
      {"role": "user", "content": "i want to change the website name"},
      {
        "role": "model",
        "content": "What new name should I use? Please share the exact website, app, or brand name you want applied.",
      },
    ],
  )

  assert recovered == "i want to change the website name to worktual-ai crm-v1"


def test_recover_feature_clarification_reply_into_update_prompt() -> None:
  recovered = recover_update_clarification_prompt(
    "Add WhatsApp integration on the settings page",
    [
      {"role": "user", "content": "please add a new feature in this website"},
      {
        "role": "model",
        "content": "Which feature do you want to add or change? Please mention the target page, module, or workflow and what it should do.",
      },
    ],
  )

  assert recovered.startswith("please add a new feature in this website")
  assert "Requested update details" in recovered
  assert "WhatsApp integration" in recovered


def test_recover_clarification_reply_does_not_override_separate_question() -> None:
  recovered = recover_update_clarification_prompt(
    "what files are there?",
    [
      {"role": "user", "content": "i want to change the website name"},
      {
        "role": "model",
        "content": "What new name should I use? Please share the exact website, app, or brand name you want applied.",
      },
    ],
  )

  assert recovered == "what files are there?"


def test_recover_restart_suggestion_yes_into_update_prompt() -> None:
  recovered = recover_update_clarification_prompt(
    "yes",
    [
      {"role": "user", "content": "i want to change the website name"},
      {
        "role": "model",
        "content": 'Previously you mentioned "worktual-ai crm-v1". Do you want to use that name, or provide a different one?',
      },
    ],
  )

  assert recovered == "change the website name to worktual-ai crm-v1"


def test_recover_restart_suggestion_okay_into_update_prompt() -> None:
  recovered = recover_update_clarification_prompt(
    "okay",
    [
      {"role": "user", "content": "i want to change the website name"},
      {
        "role": "model",
        "content": 'Previously you mentioned "worktual-ai crm-v1". Do you want to use that name, or provide a different one?',
      },
    ],
  )

  assert recovered == "change the website name to worktual-ai crm-v1"


def test_prior_rename_target_suggestion_recovers_previous_name_after_restart() -> None:
  suggestion = prior_rename_target_suggestion(
    "i want to change the website name",
    [
      {"role": "user", "content": "i want to change the website name"},
      {
        "role": "model",
        "content": "What new name should I use? Please share the exact website, app, or brand name you want applied.",
      },
      {"role": "user", "content": "CRM-ai-native"},
    ],
  )

  assert suggestion == "CRM-ai-native"


def test_prior_rename_target_suggestion_ignores_acknowledgement_only_reply() -> None:
  suggestion = prior_rename_target_suggestion(
    "i want to change the website name",
    [
      {"role": "user", "content": "i want to change the website name"},
      {
        "role": "model",
        "content": "What new name should I use? Please share the exact website, app, or brand name you want applied.",
      },
      {"role": "user", "content": "yes update"},
    ],
  )

  assert suggestion == ""


def test_prior_rename_target_suggestion_extracts_name_from_explicit_reply_sentence() -> None:
  suggestion = prior_rename_target_suggestion(
    "i want to change the website name",
    [
      {"role": "user", "content": "i want to change the website name"},
      {
        "role": "model",
        "content": "What new name should I use? Please share the exact website, app, or brand name you want applied.",
      },
      {"role": "user", "content": "website name is worktual-ai crm"},
    ],
  )

  assert suggestion == "worktual-ai crm"


def test_prior_rename_target_suggestion_from_memories_recovers_previous_name_after_restart() -> None:
  suggestion = prior_rename_target_suggestion_from_memories(
    "i want to change the website name",
    [
      {
        "content": (
          "Intent: website_update\n"
          "Outcome: completed\n"
          "User request: worktual-ai-crm\n"
          "Preview: dry_run"
        ),
        "metadata": {
          "intent": "website_update",
          "outcome": "completed",
          "chat_session_id": "session-1",
        },
      },
      {
        "content": (
          "Intent: website_update\n"
          "Outcome: dry_run_planned\n"
          "User request: i want to change my website name\n"
          "Preview: dry_run"
        ),
        "metadata": {
          "intent": "website_update",
          "outcome": "dry_run_planned",
          "chat_session_id": "session-1",
        },
      },
    ],
  )

  assert suggestion == "worktual-ai-crm"


def test_prior_rename_target_suggestion_from_memories_rejects_old_request_sentence_with_typo() -> None:
  suggestion = prior_rename_target_suggestion_from_memories(
    "i want to change the website name",
    [
      {
        "content": (
          "Intent: website_update\n"
          "Outcome: completed\n"
          "User request: i want to chnage the website name\n"
          "Preview: dry_run"
        ),
        "metadata": {
          "intent": "website_update",
          "outcome": "completed",
          "chat_session_id": "session-1",
        },
      },
    ],
  )

  assert suggestion == ""
