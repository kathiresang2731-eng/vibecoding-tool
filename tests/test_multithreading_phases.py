import importlib.util
from pathlib import Path

from backend.agents.dynamic_agenting.execution import _clone_provider_for_thread
from backend.agents.providers.gemini import GeminiProvider
from backend.agents.providers.thread_clone import clone_llm_provider

_events_path = Path(__file__).resolve().parents[1] / "backend" / "api" / "v1" / "events.py"
_events_spec = importlib.util.spec_from_file_location("_v1_events_under_test", _events_path)
assert _events_spec and _events_spec.loader
_events_mod = importlib.util.module_from_spec(_events_spec)
_events_spec.loader.exec_module(_events_mod)
translate_legacy_stream_event = _events_mod.translate_legacy_stream_event


def test_clone_llm_provider_returns_distinct_gemini_instances() -> None:
  shared = GeminiProvider(model="gemini-test")
  first = clone_llm_provider(shared)
  second = clone_llm_provider(shared)
  assert first is not shared
  assert second is not shared
  assert first is not second
  assert getattr(first, "model", None) == "gemini-test"


def test_clone_llm_provider_copies_chat_history() -> None:
  shared = GeminiProvider(model="gemini-test")
  shared.chat_history = [{"role": "user", "parts": [{"text": "prior turn"}]}]
  cloned = clone_llm_provider(shared)
  assert cloned.chat_history == shared.chat_history
  assert cloned.chat_history is not shared.chat_history
  assert getattr(cloned, "model", None) == "gemini-test"


def test_dynamic_agenting_clone_provider_for_thread() -> None:
  shared = GeminiProvider(model="gemini-test")
  cloned = _clone_provider_for_thread(shared)
  assert cloned is not shared


def test_v1_parallel_wave_event_marks_execution_engine() -> None:
  event = translate_legacy_stream_event(
    {
      "step": "agent.parallel.wave.started",
      "status": "running",
      "message": "Wave 1/2: 3 worker(s) in parallel",
      "detail": {"wave": 1, "task_ids": ["t1", "t2"]},
    },
    run_id="run-1",
    workspace_id="project-1",
    client="web",
  )
  assert event["type"] == "run.progress"
  assert event["detail"]["execution_engine"] == "parallel"
  assert event["detail"]["step"] == "agent.parallel.wave.started"


def test_v1_update_analysis_event_marks_execution_engine() -> None:
  event = translate_legacy_stream_event(
    {
      "step": "update.analysis.completed",
      "status": "completed",
      "message": "Update analysis ready for parallel worker planning",
      "detail": {"preflight_source": "heuristic_code_search", "candidate_files": ["src/App.jsx"]},
    },
    run_id="run-1",
    workspace_id="project-1",
    client="web",
  )
  assert event["type"] == "run.progress"
  assert event["detail"]["execution_engine"] == "parallel"
  assert event["detail"]["preflight_source"] == "heuristic_code_search"
