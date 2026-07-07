from __future__ import annotations

from queue import Empty, Queue
from time import monotonic
from typing import Any, Iterator

from ..constants import GENERATION_STREAM_HEARTBEAT_SECONDS
from ..progress import make_progress_event, ndjson_event


def yield_generation_stream_events(
  event_queue: Queue[dict[str, Any]],
  tracker: dict[str, Any],
) -> Iterator[str]:
  while True:
    try:
      event = event_queue.get(timeout=GENERATION_STREAM_HEARTBEAT_SECONDS)
    except Empty:
      yield ndjson_event(
        {
          "type": "progress",
          **make_progress_event(
            "backend.waiting",
            tracker["last_running_message"],
            detail={"elapsed_seconds": round(monotonic() - tracker["started_at"])},
          ),
        }
      )
      continue

    if event["type"] == "end":
      break
    if event["type"] == "progress" and event.get("status") == "running":
      tracker["last_running_step"] = str(event.get("step") or tracker["last_running_step"])
      tracker["last_running_message"] = str(event.get("message") or tracker["last_running_message"])
    yield ndjson_event(event)

