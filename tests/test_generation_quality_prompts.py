from backend.agents.streaming.task_planner import (
  auth_onboarding_flow_repair_summary,
  is_auth_onboarding_flow_repair_prompt,
  is_rich_greenfield_website_request,
)


def test_auth_flow_repair_detects_guest_trial_click_issue() -> None:
  prompt = (
    "When a user clicks Guest Trial on the authentication page, the app should bypass signup, "
    "but while click that button there is no action is happening"
  )
  assert is_auth_onboarding_flow_repair_prompt(prompt)


def test_auth_flow_repair_summary_for_guest_trial() -> None:
  summary = auth_onboarding_flow_repair_summary("wire guest trial sandbox button on auth page")
  assert "onClick" in summary
  assert "react-router-dom" in summary


def test_rich_greenfield_detects_enterprise_crm_brief() -> None:
  prompt = (
    "Build a CRM website with enterprise workspace dashboard modules, copilot, analytics, "
    "and authentication onboarding flow"
  )
  assert is_rich_greenfield_website_request(prompt)
