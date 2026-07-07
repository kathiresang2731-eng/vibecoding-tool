from backend.agents.project_workspace import is_scaffold_only_codebase
from backend.agents.streaming.syntax_guard import guard_syntax_write, syntax_issues_for_content
from backend.agents.streaming.task_planner import plan_file_work


def test_syntax_guard_blocks_unbalanced_braces():
  blocked = guard_syntax_write("src/pages/Home.jsx", "export default function Home() { return <div>;\n")
  assert blocked is not None
  assert blocked.get("syntax_blocked") is True


def test_syntax_guard_allows_valid_component():
  code = "export default function Home() {\n  return <div>ok</div>;\n}\n"
  assert guard_syntax_write("src/pages/Home.jsx", code) is None


def test_scaffold_only_codebase_detects_vite_without_pages():
  files = [
    {"path": "package.json", "content": '{"name":"demo","dependencies":{"react":"^18.0.0","vite":"^5.0.0"}}'},
    {
      "path": "index.html",
      "content": '<!doctype html><html><head><title>x</title></head><body><div id="root"></div><script type="module" src="/src/main.jsx"></script></body></html>',
    },
    {"path": "vite.config.js", "content": "import { defineConfig } from 'vite'\nexport default defineConfig({ plugins: [] })\n"},
    {"path": "tailwind.config.js", "content": "export default { content: ['./index.html', './src/**/*.{js,jsx}'] }\n"},
    {"path": "postcss.config.js", "content": "export default { plugins: { tailwindcss: {}, autoprefixer: {} } }\n"},
    {"path": "src/main.jsx", "content": "import React from 'react'\nimport { createRoot } from 'react-dom/client'\ncreateRoot(document.getElementById('root')).render(<App />)\n"},
    {"path": "src/index.css", "content": "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n" + ("x" * 90)},
    {"path": "src/App.jsx", "content": "import React from 'react'\nexport default function App() {\n  return <div className='app'>placeholder shell</div>\n}\n"},
  ]
  assert is_scaffold_only_codebase(files) is True


def test_website_generation_on_scaffold_uses_parallel_greenfield_plan():
  files = [
    {"path": "package.json", "content": '{"name":"demo","dependencies":{"react":"^18.0.0"}}'},
    {"path": "index.html", "content": "<!doctype html><html><head><title>x</title></head><body><div id=root></div></body></html>"},
    {"path": "vite.config.js", "content": "export default { plugins: [] }"},
    {"path": "tailwind.config.js", "content": "export default { content: ['./index.html', './src/**/*.{js,jsx}'] }"},
    {"path": "postcss.config.js", "content": "export default { plugins: { tailwindcss: {}, autoprefixer: {} } }"},
    {"path": "src/main.jsx", "content": "import React from 'react'"},
    {"path": "src/index.css", "content": "@tailwind base;"},
    {"path": "src/App.jsx", "content": "export default function App(){return null}"},
  ]
  plan = plan_file_work(
    "Build AI CCaaS with auth onboarding dashboard copilot channels settings",
    intent="website_generation",
    project_files=files,
  )
  assert plan.get("greenfield") is True
  assert plan.get("use_parallel_workers") is True
  assert plan.get("task_count", 0) >= 2
