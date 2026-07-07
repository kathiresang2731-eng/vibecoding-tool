from __future__ import annotations

import base64
import json
import os
import socket
import struct
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from .constants import BROWSER_QA_TIMEOUT_SECONDS
from .layout import DEFAULT_LAYOUT_VIEWPORTS, analyze_layout_snapshot, layout_severity
from .types import BrowserCommand


LAYOUT_PROBE_TIMEOUT_SECONDS = min(8, BROWSER_QA_TIMEOUT_SECONDS)


def run_browser_layout_qa(
  *,
  browser_command: BrowserCommand,
  target_url: str,
  profile_root: Path,
) -> dict[str, Any]:
  viewport_results: list[dict[str, Any]] = []
  warnings: list[str] = []

  for viewport in DEFAULT_LAYOUT_VIEWPORTS:
    snapshot_result = collect_layout_snapshot(
      browser_command=browser_command,
      target_url=target_url,
      viewport=viewport,
      profile_path=profile_root / f"layout-{viewport['name']}",
    )
    if snapshot_result.get("status") != "passed":
      reason = str(snapshot_result.get("reason") or "Layout probe was skipped.")
      viewport_results.append(
        {
          "name": viewport["name"],
          "width": viewport["width"],
          "height": viewport["height"],
          "status": "skipped",
          "severity": "unknown",
          "reason": reason,
          "issues": [],
        }
      )
      warnings.append(f"{viewport['name']} layout QA skipped: {reason}")
      continue
    analysis = analyze_layout_snapshot(snapshot_result.get("snapshot") or {}, viewport=viewport)
    viewport_results.append(analysis)

  checked_results = [
    item
    for item in viewport_results
    if item.get("status") in {"passed", "failed"} and item.get("severity") != "unknown"
  ]
  layout_checked = bool(checked_results)
  layout_issues = flatten_layout_issues(checked_results)
  severity = layout_severity(layout_issues) if layout_checked else "none"
  return {
    "status": "failed" if severity == "high" else "passed" if layout_checked else "skipped",
    "layout_checked": layout_checked,
    "viewport_results": viewport_results,
    "layout_issues": layout_issues,
    "severity": severity,
    "warnings": warnings,
  }


def collect_layout_snapshot(
  *,
  browser_command: BrowserCommand,
  target_url: str,
  viewport: dict[str, Any],
  profile_path: Path,
) -> dict[str, Any]:
  port = available_local_port()
  width = int(viewport.get("width") or 390)
  height = int(viewport.get("height") or 844)
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
    "--force-device-scale-factor=1",
    "--remote-allow-origins=*",
    f"--remote-debugging-port={port}",
    f"--user-data-dir={profile_path}",
    f"--window-size={width},{height}",
    target_url,
  ]
  process: subprocess.Popen[str] | None = None
  try:
    process = subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    endpoint = wait_for_cdp_endpoint(port, process, timeout_seconds=LAYOUT_PROBE_TIMEOUT_SECONDS)
    if not endpoint.get("webSocketDebuggerUrl"):
      return {"status": "skipped", "reason": endpoint.get("reason") or "DevTools endpoint was unavailable."}
    with DevToolsClient(str(endpoint["webSocketDebuggerUrl"]), timeout=LAYOUT_PROBE_TIMEOUT_SECONDS) as client:
      snapshot = evaluate_layout_snapshot(client)
    return {"status": "passed", "snapshot": snapshot}
  except Exception as exc:
    return {"status": "skipped", "reason": f"Layout probe failed: {exc}"}
  finally:
    if process is not None:
      stop_process(process)


def available_local_port() -> int:
  with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
    probe.bind(("127.0.0.1", 0))
    return int(probe.getsockname()[1])


def wait_for_cdp_endpoint(port: int, process: subprocess.Popen[str], *, timeout_seconds: float) -> dict[str, Any]:
  deadline = time.monotonic() + timeout_seconds
  endpoint_url = f"http://127.0.0.1:{port}/json/list"
  last_error = ""
  while time.monotonic() < deadline:
    if process.poll() is not None:
      output = read_process_output(process)
      return {
        "reason": f"Browser exited before DevTools endpoint was available.{(' ' + output[:500]) if output else ''}"
      }
    try:
      with urlopen(endpoint_url, timeout=0.5) as response:
        targets = json.loads(response.read().decode("utf-8"))
      for target in targets:
        if isinstance(target, dict) and target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
          return target
    except (OSError, URLError, json.JSONDecodeError) as exc:
      last_error = str(exc)
    time.sleep(0.1)
  return {"reason": f"Timed out waiting for DevTools endpoint.{(' ' + last_error) if last_error else ''}"}


def read_process_output(process: subprocess.Popen[str]) -> str:
  try:
    stdout, stderr = process.communicate(timeout=0.2)
  except Exception:
    return ""
  return "\n".join(part for part in (stdout, stderr) if part).strip()


def stop_process(process: subprocess.Popen[str]) -> None:
  if process.poll() is not None:
    return
  process.terminate()
  try:
    process.wait(timeout=2)
  except subprocess.TimeoutExpired:
    process.kill()
    process.wait(timeout=2)


def evaluate_layout_snapshot(client: "DevToolsClient") -> dict[str, Any]:
  client.call("Runtime.enable")
  response = client.call(
    "Runtime.evaluate",
    {
      "expression": LAYOUT_COLLECTION_SCRIPT,
      "awaitPromise": True,
      "returnByValue": True,
    },
  )
  if response.get("exceptionDetails"):
    raise RuntimeError("Layout script raised an exception.")
  result = response.get("result") if isinstance(response.get("result"), dict) else {}
  value = result.get("value") if isinstance(result.get("value"), dict) else None
  if not isinstance(value, dict):
    raise RuntimeError("Layout script did not return a snapshot object.")
  return value


def flatten_layout_issues(viewport_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
  issues: list[dict[str, Any]] = []
  for result in viewport_results:
    viewport_name = str(result.get("name") or "")
    width = result.get("width")
    height = result.get("height")
    for issue in result.get("issues", []):
      if not isinstance(issue, dict):
        continue
      issues.append(
        {
          **issue,
          "viewport": viewport_name,
          "viewport_width": width,
          "viewport_height": height,
        }
      )
  return issues


class DevToolsClient:
  def __init__(self, websocket_url: str, *, timeout: float) -> None:
    self.websocket_url = websocket_url
    self.timeout = timeout
    self.socket: socket.socket | None = None
    self.message_id = 0
    self.events: list[dict[str, Any]] = []

  def __enter__(self) -> "DevToolsClient":
    parsed = urlparse(self.websocket_url)
    if parsed.scheme != "ws":
      raise RuntimeError(f"Unsupported DevTools websocket scheme: {parsed.scheme}")
    port = parsed.port or 80
    sock = socket.create_connection((parsed.hostname or "127.0.0.1", port), timeout=self.timeout)
    sock.settimeout(self.timeout)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    path = parsed.path or "/"
    if parsed.query:
      path = f"{path}?{parsed.query}"
    request = (
      f"GET {path} HTTP/1.1\r\n"
      f"Host: {parsed.hostname}:{port}\r\n"
      "Upgrade: websocket\r\n"
      "Connection: Upgrade\r\n"
      f"Sec-WebSocket-Key: {key}\r\n"
      "Sec-WebSocket-Version: 13\r\n"
      "\r\n"
    )
    sock.sendall(request.encode("ascii"))
    response = receive_http_headers(sock)
    if " 101 " not in response.split("\r\n", 1)[0]:
      raise RuntimeError(f"DevTools websocket upgrade failed: {response.splitlines()[0] if response else 'no response'}")
    self.socket = sock
    return self

  def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
    if self.socket is not None:
      try:
        self.socket.close()
      finally:
        self.socket = None

  def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    self.message_id += 1
    message = {"id": self.message_id, "method": method}
    if params is not None:
      message["params"] = params
    self.send_json(message)
    while True:
      payload = self.receive_text()
      if not payload:
        raise RuntimeError("DevTools websocket closed.")
      response = json.loads(payload)
      if response.get("id") != self.message_id:
        if response.get("method"):
          self.events.append(response)
        continue
      if response.get("error"):
        raise RuntimeError(str(response["error"]))
      return response

  def pop_events(self) -> list[dict[str, Any]]:
    events = list(self.events)
    self.events.clear()
    return events

  def send_json(self, message: dict[str, Any]) -> None:
    if self.socket is None:
      raise RuntimeError("DevTools websocket is not connected.")
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    self.socket.sendall(encode_client_frame(payload))

  def receive_text(self) -> str:
    if self.socket is None:
      raise RuntimeError("DevTools websocket is not connected.")
    while True:
      opcode, payload = read_server_frame(self.socket)
      if opcode == 0x8:
        return ""
      if opcode == 0x9:
        self.socket.sendall(encode_client_frame(payload, opcode=0xA))
        continue
      if opcode in {0x1, 0x0}:
        return payload.decode("utf-8")


def receive_http_headers(sock: socket.socket) -> str:
  chunks: list[bytes] = []
  data = b""
  while b"\r\n\r\n" not in data:
    chunk = sock.recv(4096)
    if not chunk:
      break
    chunks.append(chunk)
    data = b"".join(chunks)
  return data.decode("iso-8859-1", errors="replace")


def encode_client_frame(payload: bytes, *, opcode: int = 0x1) -> bytes:
  length = len(payload)
  first = 0x80 | opcode
  mask_bit = 0x80
  if length < 126:
    header = bytes([first, mask_bit | length])
  elif length <= 0xFFFF:
    header = bytes([first, mask_bit | 126]) + struct.pack(">H", length)
  else:
    header = bytes([first, mask_bit | 127]) + struct.pack(">Q", length)
  mask = os.urandom(4)
  masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
  return header + mask + masked


def read_server_frame(sock: socket.socket) -> tuple[int, bytes]:
  header = recv_exact(sock, 2)
  first, second = header[0], header[1]
  opcode = first & 0x0F
  masked = bool(second & 0x80)
  length = second & 0x7F
  if length == 126:
    length = struct.unpack(">H", recv_exact(sock, 2))[0]
  elif length == 127:
    length = struct.unpack(">Q", recv_exact(sock, 8))[0]
  mask = recv_exact(sock, 4) if masked else b""
  payload = recv_exact(sock, length) if length else b""
  if masked:
    payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
  return opcode, payload


def recv_exact(sock: socket.socket, length: int) -> bytes:
  chunks: list[bytes] = []
  remaining = length
  while remaining > 0:
    chunk = sock.recv(remaining)
    if not chunk:
      raise RuntimeError("Unexpected websocket EOF.")
    chunks.append(chunk)
    remaining -= len(chunk)
  return b"".join(chunks)


LAYOUT_COLLECTION_SCRIPT = r"""
new Promise((resolve) => {
  let resolved = false;
  const finish = () => {
    if (resolved) return;
    resolved = true;
    requestAnimationFrame(() => {
      setTimeout(() => {
        const selector = [
          'main',
          'section',
          'article',
          'header',
          'footer',
          'nav',
          'button',
          'a',
          'input',
          'textarea',
          'select',
          '[role="button"]',
          '[class*="card" i]',
          '[class*="panel" i]',
          '[class*="modal" i]',
          '[class*="drawer" i]',
          '[class*="hero" i]',
          'h1',
          'h2',
          'h3',
          'p'
        ].join(',');
        const elementSelector = (element) => {
          const tag = element.tagName.toLowerCase();
          if (element.id) return `${tag}#${element.id}`;
          const classes = Array.from(element.classList || []).slice(0, 3).join('.');
          if (classes) return `${tag}.${classes}`;
          const role = element.getAttribute('role');
          if (role) return `${tag}[role="${role}"]`;
          return tag;
        };
        const elements = Array.from(document.querySelectorAll(selector)).slice(0, 450).map((element) => {
          const rect = element.getBoundingClientRect();
          const style = window.getComputedStyle(element);
          const text = (element.innerText || element.textContent || '').replace(/\s+/g, ' ').trim();
          const visible = style.display !== 'none'
            && style.visibility !== 'hidden'
            && Number(style.opacity || '1') > 0.05
            && rect.width > 0
            && rect.height > 0;
          return {
            selector: elementSelector(element),
            tag: element.tagName.toLowerCase(),
            text,
            left: rect.left,
            top: rect.top,
            width: rect.width,
            height: rect.height,
            visible,
            scroll_width: element.scrollWidth,
            client_width: element.clientWidth,
            scroll_height: element.scrollHeight,
            client_height: element.clientHeight
          };
        });
        const root = document.documentElement;
        const body = document.body || root;
        resolve({
          viewport_width: window.innerWidth,
          viewport_height: window.innerHeight,
          scroll_width: Math.max(root.scrollWidth || 0, body.scrollWidth || 0),
          scroll_height: Math.max(root.scrollHeight || 0, body.scrollHeight || 0),
          elements
        });
      }, 250);
    });
  };
  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    finish();
  } else {
    window.addEventListener('load', finish, { once: true });
    setTimeout(finish, 2500);
  }
})
"""
