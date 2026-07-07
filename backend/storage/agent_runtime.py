from __future__ import annotations

from typing import Any

from .errors import StorageError
from .ids import new_id
from .permissions import ensure_project_read, ensure_project_write, require_project, require_write
from .serialization import json_dumps_safe, serialize_row
from .user import UserContext

class AgentRuntimeStoreMixin:
  def create_generation_run(
    self,
    project_id: str,
    user: UserContext,
    *,
    prompt: str,
    provider: str,
    status: str,
    response: dict[str, Any] | None = None,
    error: str | None = None,
  ) -> dict[str, Any]:
    run_id = new_id()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into generation_runs (id, project_id, user_id, prompt, provider, status, response_json, error)
          values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
          returning id, project_id, prompt, provider, status, response_json, error, created_at
          """,
          (
            run_id,
            project_id,
            user.id,
            prompt,
            provider,
            status,
            json_dumps_safe(response, context="generation_run.response") if response is not None else None,
            error,
          ),
        )
        row = cursor.fetchone()
    self.add_event(project_id, user.id, f"generation.{status}", {"run_id": run_id})
    return serialize_row(row)

  def create_agent_run(
    self,
    project_id: str,
    user: UserContext,
    *,
    runtime: str,
    provider: str,
    model: str | None = None,
    status: str = "running",
    input_payload: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    run_id = new_id()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into agent_runs (id, project_id, user_id, runtime, provider, model, status, input_json)
          values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
          returning id, project_id, generation_run_id, user_id, runtime, provider, model, status,
            input_json, output_json, error, started_at, completed_at
          """,
          (
            run_id,
            project_id,
            user.id,
            runtime.strip() or "worktual-python-orchestrator",
            provider.strip() or "unknown",
            model,
            status.strip() or "running",
            json_dumps_safe(input_payload or {}, context="agent_run.input"),
          ),
        )
        row = cursor.fetchone()
    self.add_event(project_id, user.id, "agent.run.started", {"agent_run_id": run_id, "runtime": runtime, "provider": provider})
    return serialize_row(row)

  def complete_agent_run(
    self,
    agent_run_id: str,
    user: UserContext,
    *,
    status: str,
    output_payload: dict[str, Any] | None = None,
    error: str | None = None,
    generation_run_id: str | None = None,
  ) -> dict[str, Any]:
    agent_run = self.get_agent_run(agent_run_id, user)
    project = require_project(self, agent_run["project_id"], user)
    ensure_project_write(user, project)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          update agent_runs
          set status = %s,
            output_json = %s::jsonb,
            error = %s,
            generation_run_id = coalesce(%s, generation_run_id),
            completed_at = now()
          where id = %s
          returning id, project_id, generation_run_id, user_id, runtime, provider, model, status,
            input_json, output_json, error, started_at, completed_at
          """,
          (
            status.strip() or "completed",
            json_dumps_safe(output_payload, context="agent_run.output") if output_payload is not None else None,
            error,
            generation_run_id,
            agent_run_id,
          ),
        )
        row = cursor.fetchone()
    self.add_event(agent_run["project_id"], user.id, f"agent.run.{status}", {"agent_run_id": agent_run_id})
    return serialize_row(row)

  def get_agent_run(self, agent_run_id: str, user: UserContext) -> dict[str, Any]:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select id, project_id, generation_run_id, user_id, runtime, provider, model, status,
            input_json, output_json, error, started_at, completed_at
          from agent_runs
          where id = %s
          """,
          (agent_run_id,),
        )
        row = cursor.fetchone()
    if not row:
      raise StorageError("Agent run not found.")
    agent_run = serialize_row(row)
    project = require_project(self, agent_run["project_id"], user)
    ensure_project_read(user, project)
    return agent_run

  def record_agent_message(
    self,
    agent_run_id: str,
    user: UserContext,
    *,
    from_agent: str,
    to_agent: str | None = None,
    role: str,
    content: str = "",
    payload: dict[str, Any] | None = None,
    status: str = "completed",
  ) -> dict[str, Any]:
    agent_run = self.get_agent_run(agent_run_id, user)
    project = require_project(self, agent_run["project_id"], user)
    ensure_project_write(user, project)
    message_id = new_id()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into agent_messages (
            id, agent_run_id, project_id, user_id, from_agent, to_agent, role,
            content, payload_json, status
          )
          values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
          returning id, agent_run_id, project_id, user_id, from_agent, to_agent, role,
            content, payload_json, status, created_at
          """,
          (
            message_id,
            agent_run_id,
            agent_run["project_id"],
            user.id,
            from_agent.strip() or "unknown_agent",
            to_agent.strip() if isinstance(to_agent, str) and to_agent.strip() else None,
            role.strip() or "assistant",
            content,
            json_dumps_safe(payload or {}, context="agent_message.payload"),
            status.strip() or "completed",
          ),
        )
        row = cursor.fetchone()
    return serialize_row(row)

  def record_tool_call(
    self,
    agent_run_id: str,
    user: UserContext,
    *,
    tool_name: str,
    call_id: str | None = None,
    status: str,
    arguments: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
  ) -> dict[str, Any]:
    agent_run = self.get_agent_run(agent_run_id, user)
    project = require_project(self, agent_run["project_id"], user)
    ensure_project_write(user, project)
    tool_call_id = new_id()
    final_status = status.strip() or "completed"
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into tool_calls (
            id, agent_run_id, project_id, user_id, call_id, tool_name, status,
            arguments_json, result_json, error, completed_at
          )
          values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, case when %s != 'running' then now() else null end)
          returning id, agent_run_id, project_id, user_id, call_id, tool_name, status,
            arguments_json, result_json, error, started_at, completed_at
          """,
          (
            tool_call_id,
            agent_run_id,
            agent_run["project_id"],
            user.id,
            call_id or tool_call_id,
            tool_name.strip() or "unknown_tool",
            final_status,
            json_dumps_safe(arguments or {}, context="tool_call.arguments"),
            json_dumps_safe(result, context="tool_call.result") if result is not None else None,
            error,
            final_status,
          ),
        )
        row = cursor.fetchone()
    return serialize_row(row)

  def record_generation_checkpoint(
    self,
    agent_run_id: str,
    user: UserContext,
    *,
    thread_id: str,
    step_name: str,
    state: dict[str, Any],
  ) -> dict[str, Any]:
    agent_run = self.get_agent_run(agent_run_id, user)
    project = require_project(self, agent_run["project_id"], user)
    ensure_project_write(user, project)
    checkpoint_id = new_id()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into generation_checkpoints (id, agent_run_id, project_id, user_id, thread_id, step_name, state_json)
          values (%s, %s, %s, %s, %s, %s, %s::jsonb)
          returning id, agent_run_id, project_id, user_id, thread_id, step_name, state_json, created_at
          """,
          (
            checkpoint_id,
            agent_run_id,
            agent_run["project_id"],
            user.id,
            thread_id.strip() or agent_run_id,
            step_name.strip() or "unknown_step",
            json_dumps_safe(state, context="generation_checkpoint.state"),
          ),
        )
        row = cursor.fetchone()
    return serialize_row(row)
