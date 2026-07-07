from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .constants import BROWSER_QA_TIMEOUT_SECONDS
from .dom_probe import (
  DevToolsClient,
  available_local_port,
  read_process_output,
  stop_process,
  wait_for_cdp_endpoint,
)
from .types import BrowserCommand


INTERACTION_MARKERS = (
  "button",
  "click",
  "onclick",
  "link",
  "cta",
  "redirect",
  "navigate",
  "open",
  "not working",
  "doesn't work",
  "does not work",
  "white page",
  "blank page",
)


def prompt_requires_interaction_qa(prompt: str) -> bool:
  lowered = str(prompt or "").strip().lower()
  return bool(lowered) and any(marker in lowered for marker in INTERACTION_MARKERS)


def run_browser_interaction_qa(
  *,
  browser_command: BrowserCommand,
  target_url: str,
  profile_path: Path,
  prompt: str,
) -> dict[str, Any]:
  if not prompt_requires_interaction_qa(prompt):
    return {"status": "skipped", "reason": "The request does not require an interaction check."}

  port = available_local_port()
  command = [
    *browser_command.parts,
    "--headless=new",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--enable-logging=stderr",
    "--hide-scrollbars",
    "--no-first-run",
    "--no-default-browser-check",
    "--no-sandbox",
    "--remote-allow-origins=*",
    f"--remote-debugging-port={port}",
    f"--user-data-dir={profile_path}",
    "--window-size=1440,1000",
    target_url,
  ]
  process: subprocess.Popen[str] | None = None
  try:
    process = subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    endpoint = wait_for_cdp_endpoint(port, process, timeout_seconds=min(10, BROWSER_QA_TIMEOUT_SECONDS))
    websocket_url = str(endpoint.get("webSocketDebuggerUrl") or "")
    if not websocket_url:
      return interaction_failure(
        target_url=target_url,
        reason=str(endpoint.get("reason") or "DevTools endpoint was unavailable."),
      )

    with DevToolsClient(websocket_url, timeout=min(10, BROWSER_QA_TIMEOUT_SECONDS)) as client:
      for method in ("Page.enable", "Runtime.enable", "Log.enable", "Network.enable"):
        client.call(method)
      client.call("Page.addScriptToEvaluateOnNewDocument", {"source": DIAGNOSTICS_BOOTSTRAP})
      client.call("Page.reload", {"ignoreCache": True})
      _wait_in_browser(client, 900)
      client.pop_events()

      click_result = _evaluate_value(
        client,
        f"({CLICK_REQUESTED_CONTROL_SCRIPT})({json.dumps(prompt)})",
      )
      if not isinstance(click_result, dict) or not click_result.get("clicked"):
        return interaction_failure(
          target_url=target_url,
          reason=str((click_result or {}).get("reason") or "No matching visible control was found."),
          selected_control=(click_result or {}).get("selected") if isinstance(click_result, dict) else None,
        )

      _wait_in_browser(client, 1400)
      evidence = _evaluate_value(client, INTERACTION_EVIDENCE_SCRIPT)
      if not isinstance(evidence, dict):
        evidence = {}
      event_evidence = evidence_from_cdp_events(client.pop_events())
      console_errors = unique_items(
        [
          *[item for item in evidence.get("console_errors", []) if isinstance(item, str)],
          *event_evidence["console_errors"],
        ]
      )
      stack_traces = unique_items(
        [
          *[item for item in evidence.get("stack_traces", []) if isinstance(item, str)],
          *event_evidence["stack_traces"],
        ]
      )
      failed_requests = unique_dicts(
        [
          *[item for item in evidence.get("failed_requests", []) if isinstance(item, dict)],
          *event_evidence["failed_requests"],
        ]
      )
      current_url = str(evidence.get("current_url") or target_url)
      blank_page = bool(evidence.get("blank_page"))
      passed = not console_errors and not stack_traces and not failed_requests and not blank_page
      return {
        "status": "passed" if passed else "failed",
        "failure_kind": "" if passed else "interaction_runtime_error",
        "reason": "" if passed else interaction_failure_reason(
          blank_page=blank_page,
          console_errors=console_errors,
          stack_traces=stack_traces,
          failed_requests=failed_requests,
        ),
        "target_url": target_url,
        "current_url": current_url,
        "selected_control": click_result.get("selected"),
        "console_errors": console_errors,
        "stack_traces": stack_traces,
        "failed_requests": failed_requests,
        "blank_page": blank_page,
      }
  except Exception as exc:
    output = read_process_output(process) if process is not None and process.poll() is not None else ""
    suffix = f" {output[:500]}" if output else ""
    return interaction_failure(target_url=target_url, reason=f"Interaction probe failed: {exc}.{suffix}")
  finally:
    if process is not None:
      stop_process(process)


def _wait_in_browser(client: DevToolsClient, milliseconds: int) -> None:
  client.call(
    "Runtime.evaluate",
    {
      "expression": f"new Promise(resolve => setTimeout(resolve, {int(milliseconds)}))",
      "awaitPromise": True,
      "returnByValue": True,
    },
  )


def _evaluate_value(client: DevToolsClient, expression: str) -> Any:
  response = client.call(
    "Runtime.evaluate",
    {"expression": expression, "awaitPromise": True, "returnByValue": True},
  )
  if response.get("exceptionDetails"):
    raise RuntimeError("Browser interaction script raised an exception.")
  result = response.get("result") if isinstance(response.get("result"), dict) else {}
  return result.get("value")


def evidence_from_cdp_events(events: list[dict[str, Any]]) -> dict[str, list[Any]]:
  console_errors: list[str] = []
  stack_traces: list[str] = []
  failed_requests: list[dict[str, Any]] = []
  request_urls: dict[str, str] = {}
  for event in events:
    if str(event.get("method") or "") != "Network.requestWillBeSent":
      continue
    params = event.get("params") if isinstance(event.get("params"), dict) else {}
    request = params.get("request") if isinstance(params.get("request"), dict) else {}
    request_id = str(params.get("requestId") or "")
    if request_id:
      request_urls[request_id] = str(request.get("url") or "")
  for event in events:
    method = str(event.get("method") or "")
    params = event.get("params") if isinstance(event.get("params"), dict) else {}
    if method == "Runtime.exceptionThrown":
      details = params.get("exceptionDetails") if isinstance(params.get("exceptionDetails"), dict) else {}
      exception = details.get("exception") if isinstance(details.get("exception"), dict) else {}
      console_errors.append(str(exception.get("description") or details.get("text") or "Uncaught exception"))
      stack = format_stack_trace(details.get("stackTrace"))
      if stack:
        stack_traces.append(stack)
    elif method == "Log.entryAdded":
      entry = params.get("entry") if isinstance(params.get("entry"), dict) else {}
      if str(entry.get("level") or "").lower() == "error":
        console_errors.append(str(entry.get("text") or "Browser console error"))
    elif method == "Network.loadingFailed":
      request_id = str(params.get("requestId") or "")
      failed_requests.append(
        {
          "url": request_urls.get(request_id) or request_id,
          "error": str(params.get("errorText") or "Network loading failed"),
          "type": str(params.get("type") or ""),
        }
      )
    elif method == "Network.responseReceived":
      response = params.get("response") if isinstance(params.get("response"), dict) else {}
      status = int(response.get("status") or 0)
      if status >= 400:
        failed_requests.append(
          {
            "url": str(response.get("url") or ""),
            "status": status,
            "error": str(response.get("statusText") or f"HTTP {status}"),
            "type": str(params.get("type") or ""),
          }
        )
  return {
    "console_errors": console_errors,
    "stack_traces": stack_traces,
    "failed_requests": failed_requests,
  }


def format_stack_trace(stack: Any) -> str:
  if not isinstance(stack, dict):
    return ""
  frames = stack.get("callFrames") if isinstance(stack.get("callFrames"), list) else []
  lines = []
  for frame in frames[:12]:
    if not isinstance(frame, dict):
      continue
    lines.append(
      f"{frame.get('functionName') or '<anonymous>'} "
      f"({frame.get('url') or '<inline>'}:{int(frame.get('lineNumber') or 0) + 1}:"
      f"{int(frame.get('columnNumber') or 0) + 1})"
    )
  return "\n".join(lines)


def interaction_failure_reason(
  *,
  blank_page: bool,
  console_errors: list[str],
  stack_traces: list[str],
  failed_requests: list[dict[str, Any]],
) -> str:
  reasons = []
  if blank_page:
    reasons.append("the page became blank after the click")
  if console_errors:
    reasons.append(f"{len(console_errors)} console error(s)")
  if stack_traces:
    reasons.append(f"{len(stack_traces)} JavaScript stack trace(s)")
  if failed_requests:
    reasons.append(f"{len(failed_requests)} failed network request(s)")
  return "Interaction QA detected " + ", ".join(reasons) + "."


def interaction_failure(*, target_url: str, reason: str, selected_control: Any = None) -> dict[str, Any]:
  return {
    "status": "failed",
    "failure_kind": "interaction_probe_failed",
    "reason": reason,
    "target_url": target_url,
    "current_url": target_url,
    "selected_control": selected_control,
    "console_errors": [],
    "stack_traces": [],
    "failed_requests": [],
    "blank_page": False,
  }


def unique_items(items: list[str]) -> list[str]:
  return list(dict.fromkeys(item.strip() for item in items if item and item.strip()))


def unique_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
  seen: set[str] = set()
  result: list[dict[str, Any]] = []
  for item in items:
    key = json.dumps(item, sort_keys=True, default=str)
    if key not in seen:
      seen.add(key)
      result.append(item)
  return result


DIAGNOSTICS_BOOTSTRAP = r"""
(() => {
  const state = window.__worktualInteractionQA = {
    consoleErrors: [], stackTraces: [], failedRequests: []
  };
  window.addEventListener('error', (event) => {
    state.consoleErrors.push(String(event.message || 'Uncaught browser error'));
    if (event.error && event.error.stack) state.stackTraces.push(String(event.error.stack));
  });
  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason;
    state.consoleErrors.push(String((reason && reason.message) || reason || 'Unhandled promise rejection'));
    if (reason && reason.stack) state.stackTraces.push(String(reason.stack));
  });
  const originalError = console.error.bind(console);
  console.error = (...args) => {
    state.consoleErrors.push(args.map(value => {
      try { return typeof value === 'string' ? value : JSON.stringify(value); }
      catch (_) { return String(value); }
    }).join(' '));
    originalError(...args);
  };
  const originalFetch = window.fetch;
  if (originalFetch) {
    window.fetch = async (...args) => {
      try {
        const response = await originalFetch(...args);
        if (!response.ok) state.failedRequests.push({
          url: response.url || String(args[0] || ''),
          status: response.status,
          error: response.statusText || `HTTP ${response.status}`
        });
        return response;
      } catch (error) {
        state.failedRequests.push({
          url: String(args[0] || ''),
          error: String((error && error.message) || error)
        });
        throw error;
      }
    };
  }
})();
"""


CLICK_REQUESTED_CONTROL_SCRIPT = r"""
(prompt) => {
  const stop = new Set([
    'the','a','an','to','for','and','or','in','on','of','this','that','is','are','was','were',
    'button','click','onclick','link','cta','not','working','doesnt','does','do','fix','update',
    'provide','page','website','while','when','after','before','with','mean','then','user'
  ]);
  const terms = String(prompt || '').toLowerCase().replace(/[^a-z0-9\s-]/g, ' ')
    .split(/\s+/).filter(term => term.length > 2 && !stop.has(term));
  const candidates = Array.from(document.querySelectorAll(
    'button, a, [role="button"], input[type="button"], input[type="submit"]'
  )).filter(element => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none'
      && style.visibility !== 'hidden' && !element.disabled;
  });
  const details = candidates.map((element, index) => {
    const label = [
      element.innerText, element.textContent, element.getAttribute('aria-label'),
      element.getAttribute('title'), element.id, element.getAttribute('name')
    ].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim();
    const lowered = label.toLowerCase();
    const score = terms.reduce((sum, term) => sum + (lowered.includes(term) ? 3 : 0), 0)
      + (terms.length && terms.every(term => lowered.includes(term)) ? 5 : 0);
    return { element, index, label, score };
  }).sort((left, right) => right.score - left.score || left.index - right.index);
  const selected = details[0];
  if (!selected || (terms.length && selected.score <= 0)) {
    return {
      clicked: false,
      reason: `No visible control matched: ${terms.join(', ') || prompt}`,
      available_controls: details.slice(0, 12).map(item => item.label)
    };
  }
  const beforeUrl = location.href;
  selected.element.scrollIntoView({ block: 'center', inline: 'center' });
  selected.element.click();
  return {
    clicked: true,
    selected: {
      label: selected.label,
      tag: selected.element.tagName.toLowerCase(),
      before_url: beforeUrl
    }
  };
}
"""


INTERACTION_EVIDENCE_SCRIPT = r"""
(() => {
  const state = window.__worktualInteractionQA || {};
  const body = document.body;
  const root = document.getElementById('root');
  const bodyText = String((body && body.innerText) || '').replace(/\s+/g, ' ').trim();
  const rootText = String((root && root.innerText) || '').replace(/\s+/g, ' ').trim();
  const visibleElements = Array.from(document.querySelectorAll('main,section,article,h1,h2,p,button,a'))
    .filter(element => {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.display !== 'none'
        && style.visibility !== 'hidden' && Number(style.opacity || 1) > 0.05;
    }).length;
  return {
    current_url: location.href,
    console_errors: state.consoleErrors || [],
    stack_traces: state.stackTraces || [],
    failed_requests: state.failedRequests || [],
    blank_page: !body || (bodyText.length < 2 && rootText.length < 2 && visibleElements === 0)
  };
})()
"""
