from backend.agents.streaming.update_write_guard import (
  compute_change_fraction,
  filter_streaming_write_payload,
  guard_streaming_file_write,
  is_new_project_path,
)


def test_is_new_project_path_treats_empty_as_new():
  assert is_new_project_path("src/pages/Home.jsx", "")
  assert is_new_project_path("src/pages/Home.jsx", "   ")
  assert not is_new_project_path("src/pages/Home.jsx", "export default function Home() {}")


def test_guard_blocks_large_rewrite_of_existing_file():
  previous = "\n".join(f"line {index}" for index in range(40))
  candidate = "export default function Home() {\n  return <div>Rewritten</div>;\n}\n"
  blocked = guard_streaming_file_write(
    "src/pages/Home.jsx",
    candidate,
    previous,
    prompt="fix the header alignment",
  )
  assert blocked is not None
  assert blocked.get("blocked_rewrite") is True


def test_guard_allows_new_file_write():
  blocked = guard_streaming_file_write(
    "src/pages/NewPage.jsx",
    "export default function NewPage() { return null; }",
    "",
    prompt="add a page",
  )
  assert blocked is None


def test_filter_write_payload_keeps_small_edits_drops_rewrites():
  previous = "\n".join(f"const value{index} = {index};" for index in range(80))
  files_before = {"src/App.jsx": previous}
  write_payload = [
    {"path": "src/App.jsx", "content": "export default function App() { return <main>ok</main>; }"},
    {"path": "src/pages/New.jsx", "content": "export default function New() { return null; }"},
  ]
  accepted, rejected = filter_streaming_write_payload(files_before, write_payload, prompt="fix bug")
  assert len(rejected) == 1
  assert rejected[0]["path"] == "src/App.jsx"
  assert len(accepted) == 1
  assert accepted[0]["path"] == "src/pages/New.jsx"


def test_compute_change_fraction_near_zero_for_tiny_edit():
  previous = "export default function App() {\n  return <div>Hello</div>;\n}\n"
  candidate = "export default function App() {\n  return <div>Hello world</div>;\n}\n"
  fraction = compute_change_fraction("src/App.jsx", previous, candidate)
  assert fraction < 0.45
