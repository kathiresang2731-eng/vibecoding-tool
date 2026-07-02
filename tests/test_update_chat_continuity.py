from backend.agents.chat_history import (
  enrich_website_modification_prompt,
  has_prior_chat_messages,
  merge_update_prompt_with_chat_context,
  prompt_already_has_update_continuity,
)


def test_merge_includes_prior_user_for_any_second_turn() -> None:
  merged = merge_update_prompt_with_chat_context(
    "Change the navbar background to navy blue",
    [
      {"role": "user", "content": "Add a pricing page with three tiers"},
      {"role": "model", "content": "I added src/pages/Pricing.jsx."},
    ],
  )
  assert "navbar background to navy blue" in merged
  assert "pricing page with three tiers" in merged
  assert "Conversation continuity" in merged


def test_merge_includes_assistant_context() -> None:
  merged = merge_update_prompt_with_chat_context(
    "Fix the button alignment",
    [
      {"role": "user", "content": "Add a contact form"},
      {"role": "model", "content": "Updated Contact.jsx with a validated form."},
    ],
  )
  assert "Contact.jsx" in merged


def test_merge_skips_when_no_prior_messages() -> None:
  prompt = "Add a hero section with a CTA"
  assert merge_update_prompt_with_chat_context(prompt, []) == prompt


def test_merge_skips_when_continuity_already_present() -> None:
  prompt = "Update header\n\nConversation continuity — earlier chat in this session still applies"
  assert merge_update_prompt_with_chat_context(prompt, [{"role": "user", "content": "older"}]) == prompt


def test_enrich_alias_matches_merge() -> None:
  messages = [{"role": "user", "content": "Make the footer sticky"}]
  prompt = "Also add social icons"
  assert enrich_website_modification_prompt(prompt, messages) == merge_update_prompt_with_chat_context(prompt, messages)


def test_has_prior_chat_messages() -> None:
  assert not has_prior_chat_messages([])
  assert has_prior_chat_messages([{"role": "user", "content": "hello"}])
  assert prompt_already_has_update_continuity("foo\n\nConversation continuity — earlier")
