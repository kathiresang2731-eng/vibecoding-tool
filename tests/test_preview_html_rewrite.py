from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_previews_module():
  module_path = Path(__file__).resolve().parents[1] / "backend" / "api" / "previews.py"
  spec = importlib.util.spec_from_file_location("worktual_previews", module_path)
  module = importlib.util.module_from_spec(spec)
  assert spec and spec.loader
  spec.loader.exec_module(module)
  return module


previews = _load_previews_module()
preview_base_path = previews.preview_base_path
rewrite_preview_html = previews.rewrite_preview_html


def test_preview_base_path_includes_project_and_version() -> None:
  assert preview_base_path("proj-1", "ver-2") == "/api/previews/proj-1/ver-2/"


def test_rewrite_preview_html_injects_unique_base_href() -> None:
  html = "<!doctype html><html><head></head><body><div id='root'></div></body></html>"
  updated = rewrite_preview_html(html, project_id="5d8d8d0f-23c9-47d0-bbe7-7d27be35fa2d", version_id="abc-version-123")

  assert '<base href="/api/previews/5d8d8d0f-23c9-47d0-bbe7-7d27be35fa2d/abc-version-123/">' in updated
  assert '__WORKTUAL_PREVIEW_NAV_GUARD__' in updated
  assert '__WORKTUAL_PREVIEW_IDS__' in updated
  assert 'patchHistoryMethod("pushState")' in updated
  assert 'patchLocationMethods' in updated
  assert 'installLocationPathnamePatch' in updated
  assert 'installAnchorHrefObserver' in updated
  assert 'worktual_active_preview_base' in updated


def test_rewrite_preview_html_rewrites_absolute_route_links() -> None:
  html = "<!doctype html><html><head></head><body><a href='/analytics'>Analytics</a></body></html>"
  updated = rewrite_preview_html(html, project_id="proj", version_id="ver")

  assert "rewriteNavigationUrl" in updated
  assert "/api/previews/" in updated


def test_rewrite_preview_html_rewrites_asset_paths() -> None:
  html = '<html><head></head><body><script src="/assets/index.js"></script></body></html>'
  updated = rewrite_preview_html(html, project_id="p1", version_id="v1")

  assert 'src="./assets/index.js"' in updated
