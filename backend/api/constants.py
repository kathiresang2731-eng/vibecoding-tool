from __future__ import annotations

HOST = "0.0.0.0"
PORT = 8787
PREVIEW_RESPONSE_HEADERS = {"Cache-Control": "no-store"}
GENERATION_STREAM_HEARTBEAT_SECONDS = 2.0
FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="12" fill="#111827"/><path fill="#fff" d="M16 18h8l5 22 5-22h7l5 22 5-22h7L50 46h-8l-5-20-5 20h-7z"/></svg>"""
SUPPORTED_GENERATION_MODELS = {
  "gemini-3.1-pro-preview",
  "gemini-3.5-flash",
}
