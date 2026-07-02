from backend.agents.domain_research import build_domain_research_context, enrich_brief_with_domain_research


def test_domain_research_returns_generic_hint_without_preset_categories() -> None:
  research = build_domain_research_context("Generate the website for e-commerce")

  assert research["status"] == "hint"
  assert research["domain"] == "generic"
  assert "required_sections" not in research
  assert "sample_products" not in research


def test_domain_research_uses_generic_hint_for_no_spec_prompt_even_with_memory() -> None:
  research = build_domain_research_context(
    "I don't have any specific idea so start the generation",
    memories=[{"content": "Prompt: Generate the website for e-commerce"}],
  )

  assert research["status"] == "hint"
  assert research["domain"] == "generic"


def test_domain_research_hint_does_not_inject_static_sections_into_brief() -> None:
  research = build_domain_research_context("Generate the website for e-commerce")
  brief = enrich_brief_with_domain_research(
    "I don't have any specific idea so start the generation",
    {
      "operation": "generate",
      "business_type": "Website",
      "audience": "Target users from the prompt",
      "goal": "I don't have any specific idea so start the generation",
      "style": "Modern, responsive, black/purple Worktual-aligned UI",
      "required_sections": ["Hero", "Features", "Contact"],
      "missing_information": [],
    },
    research,
  )

  assert brief["business_type"] == "Website"
  assert brief["required_sections"] == ["Hero", "Features", "Contact"]
  assert brief["domain_research"]["domain"] == "generic"
  assert brief["domain_research"]["status"] == "hint"


def test_domain_research_applied_llm_plan_can_enrich_brief() -> None:
  research = {
    "status": "applied",
    "source": "gemini_google_search",
    "domain": "custom_store",
    "display_name": "Online store",
    "audience": "Online shoppers",
    "goal": "Drive product discovery and checkout",
    "style": "Clean retail UI with bold CTAs",
    "required_sections": ["Shop", "Cart", "Checkout"],
  }
  brief = enrich_brief_with_domain_research(
    "Build an online store",
    {
      "business_type": "Website",
      "audience": "Target users from the prompt",
      "goal": "Build an online store",
      "style": "Modern, responsive, black/purple Worktual-aligned UI",
      "required_sections": ["Hero", "Features", "Contact"],
    },
    research,
  )

  assert brief["required_sections"] == ["Shop", "Cart", "Checkout"]
  assert brief["audience"] == "Online shoppers"
