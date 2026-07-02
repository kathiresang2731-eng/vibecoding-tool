from __future__ import annotations

import json
import posixpath
import re
from typing import Any

from .constants import TAILWIND_CLASS_RE, TAILWIND_DIRECTIVES
from .values import text_or_default

ROUTER_SHIM_PATH = "src/worktual-router-shim.jsx"
FRAMER_MOTION_SHIM_PATH = "src/worktual-framer-motion-shim.jsx"
CLSX_SHIM_PATH = "src/worktual-clsx-shim.js"
TAILWIND_MERGE_SHIM_PATH = "src/worktual-tailwind-merge-shim.js"
RECHARTS_SHIM_PATH = "src/worktual-recharts-shim.jsx"
RUNTIME_IMPORT_SHIM_PATHS = {
  "react-router-dom": ROUTER_SHIM_PATH,
  "framer-motion": FRAMER_MOTION_SHIM_PATH,
  "clsx": CLSX_SHIM_PATH,
  "tailwind-merge": TAILWIND_MERGE_SHIM_PATH,
  "recharts": RECHARTS_SHIM_PATH,
}
VITE_SCAFFOLD_PATHS = frozenset(
  {
    "package.json",
    "index.html",
    "vite.config.js",
    "vite.config.mjs",
    "vite.config.ts",
    "vite.config.cjs",
    "tailwind.config.js",
    "tailwind.config.mjs",
    "tailwind.config.cjs",
    "postcss.config.js",
    "postcss.config.mjs",
    "postcss.config.cjs",
    "src/main.jsx",
    "src/main.tsx",
    "src/index.css",
    "src/App.jsx",
    "src/App.tsx",
  }
)
DEFAULT_WEBSITE_FONT_FAMILY = '"Times New Roman", Times, serif'
DEFAULT_WEBSITE_BODY_FONT_RULE = f"body {{ font-family: {DEFAULT_WEBSITE_FONT_FAMILY}; }}"
DEFAULT_WEBSITE_TAILWIND_FONT_EXTEND = (
  "fontFamily: { sans: ['\"Times New Roman\"', 'Times', 'serif'], serif: ['\"Times New Roman\"', 'Times', 'serif'] }"
)
DEFAULT_APP_SHELL_MARKERS = (
  "Your site is being generated",
  "Page modules will replace this shell.",
)


def is_default_app_shell_content(content: str) -> bool:
  stripped = text_or_default(content, "").strip()
  return bool(stripped) and all(marker in stripped for marker in DEFAULT_APP_SHELL_MARKERS)


def _page_component_name(path: str) -> str:
  filename = posixpath.basename(text_or_default(path, ""))
  stem = filename.rsplit(".", 1)[0]
  return stem if stem else "Page"


def _page_route_path(path: str) -> str:
  name = _page_component_name(path)
  lowered = name.lower()
  if lowered in {"home", "index", "landing"}:
    return "/"
  slug = re.sub(r"(?<!^)(?=[A-Z])", "-", name).replace("_", "-").lower()
  slug = re.sub(r"[^a-z0-9-]+", "-", slug).strip("-")
  return f"/{slug or lowered}"


def _generated_page_paths(files_by_path: dict[str, str]) -> list[str]:
  page_paths = [
    path
    for path, content in files_by_path.items()
    if path.startswith("src/pages/") and path.endswith((".js", ".jsx", ".ts", ".tsx")) and text_or_default(content, "").strip()
  ]
  return sorted(dict.fromkeys(page_paths))


def _default_landing_route(page_paths: list[str]) -> str:
  if not page_paths:
    return "/"
  route_by_name = {_page_component_name(path).lower(): _page_route_path(path) for path in page_paths}
  for preferred in ("home", "index", "landing", "dashboard", "auth", "onboarding"):
    route = route_by_name.get(preferred)
    if route:
      return route
  return _page_route_path(page_paths[0])


def generated_page_app_shell(files_by_path: dict[str, str]) -> str | None:
  page_paths = _generated_page_paths(files_by_path)
  if not page_paths:
    return None

  imports = [
    'import React from "react";',
    'import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";',
  ]
  route_entries: list[tuple[str, str]] = []
  seen_names: set[str] = set()
  seen_routes: set[str] = set()
  for path in page_paths:
    name = _page_component_name(path)
    route_path = _page_route_path(path)
    if name in seen_names or route_path in seen_routes:
      continue
    seen_names.add(name)
    seen_routes.add(route_path)
    imports.append(f'import {name} from "./pages/{posixpath.basename(path)}";')
    route_entries.append((route_path, name))

  landing_route = _default_landing_route(page_paths)
  route_lines = []
  if landing_route != "/":
    route_lines.append(f'        <Route path="/" element={{<Navigate to="{landing_route}" replace />}} />')
  for route_path, name in route_entries:
    route_lines.append(f'        <Route path="{route_path}" element={{<{name} />}} />')
  if landing_route != "/":
    route_lines.append(f'        <Route path="*" element={{<Navigate to="{landing_route}" replace />}} />')

  joined_routes = "\n".join(route_lines)
  return (
    f'{"\n".join(imports)}\n\n'
    "export default function App() {\n"
    "  return (\n"
    "    <BrowserRouter>\n"
    "      <Routes>\n"
    f"{joined_routes}\n"
    "      </Routes>\n"
    "    </BrowserRouter>\n"
    "  );\n"
    "}\n"
  )


def is_valid_scaffold_file_content(path: str, content: str) -> bool:
  normalized_path = text_or_default(path, "").strip().replace("\\", "/")
  stripped = text_or_default(content, "").strip()
  if not stripped:
    return False
  if normalized_path == "package.json":
    try:
      payload = json.loads(stripped)
    except json.JSONDecodeError:
      return False
    if not isinstance(payload, dict):
      return False
    scripts = payload.get("scripts")
    if isinstance(scripts, dict) and isinstance(scripts.get("build"), str) and "vite" in scripts.get("build", "").lower():
      return True
    dependencies = payload.get("dependencies")
    return isinstance(dependencies, dict) and bool(dependencies.get("react") or dependencies.get("vite"))
  if normalized_path == "index.html":
    lowered = stripped.lower()
    return ('id="root"' in lowered or "id='root'" in lowered) and (
      "src/main.jsx" in lowered or "src/main.tsx" in lowered or 'type="module"' in lowered
    )
  if normalized_path.startswith("vite.config"):
    return "defineconfig" in stripped.lower() or "export default" in stripped
  if normalized_path in {"src/main.jsx", "src/main.tsx"}:
    lowered = stripped.lower()
    return "createroot" in lowered or "reactdom.render" in lowered or ".render(" in lowered
  if normalized_path in {"src/App.jsx", "src/App.tsx"}:
    return "export default" in stripped and len(stripped) > 40
  if normalized_path == "src/index.css":
    return "@tailwind" in stripped or len(stripped) > 80
  if normalized_path.startswith("tailwind.config") or normalized_path.startswith("postcss.config"):
    return "module.exports" in stripped or "export default" in stripped
  return True


def ensure_vite_scaffold_files(
  files: list[dict[str, Any]],
  *,
  title: str = "Generated Website",
) -> tuple[list[dict[str, str]], list[str]]:
  merged_by_path: dict[str, str] = {}
  ordered_paths: list[str] = []
  for file_item in files:
    if not isinstance(file_item, dict):
      continue
    path = text_or_default(file_item.get("path"), "")
    content = file_item.get("content")
    if content is None:
      content = file_item.get("code")
    if not path or not isinstance(content, str):
      continue
    if path not in merged_by_path:
      ordered_paths.append(path)
    merged_by_path[path] = content

  package_needs_scaffold = "package.json" not in merged_by_path or not is_valid_scaffold_file_content("package.json", merged_by_path.get("package.json", ""))
  existing_vite_config_paths = [path for path in merged_by_path if path.startswith("vite.config")]
  vite_config_needs_scaffold = any(
    not is_valid_scaffold_file_content(path, merged_by_path.get(path, ""))
    for path in existing_vite_config_paths
  )
  include_default_vite_config = package_needs_scaffold or vite_config_needs_scaffold
  generated_app_content = generated_page_app_shell(merged_by_path)

  touched_paths: list[str] = []
  for scaffold_file in default_vite_scaffold_files(title=title):
    path = scaffold_file["path"]
    if path == "vite.config.js" and path not in merged_by_path and not include_default_vite_config:
      continue
    content = generated_app_content if path == "src/App.jsx" and generated_app_content else scaffold_file["content"]
    existing = merged_by_path.get(path, "")
    should_replace_placeholder = path == "src/App.jsx" and bool(generated_app_content) and is_default_app_shell_content(existing)
    if path not in merged_by_path or not is_valid_scaffold_file_content(path, existing) or should_replace_placeholder:
      if merged_by_path.get(path) != content:
        merged_by_path[path] = content
        touched_paths.append(path)
      if path not in ordered_paths:
        ordered_paths.append(path)

  return [{"path": path, "content": merged_by_path[path]} for path in ordered_paths], touched_paths


def default_vite_scaffold_files(*, title: str) -> list[dict[str, str]]:
  safe_title = text_or_default(title, "Generated Website")
  return [
    {
      "path": "package.json",
      "content": json.dumps(
        {
          "scripts": {"build": "vite --host 0.0.0.0", "dev": "vite --host 0.0.0.0"},
          "dependencies": {
            "@vitejs/plugin-react": "latest",
            "vite": "latest",
            "react": "latest",
            "react-dom": "latest",
            "lucide-react": "latest",
          },
          "devDependencies": {
            "tailwindcss": "^3.4.17",
            "postcss": "^8.5.0",
            "autoprefixer": "^10.4.20",
          },
        },
        indent=2,
      ),
    },
    {
      "path": "index.html",
      "content": (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "  <head>\n"
        '    <meta charset="UTF-8" />\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
        f"    <title>{html_escape_text(safe_title)}</title>\n"
        "  </head>\n"
        "  <body>\n"
        '    <div id="root"></div>\n'
        '    <script type="module" src="/src/main.jsx"></script>\n'
        "  </body>\n"
        "</html>\n"
      ),
    },
    {
      "path": "src/main.jsx",
      "content": (
        'import React from "react";\n'
        'import { createRoot } from "react-dom/client";\n'
        'import App from "./App.jsx";\n'
        'import "./index.css";\n\n'
        'createRoot(document.getElementById("root")).render(<App />);\n'
      ),
    },
    {
      "path": "src/index.css",
      "content": (
        f"{TAILWIND_DIRECTIVES}\n\n"
        "* { box-sizing: border-box; }\n"
        "html { scroll-behavior: smooth; }\n"
        f"body {{ margin: 0; min-width: 320px; font-family: {DEFAULT_WEBSITE_FONT_FAMILY}; }}\n"
      ),
    },
    {
      "path": "tailwind.config.js",
      "content": default_tailwind_config(),
    },
    {
      "path": "postcss.config.js",
      "content": default_postcss_config(),
    },
    {
      "path": "vite.config.js",
      "content": default_vite_config(),
    },
    {
      "path": "src/App.jsx",
      "content": default_app_shell(),
    },
  ]


def default_vite_config() -> str:
  return (
    'import { defineConfig } from "vite";\n'
    'import react from "@vitejs/plugin-react";\n\n'
    "export default defineConfig({\n"
    '  base: "./",\n'
    "  plugins: [react()],\n"
    "});\n"
  )


def default_app_shell() -> str:
  return (
    'import React from "react";\n\n'
    "export default function App() {\n"
    "  return (\n"
    '    <main className="min-h-screen bg-slate-950 text-white">\n'
    '      <div className="mx-auto max-w-5xl px-6 py-16">\n'
    "        <h1 className=\"text-3xl font-semibold\">Your site is being generated</h1>\n"
    "        <p className=\"mt-3 text-slate-300\">Page modules will replace this shell.</p>\n"
    "      </div>\n"
    "    </main>\n"
    "  );\n"
    "}\n"
  )


def ensure_tailwind_runtime_files(files: list[dict[str, Any]]) -> tuple[list[dict[str, str]], list[str]]:
  normalized_files: list[dict[str, str]] = []
  merged_by_path: dict[str, str] = {}
  ordered_paths: list[str] = []
  for file_item in files:
    if not isinstance(file_item, dict):
      continue
    path = text_or_default(file_item.get("path"), "")
    content = file_item.get("content")
    if content is None:
      content = file_item.get("code")
    if not path or not isinstance(content, str):
      continue
    if path not in merged_by_path:
      ordered_paths.append(path)
    merged_by_path[path] = content

  if not generated_sources_use_tailwind(merged_by_path):
    return [{"path": path, "content": merged_by_path[path]} for path in ordered_paths], []

  changed_paths: list[str] = []
  package_content = ensure_tailwind_package_dependencies(merged_by_path.get("package.json", ""))
  if merged_by_path.get("package.json") != package_content:
    if "package.json" not in merged_by_path:
      ordered_paths.append("package.json")
    merged_by_path["package.json"] = package_content
    changed_paths.append("package.json")

  index_css = ensure_tailwind_css_directives(merged_by_path.get("src/index.css", ""))
  index_css = ensure_website_font_in_index_css(index_css)
  if merged_by_path.get("src/index.css") != index_css:
    if "src/index.css" not in merged_by_path:
      ordered_paths.append("src/index.css")
    merged_by_path["src/index.css"] = index_css
    changed_paths.append("src/index.css")

  for path, content in {
    "tailwind.config.js": default_tailwind_config(),
    "postcss.config.js": default_postcss_config(),
  }.items():
    if path not in merged_by_path:
      merged_by_path[path] = content
      ordered_paths.append(path)
      changed_paths.append(path)
    elif path == "tailwind.config.js":
      patched = ensure_website_font_in_tailwind_config(merged_by_path[path])
      if patched != merged_by_path[path]:
        merged_by_path[path] = patched
        if path not in changed_paths:
          changed_paths.append(path)

  normalized_files = [{"path": path, "content": merged_by_path[path]} for path in ordered_paths]
  return normalized_files, changed_paths


def normalize_frontend_runtime_imports(files: list[dict[str, Any]]) -> tuple[list[dict[str, str]], list[str]]:
  merged_by_path: dict[str, str] = {}
  ordered_paths: list[str] = []
  for file_item in files:
    if not isinstance(file_item, dict):
      continue
    path = text_or_default(file_item.get("path"), "")
    content = file_item.get("content")
    if content is None:
      content = file_item.get("code")
    if not path or not isinstance(content, str):
      continue
    if path not in merged_by_path:
      ordered_paths.append(path)
    merged_by_path[path] = content

  changed_paths: list[str] = []
  needed_shims: set[str] = set()
  for path, content in list(merged_by_path.items()):
    if not path.endswith((".js", ".jsx", ".ts", ".tsx")):
      continue
    updated = content
    for module_name, shim_path in RUNTIME_IMPORT_SHIM_PATHS.items():
      replacement = relative_import_path(path, shim_path)
      replaced = re.sub(
        rf"(?P<quote>['\"]){re.escape(module_name)}(?:/[^'\"]*)?(?P=quote)",
        lambda match, replacement=replacement: f"{match.group('quote')}{replacement}{match.group('quote')}",
        updated,
      )
      if replaced != updated:
        needed_shims.add(module_name)
        updated = replaced
    if updated != content:
      merged_by_path[path] = updated
      changed_paths.append(path)

  for module_name, shim_path in RUNTIME_IMPORT_SHIM_PATHS.items():
    if module_name not in needed_shims or shim_path in merged_by_path:
      continue
    merged_by_path[shim_path] = runtime_import_shim_code(module_name)
    ordered_paths.append(shim_path)
    changed_paths.append(shim_path)

  return [{"path": path, "content": merged_by_path[path]} for path in ordered_paths], changed_paths


def relative_import_path(from_path: str, target_path: str) -> str:
  from_dir = posixpath.dirname(from_path) or "."
  relative_path = posixpath.relpath(target_path, from_dir)
  if not relative_path.startswith("."):
    relative_path = f"./{relative_path}"
  return relative_path


def router_shim_code() -> str:
  return (
    'import React, { Children, createContext, isValidElement, useContext, useEffect, useMemo, useState } from "react";\n\n'
    "const RouterContext = createContext(null);\n"
    "const OutletContext = createContext(null);\n\n"
    "function previewBasePath() {\n"
    "  if (typeof window !== 'undefined' && window.__WORKTUAL_PREVIEW_BASE__) {\n"
    "    return String(window.__WORKTUAL_PREVIEW_BASE__ || '').replace(/\\/+$/, '');\n"
    "  }\n"
    "  if (typeof document !== 'undefined') {\n"
    "    const base = document.querySelector('base[href]');\n"
    "    if (base) {\n"
    "      try {\n"
    "        const href = new URL(base.getAttribute('href') || '', window.location.href).pathname || '';\n"
    "        if (href.includes('/api/previews/')) return href.replace(/\\/+$/, '');\n"
    "      } catch {\n"
    "        /* ignore invalid base href */\n"
    "      }\n"
    "    }\n"
    "  }\n"
    "  if (typeof window === 'undefined') return '';\n"
    "  const match = String(window.location.pathname || '').match(/^\\/api\\/previews\\/[^/]+\\/[^/]+/);\n"
    "  return match ? match[0] : '';\n"
    "}\n\n"
    "function normalizePath(path) {\n"
    "  const value = String(path || '/').split('?')[0].split('#')[0];\n"
    "  if (!value || value === '/') return '/';\n"
    "  return `/${value.replace(/^\\/+|\\/+$/g, '')}`;\n"
    "}\n\n"
    "function stripPreviewBase(pathname) {\n"
    "  const base = previewBasePath();\n"
    "  const normalized = normalizePath(pathname);\n"
    "  if (!base) return normalized;\n"
    "  const baseNorm = normalizePath(base);\n"
    "  if (normalized === baseNorm) return '/';\n"
    "  if (normalized.startsWith(`${baseNorm}/`)) return normalizePath(normalized.slice(baseNorm.length));\n"
    "  return normalized;\n"
    "}\n\n"
    "function withPreviewBase(pathname) {\n"
    "  const base = previewBasePath();\n"
    "  const routePath = normalizePath(pathname);\n"
    "  if (!base) return routePath;\n"
    "  if (routePath === '/') return `${base}/`;\n"
    "  return `${base}${routePath}`.replace(/\\/{2,}/g, '/');\n"
    "}\n\n"
    "function currentBrowserLocation() {\n"
    "  if (typeof window === 'undefined') return { pathname: '/', search: '', hash: '' };\n"
    "  return {\n"
    "    pathname: stripPreviewBase(window.location.pathname || '/'),\n"
    "    search: window.location.search || '',\n"
    "    hash: window.location.hash || '',\n"
    "  };\n"
    "}\n\n"
    "function routeToHref(to) {\n"
    '  if (typeof to === "string") {\n'
    "    const raw = (to || '#').trim();\n"
    "    if (!raw || raw === '#') return '#';\n"
    "    if (/^(https?:|mailto:|tel:|#)/i.test(raw)) return raw;\n"
    "    const hashIndex = raw.indexOf('#');\n"
    "    const queryIndex = raw.indexOf('?');\n"
    "    const pathEnd = Math.min(\n"
    "      queryIndex === -1 ? raw.length : queryIndex,\n"
    "      hashIndex === -1 ? raw.length : hashIndex,\n"
    "    );\n"
    "    const pathPart = raw.slice(0, pathEnd);\n"
    "    const search = queryIndex >= 0 ? raw.slice(queryIndex, hashIndex >= 0 ? hashIndex : undefined) : '';\n"
    "    const hash = hashIndex >= 0 ? raw.slice(hashIndex) : '';\n"
    "    return `${withPreviewBase(stripPreviewBase(pathPart))}${search}${hash}`;\n"
    "  }\n"
    '  if (to && typeof to === "object") {\n'
    "    const path = withPreviewBase(stripPreviewBase(to.pathname || '/'));\n"
    "    const search = to.search ? (String(to.search).startsWith('?') ? to.search : `?${to.search}`) : '';\n"
    "    const hash = to.hash ? (String(to.hash).startsWith('#') ? to.hash : `#${to.hash}`) : '';\n"
    "    return `${path}${search}${hash}`;\n"
    "  }\n"
    '  return "#";\n'
    "}\n\n"
    "function pathOnly(to) {\n"
    "  const href = routeToHref(to);\n"
    "  if (!href || href === '#') return '/';\n"
    "  try {\n"
    "    const url = new URL(href, typeof window === 'undefined' ? 'http://localhost' : window.location.href);\n"
    "    return stripPreviewBase(url.pathname || '/');\n"
    "  } catch {\n"
    "    return stripPreviewBase(href.split('?')[0].split('#')[0] || '/');\n"
    "  }\n"
    "}\n\n"
    "function joinPaths(base, child) {\n"
    "  if (!child) return normalizePath(base || '/');\n"
    "  if (String(child).startsWith('/')) return normalizePath(child);\n"
    "  return normalizePath(`${normalizePath(base || '/')}/${child}`);\n"
    "}\n\n"
    "function routeChildren(children) {\n"
    "  return Children.toArray(children).filter((child) => isValidElement(child));\n"
    "}\n\n"
    "function isSameOrChildPath(pathname, routePath) {\n"
    "  const path = normalizePath(pathname);\n"
    "  const route = normalizePath(routePath);\n"
    "  if (route === '/') return true;\n"
    "  return path === route || path.startsWith(`${route}/`);\n"
    "}\n\n"
    "function renderWithOutlet(element, outlet) {\n"
    "  if (!element) return outlet || null;\n"
    "  return <OutletContext.Provider value={outlet || null}>{element}</OutletContext.Provider>;\n"
    "}\n\n"
    "function resolveRouteElement(props) {\n"
    "  if (props?.element) return props.element;\n"
    "  if (props?.Component) return <props.Component />;\n"
    "  if (props?.component) return React.createElement(props.component);\n"
    "  return props?.children || null;\n"
    "}\n\n"
    "function matchRouteElement(route, pathname, basePath = '/') {\n"
    "  if (!isValidElement(route)) return null;\n"
    "  const props = route.props || {};\n"
    "  const hasIndex = Boolean(props.index);\n"
    "  const routePath = hasIndex ? normalizePath(basePath) : joinPaths(basePath, props.path || '');\n"
    "  const children = routeChildren(props.children);\n"
    "  const isWildcard = String(props.path || '').includes('*');\n"
    "  const matches = hasIndex\n"
    "    ? normalizePath(pathname) === normalizePath(basePath)\n"
    "    : isWildcard\n"
    "      ? isSameOrChildPath(pathname, routePath.replace(/\\/\\*$/, ''))\n"
    "      : children.length\n"
    "        ? isSameOrChildPath(pathname, routePath)\n"
    "        : normalizePath(pathname) === routePath;\n"
    "  if (!matches) return null;\n"
    "  let outlet = null;\n"
    "  for (const child of children) {\n"
    "    outlet = matchRouteElement(child, pathname, routePath);\n"
    "    if (outlet) break;\n"
    "  }\n"
    "  return renderWithOutlet(resolveRouteElement(props), outlet);\n"
    "}\n\n"
    "function classNameValue(value, state = {}) {\n"
    '  return typeof value === "function" ? value(state) : value;\n'
    "}\n\n"
    "export function BrowserRouter({ children }) {\n"
    "  const [location, setLocation] = useState(currentBrowserLocation);\n"
    "  const syncLocation = useMemo(() => () => setLocation(currentBrowserLocation()), []);\n"
    "  const navigate = useMemo(() => (to, options = {}) => {\n"
    "    const href = routeToHref(to);\n"
    "    if (typeof window !== 'undefined' && href && href !== '#') {\n"
    "      const method = options && options.replace ? 'replaceState' : 'pushState';\n"
    "      window.history[method]({}, '', href);\n"
    "    }\n"
    "    syncLocation();\n"
    "  }, [syncLocation]);\n"
    "  useEffect(() => {\n"
    "    if (typeof window === 'undefined') return undefined;\n"
    "    const onPopState = () => syncLocation();\n"
    "    window.addEventListener('popstate', onPopState);\n"
    "    return () => window.removeEventListener('popstate', onPopState);\n"
    "  }, [syncLocation]);\n"
    "  useEffect(() => {\n"
    "    syncLocation();\n"
    "  }, [syncLocation]);\n"
    "  const value = useMemo(() => ({ location, navigate }), [location, navigate]);\n"
    "  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>;\n"
    "}\n\n"
    "export const HashRouter = BrowserRouter;\n"
    "export const MemoryRouter = BrowserRouter;\n\n"
    "export function Routes({ children }) {\n"
    "  const router = useContext(RouterContext);\n"
    "  const pathname = router?.location?.pathname || currentBrowserLocation().pathname || '/';\n"
    "  for (const child of routeChildren(children)) {\n"
    "    const matched = matchRouteElement(child, pathname, '/');\n"
    "    if (matched) return matched;\n"
    "  }\n"
    "  return null;\n"
    "}\n\n"
    "export function Route({ element, Component, component, children }) {\n"
    "  return resolveRouteElement({ element, Component, component, children });\n"
    "}\n\n"
    "export function Link({ to = '#', className, children, onClick: userOnClick, target, ...props }) {\n"
    "  const router = useContext(RouterContext);\n"
    "  const href = routeToHref(to);\n"
    "  const isActive = normalizePath(router?.location?.pathname || '/') === normalizePath(pathOnly(to));\n"
    "  const onClick = (event) => {\n"
    "    userOnClick?.(event);\n"
    "    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || target) return;\n"
    "    event.preventDefault();\n"
    "    router?.navigate?.(to, { replace: false });\n"
    "  };\n"
    "  return <a {...props} href={href} target={target} onClick={onClick} className={classNameValue(className, { isActive })}>{children}</a>;\n"
    "}\n\n"
    "export function NavLink({ to = '#', className, children, ...props }) {\n"
    "  const location = useLocation();\n"
    "  const isActive = normalizePath(location.pathname || '/') === normalizePath(pathOnly(to));\n"
    "  const resolvedClassName = classNameValue(className, { isActive });\n"
    "  const resolvedChildren = typeof children === 'function' ? children({ isActive }) : children;\n"
    "  return <Link to={to} className={resolvedClassName} {...props}>{resolvedChildren}</Link>;\n"
    "}\n\n"
    "export function Navigate({ to = '/', replace = true }) {\n"
    "  const navigate = useNavigate();\n"
    "  useEffect(() => {\n"
    "    navigate(to, { replace });\n"
    "  }, [navigate, replace, to]);\n"
    "  return null;\n"
    "}\n\n"
    "export function Outlet() {\n"
    "  return useContext(OutletContext);\n"
    "}\n\n"
    "export function useNavigate() {\n"
    "  const router = useContext(RouterContext);\n"
    "  return router?.navigate || (() => {});\n"
    "}\n\n"
    "export function useLocation() {\n"
    "  const router = useContext(RouterContext);\n"
    "  return router?.location || currentBrowserLocation();\n"
    "}\n\n"
    "export function useParams() {\n"
    "  return {};\n"
    "}\n\n"
    "export function useSearchParams() {\n"
    "  const location = useLocation();\n"
    "  const params = useMemo(() => new URLSearchParams(location.search || ''), [location.search]);\n"
    "  return [params, () => {}];\n"
    "}\n\n"
    "export const Router = BrowserRouter;\n"
  )


def runtime_import_shim_code(module_name: str) -> str:
  if module_name == "react-router-dom":
    return router_shim_code()
  if module_name == "framer-motion":
    return framer_motion_shim_code()
  if module_name == "clsx":
    return clsx_shim_code()
  if module_name == "tailwind-merge":
    return tailwind_merge_shim_code()
  if module_name == "recharts":
    return recharts_shim_code()
  raise ValueError(f"Unsupported runtime import shim: {module_name}")


def recharts_shim_code() -> str:
  return (
    'import React, { Children, isValidElement, useMemo } from "react";\n\n'
    "function asNumber(value, fallback = 0) {\n"
    "  const parsed = Number(value);\n"
    "  return Number.isFinite(parsed) ? parsed : fallback;\n"
    "}\n\n"
    "function pieSlices(data, dataKey) {\n"
    "  const total = (data || []).reduce((sum, item) => sum + asNumber(item?.[dataKey]), 0) || 1;\n"
    "  let cursor = 0;\n"
    "  return (data || []).map((item, index) => {\n"
    "    const value = asNumber(item?.[dataKey]);\n"
    "    const start = (cursor / total) * 360;\n"
    "    cursor += value;\n"
    "    const end = (cursor / total) * 360;\n"
    "    return { item, index, start, end, value };\n"
    "  });\n"
    "}\n\n"
    "function arcPath(cx, cy, radius, startAngle, endAngle) {\n"
    "  const start = ((startAngle - 90) * Math.PI) / 180;\n"
    "  const end = ((endAngle - 90) * Math.PI) / 180;\n"
    "  const x1 = cx + radius * Math.cos(start);\n"
    "  const y1 = cy + radius * Math.sin(start);\n"
    "  const x2 = cx + radius * Math.cos(end);\n"
    "  const y2 = cy + radius * Math.sin(end);\n"
    "  const largeArc = endAngle - startAngle > 180 ? 1 : 0;\n"
    "  return `M ${cx} ${cy} L ${x1} ${y1} A ${radius} ${radius} 0 ${largeArc} 1 ${x2} ${y2} Z`;\n"
    "}\n\n"
    "export function ResponsiveContainer({ children, width = '100%', height = '100%' }) {\n"
    "  return <div style={{ width, height, minHeight: 180 }}>{children}</div>;\n"
    "}\n\n"
    "export function PieChart({ children, width = '100%', height = 220 }) {\n"
    "  return <svg width={width} height={height} viewBox=\"0 0 220 220\" role=\"img\">{children}</svg>;\n"
    "}\n\n"
    "export function Pie({ data = [], dataKey = 'value', cx = 110, cy = 110, outerRadius = 80, children }) {\n"
    "  const fills = Children.toArray(children)\n"
    "    .filter((child) => isValidElement(child))\n"
    "    .map((child) => child.props?.fill || '#0f766e');\n"
    "  const slices = useMemo(() => pieSlices(data, dataKey), [data, dataKey]);\n"
    "  return (\n"
    "    <g>\n"
    "      {slices.map(({ item, index, start, end }) => (\n"
    "        <path\n"
    "          key={`${index}-${item?.name || item?.label || 'slice'}`}\n"
    "          d={arcPath(cx, cy, outerRadius, start, end)}\n"
    "          fill={fills[index % fills.length] || '#0f766e'}\n"
    "          stroke=\"#ffffff\"\n"
    "          strokeWidth=\"1\"\n"
    "        />\n"
    "      ))}\n"
    "    </g>\n"
    "  );\n"
    "}\n\n"
    "export function Cell({ fill }) {\n"
    "  return null;\n"
    "}\n\n"
    "export function Tooltip() {\n"
    "  return null;\n"
    "}\n\n"
    "export function Legend() {\n"
    "  return null;\n"
    "}\n\n"
    "export function BarChart({ children }) {\n"
    "  return <svg width=\"100%\" height=\"220\" viewBox=\"0 0 220 220\">{children}</svg>;\n"
    "}\n\n"
    "export function Bar() {\n"
    "  return null;\n"
    "}\n\n"
    "export function XAxis() {\n"
    "  return null;\n"
    "}\n\n"
    "export function YAxis() {\n"
    "  return null;\n"
    "}\n\n"
    "export function CartesianGrid() {\n"
    "  return null;\n"
    "}\n"
  )


def framer_motion_shim_code() -> str:
  return (
    'import React, { forwardRef } from "react";\n\n'
    "const MOTION_ONLY_PROPS = new Set([\n"
    '  "animate", "initial", "exit", "transition", "variants", "whileHover", "whileTap",\n'
    '  "whileFocus", "whileInView", "whileDrag", "layout", "layoutId", "viewport", "custom",\n'
    '  "drag", "dragConstraints", "dragElastic", "dragMomentum", "dragTransition",\n'
    '  "onAnimationStart", "onAnimationComplete", "onUpdate", "styleEffect",\n'
    "]);\n\n"
    "function cleanProps(props) {\n"
    "  const output = {};\n"
    "  for (const [key, value] of Object.entries(props || {})) {\n"
    "    if (MOTION_ONLY_PROPS.has(key)) continue;\n"
    "    output[key] = value;\n"
    "  }\n"
    "  return output;\n"
    "}\n\n"
    "function createMotionComponent(tag) {\n"
    "  return forwardRef(function MotionShimComponent({ children, ...props }, ref) {\n"
    "    return React.createElement(tag, { ...cleanProps(props), ref }, children);\n"
    "  });\n"
    "}\n\n"
    "export const motion = new Proxy({}, { get: (_target, tag) => createMotionComponent(tag) });\n"
    "export const m = motion;\n\n"
    "export function AnimatePresence({ children }) {\n"
    "  return <>{children}</>;\n"
    "}\n\n"
    "export function LazyMotion({ children }) {\n"
    "  return <>{children}</>;\n"
    "}\n\n"
    "export const domAnimation = {};\n"
    "export const domMax = {};\n\n"
    "export function useAnimation() {\n"
    "  return { start: () => Promise.resolve(), stop: () => {}, set: () => {} };\n"
    "}\n\n"
    "export function useAnimate() {\n"
    "  return [null, () => Promise.resolve()];\n"
    "}\n\n"
    "export function useInView() {\n"
    "  return true;\n"
    "}\n"
  )


def clsx_shim_code() -> str:
  return (
    "function flatten(value, output) {\n"
    "  if (!value) return;\n"
    "  if (typeof value === 'string' || typeof value === 'number') {\n"
    "    output.push(String(value));\n"
    "    return;\n"
    "  }\n"
    "  if (Array.isArray(value)) {\n"
    "    value.forEach((item) => flatten(item, output));\n"
    "    return;\n"
    "  }\n"
    "  if (typeof value === 'object') {\n"
    "    Object.entries(value).forEach(([key, enabled]) => {\n"
    "      if (enabled) output.push(key);\n"
    "    });\n"
    "  }\n"
    "}\n\n"
    "export function clsx(...values) {\n"
    "  const output = [];\n"
    "  values.forEach((value) => flatten(value, output));\n"
    "  return output.join(' ');\n"
    "}\n\n"
    "export default clsx;\n"
  )


def tailwind_merge_shim_code() -> str:
  return (
    "function flatten(value, output) {\n"
    "  if (!value) return;\n"
    "  if (typeof value === 'string' || typeof value === 'number') {\n"
    "    output.push(String(value));\n"
    "    return;\n"
    "  }\n"
    "  if (Array.isArray(value)) {\n"
    "    value.forEach((item) => flatten(item, output));\n"
    "  }\n"
    "}\n\n"
    "export function twMerge(...values) {\n"
    "  const output = [];\n"
    "  values.forEach((value) => flatten(value, output));\n"
    "  return output.join(' ').replace(/\\s+/g, ' ').trim();\n"
    "}\n"
  )


def generated_sources_use_tailwind(files_by_path: dict[str, str]) -> bool:
  for path, content in files_by_path.items():
    if path.endswith((".js", ".jsx", ".ts", ".tsx")) and TAILWIND_CLASS_RE.search(content):
      return True
  return False


def ensure_tailwind_package_dependencies(content: str) -> str:
  try:
    data = json.loads(content) if content.strip() else {}
  except json.JSONDecodeError:
    data = {}
  if not isinstance(data, dict):
    data = {}
  scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
  scripts.setdefault("build", "vite --host 0.0.0.0")
  scripts.setdefault("dev", "vite --host 0.0.0.0")
  dependencies = data.get("dependencies") if isinstance(data.get("dependencies"), dict) else {}
  for name in ("@vitejs/plugin-react", "vite", "react", "react-dom", "lucide-react"):
    dependencies.setdefault(name, "latest")
  dev_dependencies = data.get("devDependencies") if isinstance(data.get("devDependencies"), dict) else {}
  dev_dependencies.setdefault("tailwindcss", "^3.4.17")
  dev_dependencies.setdefault("postcss", "^8.5.0")
  dev_dependencies.setdefault("autoprefixer", "^10.4.20")
  data["scripts"] = scripts
  data["dependencies"] = dependencies
  data["devDependencies"] = dev_dependencies
  return json.dumps(data, indent=2)


def ensure_tailwind_css_directives(content: str) -> str:
  if "@tailwind base" in content and "@tailwind components" in content and "@tailwind utilities" in content:
    return content
  suffix = content.strip()
  if suffix:
    return f"{TAILWIND_DIRECTIVES}\n\n{suffix}\n"
  return f"{TAILWIND_DIRECTIVES}\n\n* {{ box-sizing: border-box; }}\nbody {{ margin: 0; min-width: 320px; font-family: {DEFAULT_WEBSITE_FONT_FAMILY}; }}\n"


def ensure_website_font_in_index_css(content: str) -> str:
  if "Times New Roman" in content:
    return content
  stripped = content.rstrip()
  if not stripped:
    return f"{DEFAULT_WEBSITE_BODY_FONT_RULE}\n"
  return f"{stripped}\n\n{DEFAULT_WEBSITE_BODY_FONT_RULE}\n"


def ensure_website_font_in_tailwind_config(content: str) -> str:
  if "Times New Roman" in content:
    return content
  if "extend: {}" in content:
    return content.replace("extend: {}", f"extend: {{ {DEFAULT_WEBSITE_TAILWIND_FONT_EXTEND} }}", 1)
  if "extend: {" in content and "fontFamily" not in content:
    return content.replace("extend: {", f"extend: {{ {DEFAULT_WEBSITE_TAILWIND_FONT_EXTEND},", 1)
  return content


def default_tailwind_config() -> str:
  return (
    "module.exports = {\n"
    "  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],\n"
    "  theme: {\n"
    "    extend: {\n"
    '      fontFamily: {\n'
    '        sans: [\'"Times New Roman"\', "Times", "serif"],\n'
    '        serif: [\'"Times New Roman"\', "Times", "serif"],\n'
    "      },\n"
    "    },\n"
    "  },\n"
    "  plugins: [],\n"
    "};\n"
  )


def default_postcss_config() -> str:
  return "module.exports = { plugins: { tailwindcss: {}, autoprefixer: {} } };\n"


def html_escape_text(value: str) -> str:
  return (
    value.replace("&", "&amp;")
    .replace("<", "&lt;")
    .replace(">", "&gt;")
    .replace('"', "&quot;")
  )
