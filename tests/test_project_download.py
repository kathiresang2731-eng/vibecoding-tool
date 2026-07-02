from __future__ import annotations

import importlib.util
import io
import zipfile
from pathlib import Path


def _load_project_download_module():
  module_path = Path(__file__).resolve().parents[1] / "backend" / "api" / "project_download.py"
  spec = importlib.util.spec_from_file_location("worktual_project_download", module_path)
  module = importlib.util.module_from_spec(spec)
  assert spec and spec.loader
  spec.loader.exec_module(module)
  return module


project_download = _load_project_download_module()
build_project_zip = project_download.build_project_zip
safe_download_filename = project_download.safe_download_filename


def test_build_project_zip_contains_project_files() -> None:
  files = [
    {"path": "package.json", "content": '{"name":"demo"}'},
    {"path": "src/App.jsx", "content": "export default function App(){ return null; }"},
  ]
  archive_bytes = build_project_zip(files, project_name="Demo")
  with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
    names = set(archive.namelist())
    package_json = archive.read("package.json").decode("utf-8")
  assert names == {"package.json", "src/App.jsx"}
  assert '"name":"demo"' in package_json


def test_safe_download_filename() -> None:
  assert safe_download_filename("Ai Native Farm") == "Ai-Native-Farm"
