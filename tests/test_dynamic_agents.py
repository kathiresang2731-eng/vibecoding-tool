import json
import time

from backend.llm.dynamic_agents import (
  ALLOWED_DYNAMIC_TOOLS,
  MAX_DYNAMIC_AGENTS_PER_WORKFLOW,
  AgentDefinition,
  AgentRegistry,
  agent_definition_from_storage_row,
  allowed_dynamic_tool_schemas,
  build_guarded_dynamic_tool_executor,
  build_user_agent_registry,
  build_parallel_groups,
  create_dynamic_workflow,
  decompose_capability_tasks,
  dynamic_agent_promotion_min_successes,
  execute_dynamic_specialists,
  execute_specialist_task,
  hydrate_registry_from_memories,
  merge_capability_tasks,
  persist_user_dynamic_agents,
  request_model_task_decomposition,
  run_with_timeout,
  safe_runtime_action,
  task,
  validate_candidate_changes,
)


class UnsafeTaskProvider:
  def generate_json(self, _prompt, **kwargs):
    if kwargs.get("trace_label") == "dynamic_task_decomposer":
      return {
        "tasks": [
          {
            "id": "unsafe_write",
            "name": "Unsafe write",
            "required_capability": "checkout_flow",
            "dependencies": [],
            "risk_level": "high",
            "runtime_action": "WRITE_PROJECT_FILES",
          }
        ]
      }
    return {}


def test_default_registry_contains_seven_core_and_eight_reusable_agents():
  snapshot = AgentRegistry().snapshot()

  assert snapshot["agent_count"] == 15
  assert snapshot["core_count"] == 7
  assert snapshot["reusable_count"] == 8
  assert snapshot["experimental_count"] == 0


def test_crm_workflow_creates_and_promotes_missing_specialists_for_reuse():
  registry = AgentRegistry()
  workflow = create_dynamic_workflow(
    "Build a CRM with deal pipeline and role permissions",
    routing_result={"intent": "website_generation"},
    brief={"business_type": "CRM"},
    registry=registry,
  )

  assert workflow["domain"] == "crm"
  assert workflow["created_agent_ids"] == ["crm_pipeline_agent", "rbac_agent"]
  for agent_id in workflow["created_agent_ids"]:
    agent = registry.agents[agent_id]
    assert agent.lifecycle == "experimental"
    assert set(agent.tools) == ALLOWED_DYNAMIC_TOOLS
    assert agent.constraints["direct_file_writes"] is False

  for _index in range(dynamic_agent_promotion_min_successes()):
    registry.mark_workflow_success(workflow["assignments"])
  for agent_id in workflow["created_agent_ids"]:
    assert registry.agents[agent_id].lifecycle == "reusable"
    assert registry.agents[agent_id].metrics["successful_runs"] == dynamic_agent_promotion_min_successes()

  reused_workflow = create_dynamic_workflow(
    "Build another CRM with deal pipeline and role permissions",
    routing_result={"intent": "website_generation"},
    brief={"business_type": "CRM"},
    registry=registry,
  )

  assert reused_workflow["created_agent_ids"] == []
  assert {"crm_pipeline_agent", "rbac_agent"}.issubset(set(reused_workflow["reused_agent_ids"]))


def test_domain_decomposition_adds_expected_temporary_capabilities():
  ecommerce = decompose_capability_tasks(
    "Build an online store with product catalog, cart, and checkout",
    domain="custom_store",
    scope="large",
  )
  booking = decompose_capability_tasks("Build a booking website with appointments", domain="booking", scope="medium")

  assert {"checkout_flow", "inventory"}.issubset({item.required_capability for item in ecommerce})
  assert "booking_workflow" in {item.required_capability for item in booking}


def test_dynamic_agent_creation_is_capped_and_falls_back_to_guarded_core_agent():
  registry = AgentRegistry()
  tasks = [
    task(f"custom_{index}", f"Custom {index}", f"custom_capability_{index}", [], "medium", "RUN_DYNAMIC_SPECIALISTS")
    for index in range(MAX_DYNAMIC_AGENTS_PER_WORKFLOW + 1)
  ]

  assignments, created_ids, _reused_ids = registry.assign_tasks(tasks, domain="custom")

  assert len(created_ids) == MAX_DYNAMIC_AGENTS_PER_WORKFLOW
  assert assignments[-1].assignment_type == "fallback"
  assert assignments[-1].agent_id == "task-decomposer-agent"


def test_reserved_runtime_capability_never_creates_dynamic_agent():
  registry = AgentRegistry(owner_user_id="user-1")
  memory_task = task(
    "persist_project_memory",
    "Persist project memory",
    "memory_persistence",
    [],
    "low",
    "PERSIST_PROJECT_MEMORY",
  )

  assignments, created_ids, reused_ids = registry.assign_tasks([memory_task], domain="e_commerce")

  assert created_ids == []
  assert reused_ids == []
  assert "memory_persistence_agent" not in registry.agents
  assert assignments[0].assignment_type == "fallback"
  assert assignments[0].agent_id == "memory-agent"


def test_model_cannot_schedule_direct_file_write_from_dynamic_task():
  model_tasks = request_model_task_decomposition(
    UnsafeTaskProvider(),
    "Build an online store",
    routing_result={"intent": "website_generation"},
    brief={"business_type": "e-commerce"},
  )

  assert model_tasks[0].runtime_action == "RUN_DYNAMIC_SPECIALISTS"
  assert safe_runtime_action("WRITE_PROJECT_FILES", "checkout_flow") == "RUN_DYNAMIC_SPECIALISTS"


def test_model_task_merge_skips_duplicate_and_runtime_core_capabilities():
  deterministic = decompose_capability_tasks("Build an e-commerce store", domain="e_commerce", scope="large")
  model_tasks = [
    task("checkout_extra", "Checkout extra", "checkout_flow", [], "medium", "RUN_DYNAMIC_SPECIALISTS"),
    task("project_planning_extra", "Project planning", "project_planning", [], "low", "RUN_DYNAMIC_SPECIALISTS"),
    task("extra_preview", "Extra preview", "custom_preview", [], "low", "BUILD_STAGED_PROJECT_PREVIEW"),
    task("react_dev_extra", "React dev", "react_tailwind_development", [], "high", "RUN_DYNAMIC_SPECIALISTS"),
    task("loyalty_program", "Loyalty program", "loyalty_program", [], "medium", "RUN_DYNAMIC_SPECIALISTS"),
  ]

  merged = merge_capability_tasks(deterministic, model_tasks, domain="e_commerce")
  capabilities = [item.required_capability for item in merged]

  assert capabilities.count("checkout_flow") == 1
  assert "project_planning" not in capabilities
  assert "custom_preview" not in capabilities
  assert "react_tailwind_development" not in capabilities
  assert "loyalty_program" in capabilities


def test_project_specific_dynamic_agent_prompt_is_sanitized_before_registration():
  registry = AgentRegistry(owner_user_id="user-1")

  class ProjectSpecificProvider:
    def generate_json(self, _prompt, **_kwargs):
      return {
        "id": "tailwind_style_updater",
        "name": "Tailwind Style Updater",
        "role": "Update current website colors.",
        "system_prompt": "You are tailoring styles for the 'Yoga & choga' website. The current focus is the 'Yoga & choga' warm wellness palette.",
        "capabilities": ["tailwind_style_update"],
        "supported_domains": ["yoga_apparel"],
      }

  style_task = task(
    "tailwind_style_update",
    "Tailwind style update",
    "tailwind_style_update",
    [],
    "medium",
    "RUN_DYNAMIC_SPECIALISTS",
  )

  agent = registry.create_dynamic_agent(style_task, domain="e_commerce", provider=ProjectSpecificProvider())

  assert agent.id == "tailwind_style_updater"
  assert "Yoga" not in agent.system_prompt
  assert "choga" not in agent.system_prompt
  assert "hard-code" in agent.system_prompt


def test_parallel_groups_preserve_dependencies_and_serial_guarded_actions():
  tasks = decompose_capability_tasks("Build an e-commerce store", domain="e_commerce", scope="large")
  groups = build_parallel_groups(tasks)
  group_index = {task_id: index for index, group in enumerate(groups) for task_id in group}
  tasks_by_id = {task_item.id: task_item for task_item in tasks}

  for task_item in tasks:
    assert all(group_index[dependency] < group_index[task_item.id] for dependency in task_item.dependencies)

  guarded_ids = ["code_generation", "artifact_validation", "preview_build", "visual_qa", "memory_persist"]
  assert [group_index[task_id] for task_id in guarded_ids] == sorted(group_index[task_id] for task_id in guarded_ids)
  assert all(len(groups[group_index[task_id]]) == 1 for task_id in guarded_ids)
  assert tasks_by_id["repair_if_needed"].optional is True


def test_dynamic_specialists_execute_only_planning_tasks_in_workflow_groups():
  registry = AgentRegistry()
  workflow = create_dynamic_workflow(
    "Build an online store with product catalog and checkout",
    routing_result={"intent": "website_generation"},
    brief={"business_type": "online-store"},
    registry=registry,
  )

  results = execute_dynamic_specialists(
    None,
    workflow,
    prompt="Build an online store with product catalog and checkout",
    brief={"business_type": "online-store"},
    plan={"sections": ["Catalog", "Cart", "Checkout"]},
    registry=registry,
  )

  completed = set(results["completed_task_ids"])
  assert {"content_strategy", "component_plan", "checkout_flow", "inventory"}.issubset(completed)
  assert "code_generation" not in completed
  assert results["parallel_groups_executed"]
  assert {
    result["source"]
    for result in results["results"].values()
    if isinstance(result, dict)
  } == {"required_dynamic_agent_unavailable"}
  assert all(
    execution["execution_failed"] is True
    for execution in results["dynamic_agent_executions"]
  )


def test_successful_dynamic_agents_can_be_hydrated_from_project_memory():
  source_registry = AgentRegistry()
  workflow = create_dynamic_workflow(
    "Build a booking website",
    routing_result={"intent": "website_generation"},
    brief={"business_type": "booking"},
    registry=source_registry,
  )
  for _index in range(dynamic_agent_promotion_min_successes()):
    source_registry.mark_workflow_success(workflow["assignments"])
  snapshot = source_registry.snapshot(agent_ids=workflow["created_agent_ids"])
  restored_registry = AgentRegistry()

  hydrated_ids = hydrate_registry_from_memories(
    [
      {
        "key": "latest_dynamic_agent_registry",
        "kind": "agent_registry",
        "content": json.dumps(snapshot),
      }
    ],
    registry=restored_registry,
  )

  assert hydrated_ids == ["booking_workflow_agent"]
  assert restored_registry.agents["booking_workflow_agent"].lifecycle == "reusable"
  assert set(restored_registry.agents["booking_workflow_agent"].tools) == ALLOWED_DYNAMIC_TOOLS


class FakeUser:
  def __init__(self, user_id):
    self.id = user_id


class FakeDynamicAgentStore:
  def __init__(self):
    self.rows_by_user = {}

  def list_dynamic_agent_definitions(self, user, include_disabled=False):
    rows = list(self.rows_by_user.get(user.id, []))
    return rows if include_disabled else [row for row in rows if row["lifecycle"] != "disabled"]

  def upsert_dynamic_agent_definition(self, user, *, agent_key, lifecycle, definition, metrics):
    rows = self.rows_by_user.setdefault(user.id, [])
    existing = next((row for row in rows if row["agent_key"] == agent_key), None)
    if existing:
      existing.update(
        {
          "version": existing["version"] + 1,
          "lifecycle": lifecycle,
          "definition_json": definition,
          "metrics_json": metrics,
        }
      )
      return existing
    row = {
      "id": f"{user.id}-{agent_key}",
      "owner_user_id": user.id,
      "agent_key": agent_key,
      "version": 1,
      "lifecycle": lifecycle,
      "definition_json": definition,
      "metrics_json": metrics,
    }
    rows.append(row)
    return row


def test_user_scoped_registry_isolated_between_users_and_reused_across_projects():
  store = FakeDynamicAgentStore()
  user_one = FakeUser("user-1")
  user_two = FakeUser("user-2")
  registry_one = build_user_agent_registry(store, user_one)
  workflow = create_dynamic_workflow(
    "Build a booking website",
    routing_result={"intent": "website_generation"},
    brief={"business_type": "booking"},
    registry=registry_one,
  )
  persist_user_dynamic_agents(store, user_one, registry_one, agent_ids=workflow["created_agent_ids"])

  reloaded_one = build_user_agent_registry(store, user_one)
  reloaded_two = build_user_agent_registry(store, user_two)

  assert "booking_workflow_agent" in reloaded_one.agents
  assert reloaded_one.agents["booking_workflow_agent"].owner_user_id == "user-1"
  assert "booking_workflow_agent" not in reloaded_two.agents


def test_invalid_persisted_dynamic_agents_are_not_rehydrated_or_repersisted():
  store = FakeDynamicAgentStore()
  user = FakeUser("user-1")
  bad_memory_agent = AgentDefinition(
    id="memory_persistence_agent",
    name="Memory Persistence Agent",
    role="Persist project memory.",
    capabilities=["memory_persistence"],
    system_prompt="Persist memory for this project.",
    tools=["READ_PROJECT_FILES"],
    supported_domains=["e_commerce"],
    constraints={"python_tool_execution_only": True, "direct_file_writes": False},
    metrics={"usage_count": 0},
    lifecycle="experimental",
    owner_user_id="user-1",
    allowed_tools=["READ_PROJECT_FILES"],
  )
  project_specific_agent = AgentDefinition(
    id="tailwind_style_updater",
    name="Tailwind Style Updater",
    role="Style updater.",
    capabilities=["tailwind_style_update"],
    system_prompt="The current focus is the 'Yoga & choga' warm wellness palette.",
    tools=["READ_PROJECT_FILES"],
    supported_domains=["yoga_apparel"],
    constraints={"python_tool_execution_only": True, "direct_file_writes": False},
    metrics={"usage_count": 0},
    lifecycle="experimental",
    owner_user_id="user-1",
    allowed_tools=["READ_PROJECT_FILES"],
  )
  store.rows_by_user[user.id] = [
    {
      "id": "row-1",
      "owner_user_id": user.id,
      "agent_key": bad_memory_agent.id,
      "version": 5,
      "lifecycle": "experimental",
      "definition_json": bad_memory_agent.to_dict(),
      "metrics_json": bad_memory_agent.metrics,
    },
    {
      "id": "row-2",
      "owner_user_id": user.id,
      "agent_key": project_specific_agent.id,
      "version": 1,
      "lifecycle": "experimental",
      "definition_json": project_specific_agent.to_dict(),
      "metrics_json": project_specific_agent.metrics,
    },
  ]

  registry = build_user_agent_registry(store, user)

  assert "memory_persistence_agent" not in registry.agents
  assert "tailwind_style_updater" not in registry.agents


def test_persisted_agent_payload_keeps_metrics_separate_from_definition():
  store = FakeDynamicAgentStore()
  user = FakeUser("user-1")
  registry = AgentRegistry(owner_user_id=user.id)
  workflow = create_dynamic_workflow(
    "Build a booking website",
    routing_result={"intent": "website_generation"},
    brief={"business_type": "booking"},
    registry=registry,
  )

  rows = persist_user_dynamic_agents(store, user, registry, agent_ids=workflow["created_agent_ids"])

  assert rows
  assert "metrics" not in rows[0]["definition_json"]
  assert rows[0]["metrics_json"]["usage_count"] == 0


def test_agent_definition_from_storage_row_rejects_reserved_capability():
  row = {
    "agent_key": "memory_persistence_agent",
    "version": 1,
    "lifecycle": "experimental",
    "definition_json": {
      "id": "memory_persistence_agent",
      "name": "Memory Persistence Agent",
      "capabilities": ["memory_persistence"],
      "system_prompt": "Persist memory.",
      "supported_domains": ["e_commerce"],
      "allowed_tools": ["READ_PROJECT_FILES"],
      "constraints": {"python_tool_execution_only": True, "direct_file_writes": False},
    },
    "metrics_json": {},
  }

  assert agent_definition_from_storage_row(row, owner_user_id="user-1") is None


def test_guarded_dynamic_tool_executor_rejects_dangerous_tool_and_candidate_limits():
  registry = AgentRegistry(owner_user_id="user-1")
  workflow = create_dynamic_workflow(
    "Build a booking website",
    routing_result={"intent": "website_generation"},
    brief={"business_type": "booking"},
    registry=registry,
  )
  agent = registry.agents[workflow["created_agent_ids"][0]]
  safety_violations = []
  guarded = build_guarded_dynamic_tool_executor(
    agent,
    execute_tool=lambda name, arguments: {"name": name, "arguments": arguments},
    safety_violations=safety_violations,
  )

  assert guarded("READ_PROJECT_FILES", {})["name"] == "READ_PROJECT_FILES"
  try:
    guarded("WRITE_PROJECT_FILES", {"files": []})
  except RuntimeError as exc:
    assert "forbidden" in str(exc)
  else:
    raise AssertionError("Dangerous dynamic tool request was not rejected.")
  assert safety_violations
  schemas = allowed_dynamic_tool_schemas(agent.allowed_tools)
  assert {schema["name"] for schema in schemas} == ALLOWED_DYNAMIC_TOOLS
  assert all("project_id" not in schema["parameters"]["properties"] for schema in schemas)

  accepted, rejected = validate_candidate_changes(
    [
      {"path": "src/Booking.jsx", "content": "export default function Booking() { return <main />; }"},
      {"path": "../secret.txt", "content": "secret"},
      {"path": "src/Booking.jsx", "content": "duplicate"},
      {"path": "src/Delete.jsx", "operation": "delete", "content": ""},
    ],
    agent=agent,
    task_id="booking_workflow",
  )

  assert [item["path"] for item in accepted] == ["src/Booking.jsx"]
  assert len(rejected) == 3


def test_dynamic_agent_disables_after_three_consecutive_failures():
  registry = AgentRegistry(owner_user_id="user-1")
  workflow = create_dynamic_workflow(
    "Build a booking website",
    routing_result={"intent": "website_generation"},
    brief={"business_type": "booking"},
    registry=registry,
  )
  agent_id = workflow["created_agent_ids"][0]
  assignment = [item for item in workflow["assignments"] if item["agent_id"] == agent_id]

  for _index in range(3):
    registry.mark_workflow_failure(assignment, reason="candidate failed staged preview")

  agent = registry.agents[agent_id]
  assert agent.lifecycle == "disabled"
  assert agent.metrics["consecutive_failures"] == 3
  assert registry.find_agents_by_capability("booking_workflow")[0].lifecycle == "disabled"

  replacement_workflow = create_dynamic_workflow(
    "Build another booking website",
    routing_result={"intent": "website_generation"},
    brief={"business_type": "booking"},
    registry=registry,
  )
  assert replacement_workflow["created_agent_ids"] == ["booking_workflow_v2_agent"]


def test_optional_dynamic_execution_failure_is_skipped_and_timeout_is_enforced():
  registry = AgentRegistry(owner_user_id="user-1")
  optional_task = task(
    "optional_insight",
    "Optional insight",
    "optional_insight",
    [],
    "low",
    "RUN_DYNAMIC_SPECIALISTS",
    optional=True,
  )
  agent = registry.create_dynamic_agent(optional_task, domain="custom")

  class FailingProvider:
    def generate_json(self, prompt, **kwargs):
      raise RuntimeError("provider unavailable")

  result = execute_specialist_task(
    FailingProvider(),
    optional_task.to_dict(),
    {"agent_id": agent.id, "agent_name": agent.name},
    prompt="Build a custom website",
    brief={},
    plan={},
    registry=registry,
  )

  assert result["status"] == "skipped"
  assert result["execution_failed"] is True
  assert result["source"] == "optional_dynamic_agent_skipped"

  try:
    run_with_timeout(lambda: time.sleep(2), timeout_seconds=1, label="slow-agent")
  except TimeoutError as exc:
    assert "exceeded timeout budget" in str(exc)
  else:
    raise AssertionError("Dynamic agent timeout was not enforced.")


def test_dynamic_specialist_tool_loop_is_opt_in_by_default(monkeypatch):
  registry = AgentRegistry(owner_user_id="user-1")
  workflow = create_dynamic_workflow(
    "Build a booking website",
    routing_result={"intent": "website_generation"},
    brief={"business_type": "booking"},
    registry=registry,
  )
  agent_id = workflow["created_agent_ids"][0]
  task_item = next(item for item in workflow["tasks"] if item["required_capability"] == "booking_workflow")

  class ToolLoopProvider:
    def __init__(self):
      self.generate_calls = 0
      self.tool_loop_calls = 0

    def generate_json(self, prompt, **kwargs):
      self.generate_calls += 1
      return {
        "status": "completed",
        "summary": "Plan booking interactions.",
        "recommendations": ["Show service selection."],
        "requirements": ["Include booking CTA."],
        "risks": [],
        "candidate_changes": [],
      }

    def run_tool_loop(self, **kwargs):
      self.tool_loop_calls += 1
      return {"output_text": '{"status":"completed"}', "tool_calls": []}

  monkeypatch.delenv("ENABLE_DYNAMIC_AGENT_TOOL_LOOP", raising=False)
  provider = ToolLoopProvider()

  result = execute_specialist_task(
    provider,
    task_item,
    {"agent_id": agent_id, "agent_name": registry.agents[agent_id].name},
    prompt="Build a booking website",
    brief={"business_type": "booking"},
    plan={},
    registry=registry,
    execute_tool=lambda name, arguments: {"ok": True},
  )

  assert result["status"] == "completed"
  assert provider.generate_calls == 1
  assert provider.tool_loop_calls == 0
