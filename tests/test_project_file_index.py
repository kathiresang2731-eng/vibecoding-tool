from backend.agents.agent_runtime.targeted_updates import build_project_file_keyword_index


def test_project_file_index_tracks_dependencies_routes_symbols_and_hashes():
  index = build_project_file_keyword_index(
    [
      {
        "path": "src/App.jsx",
        "content": (
          'import Auth from "./pages/Auth";\n'
          'import "./index.css";\n'
          'export default function App() {\n'
          '  return <Route path="/login" element={<Auth className="auth-shell" />} />;\n'
          "}\n"
        ),
        "last_changed_run_id": "run-1",
      }
    ]
  )

  assert len(index) == 1
  item = index[0]
  assert item["content_hash"]
  assert "./pages/Auth" in item["imports"]
  assert "./index.css" in item["imports"]
  assert "/login" in item["routes"]
  assert "App" in item["symbols"]
  assert "App" in item["components"]
  assert "auth-shell" in item["css_references"]
  assert item["last_changed_run_id"] == "run-1"
