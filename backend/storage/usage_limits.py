from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from .errors import StorageError
from .ids import new_id
from .token_pricing import CREDIT_USD_VALUE, DEFAULT_INCLUDED_MONTHLY_CREDITS, PRICING_VERSION, estimate_model_usage_cost


def _utc_now() -> datetime:
  return datetime.now(timezone.utc)


def _period_start(now: datetime, *, unit: str) -> datetime:
  if unit == "day":
    return now.replace(hour=0, minute=0, second=0, microsecond=0)
  if unit == "week":
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start - timedelta(days=start.weekday())
  if unit == "month":
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
  raise ValueError(f"Unsupported period unit: {unit}")


def _safe_int(value: Any) -> int:
  try:
    return max(0, int(value or 0))
  except (TypeError, ValueError):
    return 0


def _safe_float(value: Any) -> float | None:
  if value is None:
    return None
  try:
    if isinstance(value, Decimal):
      return float(value)
    return float(value)
  except (TypeError, ValueError):
    return None


def _period_end_for_month(start: datetime) -> datetime:
  year = start.year + (1 if start.month == 12 else 0)
  month = 1 if start.month == 12 else start.month + 1
  return start.replace(year=year, month=month)


def _normalize_usage_row(row: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
  current = now or _utc_now()
  daily_start = row.get("daily_period_start") or _period_start(current, unit="day")
  weekly_start = row.get("weekly_period_start") or _period_start(current, unit="week")
  monthly_start = row.get("monthly_period_start") or _period_start(current, unit="month")
  daily_used = int(row.get("daily_tokens_used") or 0)
  weekly_used = int(row.get("weekly_tokens_used") or 0)
  monthly_used = int(row.get("monthly_tokens_used") or 0)
  if _period_start(current, unit="day") > daily_start:
    daily_used = 0
    daily_start = _period_start(current, unit="day")
  if _period_start(current, unit="week") > weekly_start:
    weekly_used = 0
    weekly_start = _period_start(current, unit="week")
  if _period_start(current, unit="month") > monthly_start:
    monthly_used = 0
    monthly_start = _period_start(current, unit="month")
  return {
    **row,
    "daily_token_limit": int(row.get("daily_token_limit") or 0),
    "weekly_token_limit": int(row.get("weekly_token_limit") or 0),
    "monthly_token_limit": int(row.get("monthly_token_limit") or 0),
    "daily_tokens_used": daily_used,
    "weekly_tokens_used": weekly_used,
    "monthly_tokens_used": monthly_used,
    "daily_period_start": daily_start,
    "weekly_period_start": weekly_start,
    "monthly_period_start": monthly_start,
  }


def serialize_usage_summary(
  *,
  user_id: str,
  role: str,
  is_active: bool,
  usage_row: dict[str, Any] | None,
) -> dict[str, Any]:
  if role == "admin":
    return {
      "user_id": user_id,
      "role": role,
      "is_active": is_active,
      "unlimited": True,
      "daily": {"limit": None, "used": 0, "remaining": None},
      "weekly": {"limit": None, "used": 0, "remaining": None},
      "monthly": {"limit": None, "used": 0, "remaining": None},
      "blocked_reason": "",
    }
  row = _normalize_usage_row(usage_row or {})
  daily_limit = int(row.get("daily_token_limit") or 0)
  weekly_limit = int(row.get("weekly_token_limit") or 0)
  monthly_limit = int(row.get("monthly_token_limit") or 0)
  daily_used = int(row.get("daily_tokens_used") or 0)
  weekly_used = int(row.get("weekly_tokens_used") or 0)
  monthly_used = int(row.get("monthly_tokens_used") or 0)
  blocked_reason = ""
  if not is_active:
    blocked_reason = "Account is suspended. Contact your administrator."
  return {
    "user_id": user_id,
    "role": role,
    "is_active": is_active,
    "unlimited": False,
    "daily": {
      "limit": daily_limit,
      "used": daily_used,
      "remaining": max(0, daily_limit - daily_used) if daily_limit else None,
    },
    "weekly": {
      "limit": weekly_limit,
      "used": weekly_used,
      "remaining": max(0, weekly_limit - weekly_used) if weekly_limit else None,
    },
    "monthly": {
      "limit": monthly_limit,
      "used": monthly_used,
      "remaining": max(0, monthly_limit - monthly_used) if monthly_limit else None,
    },
    "token_diagnostics_only": True,
    "blocked_reason": blocked_reason,
  }


class UsageLimitsStoreMixin:
  def _serialize_ai_credit_account(
    self,
    row: dict[str, Any] | None,
    *,
    actual_used_credits: float | int | None = None,
  ) -> dict[str, Any]:
    if not row:
      return {
        "included_monthly_credits": DEFAULT_INCLUDED_MONTHLY_CREDITS,
        "credit_usd_value": CREDIT_USD_VALUE,
        "used_credits": 0.0,
        "used_usd": 0.0,
        "reserved_credits": 0.0,
        "remaining_included_credits": DEFAULT_INCLUDED_MONTHLY_CREDITS,
        "overage_enabled": False,
        "overage_usd_cap": 0.0,
        "limit_reached": False,
        "blocked_reason": "",
        "pricing_version": PRICING_VERSION,
        "current_period_start": None,
        "current_period_end": None,
      }
    configured_included = _safe_float(row.get("included_monthly_credits")) or DEFAULT_INCLUDED_MONTHLY_CREDITS
    included = configured_included
    used = _safe_float(actual_used_credits)
    if used is None:
      used = _safe_float(row.get("used_credits")) or 0.0
    reserved = _safe_float(row.get("reserved_credits")) or 0.0
    remaining = max(0.0, included - used - reserved)
    limit_reached = included > 0 and remaining <= 0
    return {
      "included_monthly_credits": included,
      "configured_included_monthly_credits": configured_included,
      "credit_usd_value": CREDIT_USD_VALUE,
      "used_credits": used,
      "used_usd": round(used * CREDIT_USD_VALUE, 6),
      "reserved_credits": reserved,
      "remaining_included_credits": remaining,
      "overage_enabled": bool(row.get("overage_enabled")),
      "overage_usd_cap": _safe_float(row.get("overage_usd_cap")) or 0.0,
      "limit_reached": limit_reached,
      "blocked_reason": "You have completed your user limit." if limit_reached else "",
      "pricing_version": row.get("pricing_version") or PRICING_VERSION,
      "current_period_start": row.get("current_period_start"),
      "current_period_end": row.get("current_period_end"),
    }

  def _serialize_token_usage_event(self, row: dict[str, Any]) -> dict[str, Any]:
    return {
      "id": row.get("id"),
      "user_id": row.get("user_id"),
      "project_id": row.get("project_id"),
      "request_id": row.get("request_id") or "",
      "generation_run_id": row.get("generation_run_id") or "",
      "agent_run_id": row.get("agent_run_id") or "",
      "provider": row.get("provider") or "gemini",
      "model": row.get("model") or "",
      "call": row.get("call_label") or row.get("call") or "",
      "input_tokens": _safe_int(row.get("input_tokens")),
      "output_tokens": _safe_int(row.get("output_tokens")),
      "total_tokens": _safe_int(row.get("total_tokens")),
      "thought_tokens": _safe_int(row.get("thought_tokens")),
      "cached_tokens": _safe_int(row.get("cached_tokens")),
      "cached_input_tokens": _safe_int(row.get("cached_input_tokens")),
      "prompt_chars": _safe_int(row.get("prompt_chars")),
      "output_chars": _safe_int(row.get("output_chars")),
      "estimated_cost_usd": _safe_float(row.get("estimated_cost_usd")) or 0.0,
      "estimated_credits": _safe_float(row.get("estimated_credits")) or 0.0,
      "pricing_version": row.get("pricing_version") or "",
      "route": row.get("route") or "",
      "execution_stage": row.get("execution_stage") or "",
      "model_role": row.get("model_role") or "",
      "thinking_level": row.get("thinking_level") or "",
      "context_chars": _safe_int(row.get("context_chars")),
      "duration_ms": _safe_float(row.get("duration_ms")),
      "created_at": row.get("created_at"),
    }

  def _token_usage_period_totals(self, user_id: str, *, since: datetime) -> dict[str, int]:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select
            coalesce(sum(input_tokens), 0) as input_tokens,
            coalesce(sum(output_tokens), 0) as output_tokens,
            coalesce(sum(total_tokens), 0) as total_tokens,
            coalesce(sum(thought_tokens), 0) as thought_tokens,
            coalesce(sum(cached_tokens), 0) as cached_tokens,
            coalesce(sum(cached_input_tokens), 0) as cached_input_tokens,
            coalesce(sum(estimated_cost_usd), 0) as estimated_cost_usd,
            coalesce(sum(estimated_credits), 0) as estimated_credits,
            count(*) as call_count
          from user_token_usage_events
          where user_id = %s and created_at >= %s
          """,
          (user_id, since),
        )
        row = cursor.fetchone() or {}
    return {
      "input_tokens": _safe_int(row.get("input_tokens")),
      "output_tokens": _safe_int(row.get("output_tokens")),
      "total_tokens": _safe_int(row.get("total_tokens")),
      "thought_tokens": _safe_int(row.get("thought_tokens")),
      "cached_tokens": _safe_int(row.get("cached_tokens")),
      "cached_input_tokens": _safe_int(row.get("cached_input_tokens")),
      "estimated_cost_usd": _safe_float(row.get("estimated_cost_usd")) or 0.0,
      "estimated_credits": _safe_float(row.get("estimated_credits")) or 0.0,
      "call_count": _safe_int(row.get("call_count")),
    }

  def _ai_credits_used_since(self, user_id: str, *, since: datetime) -> float:
    if not user_id:
      return 0.0
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select coalesce(sum(estimated_credits), 0) as used_credits
          from user_token_usage_events
          where user_id = %s and created_at >= %s
          """,
          (user_id, since),
        )
        row = cursor.fetchone() or {}
    return _safe_float(row.get("used_credits")) or 0.0

  def get_user_token_usage_details(
    self,
    user_id: str,
    *,
    recent_request_limit: int = 10,
    recent_call_limit: int = 20,
  ) -> dict[str, Any]:
    request_limit = max(1, min(100, int(recent_request_limit or 10)))
    call_limit = max(1, min(100, int(recent_call_limit or 20)))
    now = _utc_now()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select
            id,
            user_id,
            project_id,
            request_id,
            generation_run_id,
            agent_run_id,
            provider,
            model,
            call_label,
            input_tokens,
            output_tokens,
            total_tokens,
            thought_tokens,
            cached_tokens,
            cached_input_tokens,
            prompt_chars,
            output_chars,
            estimated_cost_usd,
            estimated_credits,
            pricing_version,
            route,
            execution_stage,
            model_role,
            thinking_level,
            context_chars,
            duration_ms,
            created_at
          from user_token_usage_events
          where user_id = %s
          order by created_at desc
          limit %s
          """,
          (user_id, call_limit),
        )
        recent_calls = [self._serialize_token_usage_event(dict(row)) for row in (cursor.fetchall() or [])]
        cursor.execute(
          """
          with scoped as (
            select
              coalesce(nullif(request_id, ''), nullif(generation_run_id, ''), nullif(agent_run_id, ''), id) as request_key,
              *
            from user_token_usage_events
            where user_id = %s
          )
          select
            request_key,
            max(created_at) as created_at,
            max(project_id) as project_id,
            max(generation_run_id) as generation_run_id,
            max(agent_run_id) as agent_run_id,
            count(*) as call_count,
            coalesce(sum(input_tokens), 0) as input_tokens,
            coalesce(sum(output_tokens), 0) as output_tokens,
            coalesce(sum(total_tokens), 0) as total_tokens,
            coalesce(sum(thought_tokens), 0) as thought_tokens,
            coalesce(sum(cached_tokens), 0) as cached_tokens,
            coalesce(sum(cached_input_tokens), 0) as cached_input_tokens,
            coalesce(sum(estimated_cost_usd), 0) as estimated_cost_usd,
            coalesce(sum(estimated_credits), 0) as estimated_credits,
            array_remove(array_agg(distinct nullif(route, '')), null::text) as routes,
            array_remove(array_agg(distinct nullif(execution_stage, '')), null::text) as execution_stages,
            array_remove(array_agg(distinct nullif(model, '')), null::text) as models
          from scoped
          group by request_key
          order by max(created_at) desc
          limit %s
          """,
          (user_id, request_limit),
        )
        recent_requests = []
        for row in cursor.fetchall() or []:
          payload = dict(row)
          recent_requests.append(
            {
              "request_id": payload.get("request_key") or "",
              "project_id": payload.get("project_id") or "",
              "generation_run_id": payload.get("generation_run_id") or "",
              "agent_run_id": payload.get("agent_run_id") or "",
              "created_at": payload.get("created_at"),
              "call_count": _safe_int(payload.get("call_count")),
              "input_tokens": _safe_int(payload.get("input_tokens")),
              "output_tokens": _safe_int(payload.get("output_tokens")),
              "total_tokens": _safe_int(payload.get("total_tokens")),
              "thought_tokens": _safe_int(payload.get("thought_tokens")),
              "cached_tokens": _safe_int(payload.get("cached_tokens")),
              "cached_input_tokens": _safe_int(payload.get("cached_input_tokens")),
              "estimated_cost_usd": _safe_float(payload.get("estimated_cost_usd")) or 0.0,
              "estimated_credits": _safe_float(payload.get("estimated_credits")) or 0.0,
              "routes": [str(item) for item in (payload.get("routes") or []) if str(item or "").strip()],
              "execution_stages": [
                str(item) for item in (payload.get("execution_stages") or []) if str(item or "").strip()
              ],
              "models": [str(item) for item in (payload.get("models") or []) if str(item or "").strip()],
            }
          )
    return {
      "daily": self._token_usage_period_totals(user_id, since=_period_start(now, unit="day")),
      "weekly": self._token_usage_period_totals(user_id, since=_period_start(now, unit="week")),
      "monthly": self._token_usage_period_totals(user_id, since=_period_start(now, unit="month")),
      "credit_account": self.get_user_ai_credit_account(user_id),
      "recent_requests": recent_requests,
      "recent_model_calls": recent_calls,
    }

  def ensure_user_ai_credit_account(
    self,
    user_id: str,
    *,
    included_monthly_credits: float | int = DEFAULT_INCLUDED_MONTHLY_CREDITS,
  ) -> dict[str, Any] | None:
    if not user_id:
      return None
    now = _utc_now()
    period_start = _period_start(now, unit="month")
    period_end = _period_end_for_month(period_start)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into user_ai_credit_accounts (
            user_id,
            included_monthly_credits,
            pricing_version,
            current_period_start,
            current_period_end,
            updated_at
          )
          values (%s, %s, %s, %s, %s, %s)
          on conflict (user_id) do nothing
          """,
          (
            user_id,
            _safe_float(included_monthly_credits) or DEFAULT_INCLUDED_MONTHLY_CREDITS,
            PRICING_VERSION,
            period_start,
            period_end,
            now,
          ),
        )
        cursor.execute("select * from user_ai_credit_accounts where user_id = %s", (user_id,))
        row = cursor.fetchone()
    return self._serialize_ai_credit_account(dict(row)) if row else None

  def get_user_ai_credit_account(self, user_id: str) -> dict[str, Any]:
    if not user_id:
      return self._serialize_ai_credit_account(None)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute("select * from user_ai_credit_accounts where user_id = %s", (user_id,))
        row = cursor.fetchone()
    if not row:
      created = self.ensure_user_ai_credit_account(user_id)
      return created or self._serialize_ai_credit_account(None)
    account = dict(row)
    now = _utc_now()
    period_end = account.get("current_period_end")
    if isinstance(period_end, datetime) and period_end <= now:
      period_start = _period_start(now, unit="month")
      new_period_end = _period_end_for_month(period_start)
      with self.connect() as conn:
        with conn.cursor() as cursor:
          cursor.execute(
            """
            update user_ai_credit_accounts
            set
              used_credits = 0,
              reserved_credits = 0,
              current_period_start = %s,
              current_period_end = %s,
              pricing_version = %s,
              updated_at = %s
            where user_id = %s
            returning *
            """,
            (period_start, new_period_end, PRICING_VERSION, now, user_id),
          )
          refreshed = cursor.fetchone()
      if refreshed:
        account = dict(refreshed)
    period_start = account.get("current_period_start")
    if not isinstance(period_start, datetime):
      period_start = _period_start(now, unit="month")
    actual_used = self._ai_credits_used_since(user_id, since=period_start)
    return self._serialize_ai_credit_account(account, actual_used_credits=actual_used)

  def update_user_ai_credit_account(
    self,
    user_id: str,
    *,
    included_monthly_credits: float | int | None = None,
    reset_usage: bool = False,
  ) -> dict[str, Any]:
    if not user_id:
      return self._serialize_ai_credit_account(None)
    self.ensure_user_ai_credit_account(user_id)
    now = _utc_now()
    current = self.get_user_ai_credit_account(user_id)
    included = _safe_float(included_monthly_credits)
    if included is None:
      included = _safe_float(current.get("included_monthly_credits")) or DEFAULT_INCLUDED_MONTHLY_CREDITS
    included = max(0.0, included)
    period_start = _period_start(now, unit="month")
    period_end = _period_end_for_month(period_start)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        if reset_usage:
          cursor.execute(
            """
            update user_ai_credit_accounts
            set
              included_monthly_credits = %s,
              used_credits = 0,
              reserved_credits = 0,
              current_period_start = %s,
              current_period_end = %s,
              pricing_version = %s,
              updated_at = %s
            where user_id = %s
            returning *
            """,
            (included, now, period_end, PRICING_VERSION, now, user_id),
          )
        else:
          cursor.execute(
            """
            update user_ai_credit_accounts
            set
              included_monthly_credits = %s,
              pricing_version = %s,
              updated_at = %s
            where user_id = %s
            returning *
            """,
            (included, PRICING_VERSION, now, user_id),
          )
        row = cursor.fetchone()
    if not row:
      return self._serialize_ai_credit_account(None)
    account = dict(row)
    actual_used = 0.0 if reset_usage else self._ai_credits_used_since(user_id, since=account.get("current_period_start") or period_start)
    return self._serialize_ai_credit_account(account, actual_used_credits=actual_used)

  def reserve_ai_credits(
    self,
    user_id: str,
    *,
    estimated_credits: float | int,
    project_id: str | None = None,
    request_id: str | None = None,
    route: str | None = None,
    metadata: dict[str, Any] | None = None,
  ) -> dict[str, Any] | None:
    if not user_id:
      return None
    self.ensure_user_ai_credit_account(user_id)
    reservation_id = new_id()
    safe_estimate = _safe_float(estimated_credits) or 0.0
    account = self.get_user_ai_credit_account(user_id)
    remaining = _safe_float(account.get("remaining_included_credits")) or 0.0
    if safe_estimate > 0 and safe_estimate > remaining:
      raise StorageError("You have completed your user limit.")
    now = _utc_now()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          update user_ai_credit_accounts
          set reserved_credits = reserved_credits + %s, updated_at = %s
          where user_id = %s
          """,
          (safe_estimate, now, user_id),
        )
        cursor.execute(
          """
          insert into ai_credit_reservations (
            id,
            user_id,
            project_id,
            request_id,
            route,
            status,
            estimated_credits,
            pricing_version,
            metadata_json,
            created_at,
            updated_at
          )
          values (%s, %s, %s, %s, %s, 'reserved', %s, %s, %s::jsonb, %s, %s)
          returning *
          """,
          (
            reservation_id,
            user_id,
            project_id or None,
            str(request_id or ""),
            str(route or ""),
            safe_estimate,
            PRICING_VERSION,
            json.dumps(metadata or {}),
            now,
            now,
          ),
        )
        row = cursor.fetchone()
    return dict(row) if row else None

  def sum_ai_credits_for_request(self, user_id: str, request_id: str) -> float:
    if not user_id or not request_id:
      return 0.0
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select coalesce(sum(estimated_credits), 0) as estimated_credits
          from user_token_usage_events
          where user_id = %s and request_id = %s
          """,
          (user_id, request_id),
        )
        row = cursor.fetchone() or {}
    return _safe_float(row.get("estimated_credits")) or 0.0

  def complete_ai_credit_reservation(
    self,
    reservation_id: str,
    *,
    actual_credits: float | int,
    status: str = "completed",
  ) -> dict[str, Any] | None:
    if not reservation_id:
      return None
    safe_actual = _safe_float(actual_credits) or 0.0
    final_status = status if status in {"completed", "cancelled", "failed"} else "completed"
    now = _utc_now()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute("select * from ai_credit_reservations where id = %s for update", (reservation_id,))
        existing = cursor.fetchone()
        if not existing:
          return None
        reservation = dict(existing)
        estimated = _safe_float(reservation.get("estimated_credits")) or 0.0
        user_id = str(reservation.get("user_id") or "")
        used_delta = safe_actual if final_status == "completed" else 0.0
        cursor.execute(
          """
          update user_ai_credit_accounts
          set
            reserved_credits = greatest(0, reserved_credits - %s),
            used_credits = used_credits + %s,
            updated_at = %s
          where user_id = %s
          """,
          (estimated, used_delta, now, user_id),
        )
        cursor.execute(
          """
          update ai_credit_reservations
          set
            status = %s,
            actual_credits = %s,
            updated_at = %s,
            completed_at = %s
          where id = %s
          returning *
          """,
          (final_status, safe_actual, now, now, reservation_id),
        )
        row = cursor.fetchone()
    return dict(row) if row else None

  def record_user_token_usage_event(
    self,
    user_id: str,
    *,
    project_id: str | None = None,
    request_id: str | None = None,
    generation_run_id: str | None = None,
    agent_run_id: str | None = None,
    provider: str = "gemini",
    model: str | None = None,
    call: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    thought_tokens: int | None = None,
    cached_tokens: int | None = None,
    cached_input_tokens: int | None = None,
    prompt_chars: int | None = None,
    output_chars: int | None = None,
    estimated_cost_usd: float | int | None = None,
    estimated_credits: float | int | None = None,
    pricing_version: str | None = None,
    route: str | None = None,
    execution_stage: str | None = None,
    model_role: str | None = None,
    thinking_level: str | None = None,
    context_chars: int | None = None,
    duration_ms: float | int | None = None,
    metadata: dict[str, Any] | None = None,
  ) -> dict[str, Any] | None:
    if not user_id:
      return None
    event_id = new_id()
    safe_input = _safe_int(input_tokens)
    safe_output = _safe_int(output_tokens)
    safe_thought = _safe_int(thought_tokens)
    safe_cached = _safe_int(cached_tokens)
    safe_cached_input = _safe_int(cached_input_tokens) or safe_cached
    safe_total = _safe_int(total_tokens) or safe_input + safe_output + safe_thought
    pricing = estimate_model_usage_cost(
      model=model,
      input_tokens=safe_input,
      output_tokens=safe_output,
      thought_tokens=safe_thought,
      cached_tokens=safe_cached_input,
    )
    safe_cost = _safe_float(estimated_cost_usd)
    safe_credits = _safe_float(estimated_credits)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into user_token_usage_events (
            id,
            user_id,
            project_id,
            request_id,
            generation_run_id,
            agent_run_id,
            provider,
            model,
            call_label,
            input_tokens,
            output_tokens,
            total_tokens,
            thought_tokens,
            cached_tokens,
            cached_input_tokens,
            prompt_chars,
            output_chars,
            estimated_cost_usd,
            estimated_credits,
            pricing_version,
            route,
            execution_stage,
            model_role,
            thinking_level,
            context_chars,
            duration_ms,
            metadata_json
          )
          values (
            %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s::jsonb
          )
          returning *
          """,
          (
            event_id,
            user_id,
            project_id or None,
            str(request_id or ""),
            str(generation_run_id or ""),
            str(agent_run_id or ""),
            str(provider or "gemini"),
            str(model or ""),
            str(call or ""),
            safe_input,
            safe_output,
            safe_total,
            safe_thought,
            safe_cached,
            safe_cached_input,
            _safe_int(prompt_chars),
            _safe_int(output_chars),
            safe_cost if safe_cost is not None else pricing["estimated_cost_usd"],
            safe_credits if safe_credits is not None else pricing["estimated_credits"],
            str(pricing_version or pricing["pricing_version"] or ""),
            str(route or ""),
            str(execution_stage or ""),
            str(model_role or ""),
            str(thinking_level or ""),
            _safe_int(context_chars),
            _safe_float(duration_ms),
            json.dumps(metadata or {}),
          ),
        )
        row = cursor.fetchone()
        return self._serialize_token_usage_event(dict(row)) if row else None

  def ensure_user_usage_limits(
    self,
    user_id: str,
    *,
    daily_token_limit: int,
    weekly_token_limit: int,
    monthly_token_limit: int,
  ) -> dict[str, Any]:
    now = _utc_now()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into user_usage_limits (
            user_id,
            daily_token_limit,
            weekly_token_limit,
            monthly_token_limit,
            daily_tokens_used,
            weekly_tokens_used,
            monthly_tokens_used,
            daily_period_start,
            weekly_period_start,
            monthly_period_start,
            updated_at
          )
          values (%s, %s, %s, %s, 0, 0, 0, %s, %s, %s, %s)
          on conflict (user_id) do nothing
          """,
          (
            user_id,
            daily_token_limit,
            weekly_token_limit,
            monthly_token_limit,
            _period_start(now, unit="day"),
            _period_start(now, unit="week"),
            _period_start(now, unit="month"),
            now,
          ),
        )
        cursor.execute("select * from user_usage_limits where user_id = %s", (user_id,))
        row = cursor.fetchone()
        if not row:
          raise StorageError("Failed to initialize user usage limits.")
        return dict(row)

  def get_user_usage_limits_row(self, user_id: str) -> dict[str, Any] | None:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute("select * from user_usage_limits where user_id = %s", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

  def get_user_account_row(self, user_id: str) -> dict[str, Any] | None:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select id, email, role, display_name, is_active, created_by_admin_id, created_at
          from users
          where id = %s
          """,
          (user_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

  def get_user_usage_summary(
    self,
    user_id: str,
    *,
    recent_request_limit: int = 10,
    recent_call_limit: int = 20,
  ) -> dict[str, Any]:
    account = self.get_user_account_row(user_id)
    if not account:
      raise StorageError("User not found.")
    usage = self.get_user_usage_limits_row(user_id)
    summary = serialize_usage_summary(
      user_id=user_id,
      role=str(account.get("role") or "owner"),
      is_active=bool(account.get("is_active", True)),
      usage_row=usage,
    )
    summary["model_usage"] = self.get_user_token_usage_details(
      user_id,
      recent_request_limit=recent_request_limit,
      recent_call_limit=recent_call_limit,
    )
    credit_account = summary["model_usage"].get("credit_account") or {}
    if str(account.get("role") or "") != "admin" and credit_account.get("limit_reached"):
      summary["blocked_reason"] = str(credit_account.get("blocked_reason") or "You have completed your user limit.")
    return summary

  def user_usage_allows_generation(self, user_id: str, *, role: str, is_active: bool) -> tuple[bool, str]:
    if role == "admin":
      return True, ""
    if not is_active:
      return False, "Account is suspended. Contact your administrator."
    credit_account = self.get_user_ai_credit_account(user_id)
    if credit_account.get("limit_reached"):
      return False, str(credit_account.get("blocked_reason") or "You have completed your user limit.")
    return True, ""

  def record_user_token_usage(self, user_id: str, tokens: int) -> None:
    amount = max(0, int(tokens or 0))
    if amount <= 0:
      return
    account = self.get_user_account_row(user_id)
    if not account:
      return
    if str(account.get("role") or "") == "admin":
      return
    now = _utc_now()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute("select * from user_usage_limits where user_id = %s for update", (user_id,))
        row = cursor.fetchone()
        if not row:
          return
        normalized = _normalize_usage_row(dict(row), now=now)
        cursor.execute(
          """
          update user_usage_limits
          set
            daily_tokens_used = %s,
            weekly_tokens_used = %s,
            monthly_tokens_used = %s,
            daily_period_start = %s,
            weekly_period_start = %s,
            monthly_period_start = %s,
            updated_at = %s
          where user_id = %s
          """,
          (
            int(normalized["daily_tokens_used"]) + amount,
            int(normalized["weekly_tokens_used"]) + amount,
            int(normalized["monthly_tokens_used"]) + amount,
            normalized["daily_period_start"],
            normalized["weekly_period_start"],
            normalized["monthly_period_start"],
            now,
            user_id,
          ),
        )

  def update_user_usage_limits(
    self,
    user_id: str,
    *,
    daily_token_limit: int | None = None,
    weekly_token_limit: int | None = None,
    monthly_token_limit: int | None = None,
    reset_usage: bool = False,
  ) -> dict[str, Any]:
    existing = self.get_user_usage_limits_row(user_id)
    if not existing:
      raise StorageError("Usage limits not found for user.")
    now = _utc_now()
    daily_limit = int(daily_token_limit if daily_token_limit is not None else existing.get("daily_token_limit") or 0)
    weekly_limit = int(weekly_token_limit if weekly_token_limit is not None else existing.get("weekly_token_limit") or 0)
    monthly_limit = int(monthly_token_limit if monthly_token_limit is not None else existing.get("monthly_token_limit") or 0)
    if reset_usage:
      daily_used = 0
      weekly_used = 0
      monthly_used = 0
      daily_start = _period_start(now, unit="day")
      weekly_start = _period_start(now, unit="week")
      monthly_start = _period_start(now, unit="month")
    else:
      normalized = _normalize_usage_row(dict(existing), now=now)
      daily_used = int(normalized.get("daily_tokens_used") or 0)
      weekly_used = int(normalized.get("weekly_tokens_used") or 0)
      monthly_used = int(normalized.get("monthly_tokens_used") or 0)
      daily_start = normalized.get("daily_period_start")
      weekly_start = normalized.get("weekly_period_start")
      monthly_start = normalized.get("monthly_period_start")
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          update user_usage_limits
          set
            daily_token_limit = %s,
            weekly_token_limit = %s,
            monthly_token_limit = %s,
            daily_tokens_used = %s,
            weekly_tokens_used = %s,
            monthly_tokens_used = %s,
            daily_period_start = %s,
            weekly_period_start = %s,
            monthly_period_start = %s,
            updated_at = %s
          where user_id = %s
          returning *
          """,
          (
            daily_limit,
            weekly_limit,
            monthly_limit,
            daily_used,
            weekly_used,
            monthly_used,
            daily_start,
            weekly_start,
            monthly_start,
            now,
            user_id,
          ),
        )
        row = cursor.fetchone()
        if not row:
          raise StorageError("Failed to update usage limits.")
        return dict(row)

  def extend_user_usage_limits(
    self,
    user_id: str,
    *,
    add_daily: int = 0,
    add_weekly: int = 0,
    add_monthly: int = 0,
    reset_usage: bool = False,
  ) -> dict[str, Any]:
    existing = self.get_user_usage_limits_row(user_id)
    if not existing:
      raise StorageError("Usage limits not found for user.")
    normalized = _normalize_usage_row(dict(existing))
    return self.update_user_usage_limits(
      user_id,
      daily_token_limit=int(normalized.get("daily_token_limit") or 0) + max(0, int(add_daily)),
      weekly_token_limit=int(normalized.get("weekly_token_limit") or 0) + max(0, int(add_weekly)),
      monthly_token_limit=int(normalized.get("monthly_token_limit") or 0) + max(0, int(add_monthly)),
      reset_usage=reset_usage,
    )

  def list_managed_users(self) -> list[dict[str, Any]]:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select
            u.id,
            u.email,
            u.role,
            u.display_name,
            u.is_active,
            u.created_by_admin_id,
            u.created_at,
            l.daily_token_limit,
            l.weekly_token_limit,
            l.monthly_token_limit,
            l.daily_tokens_used,
            l.weekly_tokens_used,
            l.monthly_tokens_used
          from users u
          left join user_usage_limits l on l.user_id = u.id
          order by u.created_at desc
          """
        )
        rows = cursor.fetchall() or []
    results: list[dict[str, Any]] = []
    for row in rows:
      account = dict(row)
      usage_summary = serialize_usage_summary(
        user_id=str(account["id"]),
        role=str(account.get("role") or "owner"),
        is_active=bool(account.get("is_active", True)),
        usage_row=account,
      )
      usage_summary["model_usage"] = self.get_user_token_usage_details(str(account["id"]), recent_request_limit=5, recent_call_limit=5)
      results.append(
        {
          "id": account["id"],
          "email": account["email"],
          "role": account["role"],
          "display_name": account.get("display_name") or "",
          "is_active": bool(account.get("is_active", True)),
          "created_at": account.get("created_at"),
          "usage": usage_summary,
        }
      )
    return results

  def set_user_active(self, user_id: str, *, is_active: bool) -> None:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute("update users set is_active = %s where id = %s", (bool(is_active), user_id))

  def delete_managed_user(self, user_id: str) -> None:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute("delete from users where id = %s", (user_id,))
