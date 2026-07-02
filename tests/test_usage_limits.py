from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.storage.usage_limits import UsageLimitsStoreMixin, _normalize_usage_row, _safe_float, serialize_usage_summary


def test_normalize_usage_row_resets_daily_counter_on_new_day():
  previous_week = datetime.now(timezone.utc) - timedelta(days=8)
  row = {
    "daily_token_limit": 1000,
    "weekly_token_limit": 5000,
    "monthly_token_limit": 10000,
    "daily_tokens_used": 900,
    "weekly_tokens_used": 900,
    "monthly_tokens_used": 900,
    "daily_period_start": previous_week,
    "weekly_period_start": previous_week,
    "monthly_period_start": previous_week,
  }
  normalized = _normalize_usage_row(row)
  assert normalized["daily_tokens_used"] == 0
  assert normalized["weekly_tokens_used"] == 0


def test_serialize_usage_summary_treats_token_limits_as_diagnostics_only():
  summary = serialize_usage_summary(
    user_id="user-1",
    role="owner",
    is_active=True,
    usage_row={
      "daily_token_limit": 1000,
      "weekly_token_limit": 5000,
      "monthly_token_limit": 10000,
      "daily_tokens_used": 1000,
      "weekly_tokens_used": 1000,
      "monthly_tokens_used": 1000,
    },
  )
  assert summary["blocked_reason"] == ""
  assert summary["token_diagnostics_only"] is True
  assert summary["daily"]["remaining"] == 0


def test_admin_usage_is_unlimited():
  summary = serialize_usage_summary(
    user_id="admin-1",
    role="admin",
    is_active=True,
    usage_row=None,
  )
  assert summary["unlimited"] is True
  assert summary["blocked_reason"] == ""


def test_extend_user_usage_limits_adds_to_caps():
  from backend.storage.usage_limits import _normalize_usage_row

  row = {
    "daily_token_limit": 100000,
    "weekly_token_limit": 500000,
    "monthly_token_limit": 1000000,
    "daily_tokens_used": 90000,
    "weekly_tokens_used": 90000,
    "monthly_tokens_used": 90000,
  }
  normalized = _normalize_usage_row(row)
  extended_daily = int(normalized["daily_token_limit"]) + 50000
  assert extended_daily == 150000


def test_bootstrap_creates_redacted_token_usage_events_table():
  from backend.storage.bootstrap import BOOTSTRAP_STATEMENTS

  ddl = "\n".join(BOOTSTRAP_STATEMENTS)
  table_ddl = ddl.split("create table if not exists user_token_usage_events", 1)[1].split("create index", 1)[0]
  assert "input_tokens integer not null default 0" in table_ddl
  assert "output_tokens integer not null default 0" in table_ddl
  assert "cached_input_tokens integer not null default 0" in table_ddl
  assert "estimated_cost_usd numeric(12,6) not null default 0" in table_ddl
  assert "estimated_credits numeric(12,4) not null default 0" in table_ddl
  assert "execution_stage text not null default ''" in table_ddl
  assert "model_role text not null default ''" in table_ddl
  assert "call_label text not null default ''" in table_ddl
  assert "prompt text" not in table_ddl.lower()


def test_bootstrap_creates_credit_account_and_reservation_tables():
  from backend.storage.bootstrap import BOOTSTRAP_STATEMENTS

  ddl = "\n".join(BOOTSTRAP_STATEMENTS)
  assert "create table if not exists user_ai_credit_accounts" in ddl
  assert "included_monthly_credits numeric(12,4) not null default 1000" in ddl
  assert "alter table user_ai_credit_accounts alter column included_monthly_credits set default 1000" in ddl
  assert "overage_enabled boolean not null default false" in ddl
  assert "create table if not exists ai_credit_reservations" in ddl
  assert "estimated_credits numeric(12,4) not null default 0" in ddl
  assert "actual_credits numeric(12,4) not null default 0" in ddl
  assert "idx_ai_credit_reservations_user_created" in ddl


def test_safe_float_preserves_pricing_values():
  assert _safe_float("0.123456") == 0.123456
  assert _safe_float(4) == 4.0
  assert _safe_float(None) is None


def test_credit_account_serialization_uses_stored_credit_cap():
  account = UsageLimitsStoreMixin()._serialize_ai_credit_account(
    {
      "included_monthly_credits": 2000,
      "used_credits": 0,
      "reserved_credits": 0,
      "overage_enabled": False,
      "overage_usd_cap": 0,
      "pricing_version": "",
    },
    actual_used_credits=875.25,
  )
  assert account["included_monthly_credits"] == 2000.0
  assert account["credit_usd_value"] == 0.01
  assert account["used_usd"] == 8.7525
  assert account["remaining_included_credits"] == 1124.75
  assert account["limit_reached"] is False


def test_credit_account_serialization_uses_admin_configured_cap():
  account = UsageLimitsStoreMixin()._serialize_ai_credit_account(
    {
      "included_monthly_credits": 1500,
      "used_credits": 0,
      "reserved_credits": 0,
      "overage_enabled": False,
      "overage_usd_cap": 0,
      "pricing_version": "",
    },
    actual_used_credits=1250,
  )

  assert account["included_monthly_credits"] == 1500.0
  assert account["remaining_included_credits"] == 250.0
  assert account["limit_reached"] is False


def test_credit_limit_blocks_generation_before_token_limit():
  class Store(UsageLimitsStoreMixin):
    def get_user_ai_credit_account(self, user_id):
      return {"limit_reached": True, "blocked_reason": "You have completed your user limit."}

  allowed, reason = Store().user_usage_allows_generation("user-1", role="owner", is_active=True)

  assert allowed is False
  assert reason == "You have completed your user limit."
