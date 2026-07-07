from backend.runtime import resolve_node_binary, scan_built_preview_runtime


def test_preview_runtime_scan_does_not_block_on_bundled_react_reference(tmp_path):
  assets = tmp_path / "assets"
  assets.mkdir()
  (assets / "index-bad.js").write_text(
    'function App(){return React.createElement("main",null,"Broken");}',
    encoding="utf-8",
  )

  assert scan_built_preview_runtime(tmp_path) == []


def test_preview_runtime_scan_allows_minified_local_react_alias(tmp_path):
  assets = tmp_path / "assets"
  assets.mkdir()
  (assets / "index-ok.js").write_text(
    'const R={createElement(){}};function App(){return R.createElement("main",null,"OK");}',
    encoding="utf-8",
  )

  assert scan_built_preview_runtime(tmp_path) == []


def test_resolve_node_binary_prefers_configured_binary(monkeypatch, tmp_path):
  node = tmp_path / "node"
  node.write_text("#!/bin/sh\n", encoding="utf-8")
  node.chmod(0o755)
  monkeypatch.setenv("VITE_NODE_BINARY", str(node))

  assert resolve_node_binary() == str(node)
