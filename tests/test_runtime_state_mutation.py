import threading

from backend.agents.schema.json_safe import json_dumps_for_persistence, sanitize_for_persistence


def test_json_dumps_for_persistence_survives_concurrent_dict_mutation() -> None:
  payload = {"results": {"task-a": {"status": "completed"}, "task-b": {"status": "running"}}}
  errors: list[Exception] = []

  def mutate() -> None:
    try:
      for index in range(200):
        payload["results"][f"task-{index}"] = {"status": "running"}
        payload["results"].pop("task-a", None)
    except Exception as exc:
      errors.append(exc)

  worker = threading.Thread(target=mutate)
  worker.start()
  try:
    for _ in range(50):
      json_dumps_for_persistence(payload, context="test.concurrent_mutation")
      sanitize_for_persistence(payload)
  finally:
    worker.join(timeout=2)
  assert not errors
