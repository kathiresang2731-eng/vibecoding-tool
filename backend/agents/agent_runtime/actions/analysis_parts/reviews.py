from __future__ import annotations

from ...memory import persist_memory_checkpoint
from ...model_agents import run_review_agent
from ...state import append_step
from ...values import object_value
from ..context import RuntimeActionContext


def handle_ux_review(ctx: RuntimeActionContext) -> None:
  state = ctx.state
  agent = ctx.agent
  review = run_review_agent(
    ctx.control_provider,
    trace_label="ux_review_agent",
    system_instruction="You are a UX review agent. Return strict JSON only.",
    prompt="Review the website plan for user workflow, conversion clarity, responsive layout, and missing content.",
    state=state,
  )
  state["ux_review"] = review
  append_step(state, agent, "review_ux_plan", {"plan": object_value(state.get("plan"))}, review)
  persist_memory_checkpoint(state, tool_context=ctx.tool_context, user=ctx.user, namespace="agent", key="latest_ux_review", kind="review", content=review, project_id=ctx.project_id)


def handle_accessibility_review(ctx: RuntimeActionContext) -> None:
  state = ctx.state
  agent = ctx.agent
  review = run_review_agent(
    ctx.control_provider,
    trace_label="accessibility_review_agent",
    system_instruction="You are an accessibility review agent. Return strict JSON only.",
    prompt="Review the website plan for color contrast, semantic structure, keyboard flow, and mobile text fit.",
    state=state,
  )
  state["accessibility_review"] = review
  append_step(state, agent, "review_accessibility_plan", {"plan": object_value(state.get("plan"))}, review)
  persist_memory_checkpoint(state, tool_context=ctx.tool_context, user=ctx.user, namespace="agent", key="latest_accessibility_review", kind="review", content=review, project_id=ctx.project_id)


def handle_parallel_review_agents(ctx: RuntimeActionContext) -> None:
  from ...parallel_actions import run_parallel_review_agents

  state = ctx.state
  parallel_result = run_parallel_review_agents(ctx.control_provider, state=state)
  ux_review = object_value(parallel_result.get("ux_review"))
  accessibility_review = object_value(parallel_result.get("accessibility_review"))
  state["ux_review"] = ux_review
  state["accessibility_review"] = accessibility_review
  append_step(
    state,
    ctx.agent,
    "parallel_review_agents",
    {"plan": object_value(state.get("plan"))},
    {
      "parallel_execution_engine": parallel_result.get("parallel_execution_engine"),
      "ux_status": ux_review.get("status"),
      "accessibility_status": accessibility_review.get("status"),
    },
  )
  append_step(state, "UX Review Agent", "review_ux_plan", {"plan": object_value(state.get("plan"))}, ux_review)
  append_step(state, "Accessibility Agent", "review_accessibility_plan", {"plan": object_value(state.get("plan"))}, accessibility_review)
  persist_memory_checkpoint(
    state,
    tool_context=ctx.tool_context,
    user=ctx.user,
    namespace="agent",
    key="latest_ux_review",
    kind="review",
    content=ux_review,
    project_id=ctx.project_id,
  )
  persist_memory_checkpoint(
    state,
    tool_context=ctx.tool_context,
    user=ctx.user,
    namespace="agent",
    key="latest_accessibility_review",
    kind="review",
    content=accessibility_review,
    project_id=ctx.project_id,
  )
