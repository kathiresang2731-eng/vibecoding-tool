from __future__ import annotations

import re


def preview_base_path(project_id: str, version_id: str) -> str:
  return f"/api/previews/{project_id.strip()}/{version_id.strip()}/"


def preview_navigation_guard_script(*, base_href: str, project_id: str = "", version_id: str = "") -> str:
  """Keep preview navigation under the version prefix and expose app routes to generated SPAs."""
  return f"""(function () {{
  var base = "{base_href}".replace(/\\/+$/, "");
  if (!base || window.__WORKTUAL_PREVIEW_NAV_GUARD__) return;
  window.__WORKTUAL_PREVIEW_NAV_GUARD__ = true;
  window.__WORKTUAL_PREVIEW_BASE__ = base + "/";
  window.__WORKTUAL_PREVIEW_IDS__ = {{
    projectId: "{project_id}",
    versionId: "{version_id}",
    base: base + "/",
  }};

  try {{
    localStorage.setItem("worktual_active_preview_base", base + "/");
    localStorage.setItem("worktual_active_preview_project", "{project_id}");
    localStorage.setItem("worktual_active_preview_version", "{version_id}");
    localStorage.setItem("worktual_active_preview_at", String(Date.now()));
  }} catch (storageErr) {{
    /* ignore */
  }}

  function normalizePath(path) {{
    var value = String(path || "/").split("?")[0].split("#")[0];
    if (!value || value === "/") return "/";
    return "/" + value.replace(/^\\/+|\\/+$/g, "");
  }}

  function stripPreviewBase(pathname) {{
    var normalized = normalizePath(pathname);
    var baseNorm = normalizePath(base);
    if (normalized === baseNorm) return "/";
    if (normalized.indexOf(baseNorm + "/") === 0) {{
      return normalizePath(normalized.slice(baseNorm.length));
    }}
    return normalized;
  }}

  function withPreviewBase(pathname) {{
    var routePath = normalizePath(pathname);
    if (routePath === "/") return base + "/";
    return (base + routePath).replace(/\\/{{2,}}/g, "/");
  }}

  function currentAppRoute() {{
    if (typeof window === "undefined") return "/";
    return stripPreviewBase(window.location.pathname || "/");
  }}

  function rewriteNavigationUrl(url) {{
    if (url == null || url === "") return url;
    var raw = String(url);
    if (/^(https?:|mailto:|tel:|data:|blob:|javascript:)/i.test(raw)) return url;
    if (raw.charAt(0) === "#") return url;
    try {{
      var parsed = new URL(raw, window.location.href);
      if (parsed.origin !== window.location.origin) return url;
      var pathname = parsed.pathname || "/";
      if (pathname.indexOf("/api/previews/") === 0) return url;
      var nextPath = withPreviewBase(stripPreviewBase(pathname));
      return nextPath + (parsed.search || "") + (parsed.hash || "");
    }} catch (err) {{
      return url;
    }}
  }}

  function syncPreviewRouteMeta() {{
    try {{
      var route = currentAppRoute();
      document.documentElement.setAttribute("data-worktual-preview-route", route);
      document.documentElement.setAttribute("data-worktual-preview-project", "{project_id}");
      document.documentElement.setAttribute("data-worktual-preview-version", "{version_id}");
    }} catch (err) {{
      /* ignore */
    }}
  }}

  function installLocationPathnamePatch() {{
    try {{
      var proto = window.Location && window.Location.prototype;
      if (!proto || proto.__WORKTUAL_PATHNAME_PATCH__) return;
      var desc = Object.getOwnPropertyDescriptor(proto, "pathname");
      if (!desc || typeof desc.get !== "function") return;
      var nativeGet = desc.get;
      var nativeSet = desc.set;
      Object.defineProperty(proto, "pathname", {{
        get: function () {{
          return stripPreviewBase(nativeGet.call(this));
        }},
        set: function (value) {{
          if (nativeSet) nativeSet.call(this, withPreviewBase(String(value || "/")));
        }},
        configurable: true,
        enumerable: desc.enumerable !== false,
      }});
      proto.__WORKTUAL_PATHNAME_PATCH__ = true;
    }} catch (err) {{
      /* Some browsers block Location.prototype patching */
    }}
  }}

  function patchLocationMethods() {{
    try {{
      var proto = window.Location && window.Location.prototype;
      if (!proto) return;
      ["assign", "replace"].forEach(function (name) {{
        if (typeof proto[name] !== "function" || proto["__WORKTUAL_" + name + "_PATCH__"]) return;
        var original = proto[name];
        proto[name] = function (url) {{
          return original.call(this, rewriteNavigationUrl(url));
        }};
        proto["__WORKTUAL_" + name + "_PATCH__"] = true;
      }});
      var hrefDesc = Object.getOwnPropertyDescriptor(proto, "href");
      if (hrefDesc && typeof hrefDesc.set === "function" && !proto.__WORKTUAL_HREF_PATCH__) {{
        var nativeSet = hrefDesc.set;
        var nativeGet = hrefDesc.get;
        Object.defineProperty(proto, "href", {{
          get: function () {{
            return nativeGet.call(this);
          }},
          set: function (value) {{
            nativeSet.call(this, rewriteNavigationUrl(String(value || "")));
          }},
          configurable: true,
          enumerable: hrefDesc.enumerable !== false,
        }});
        proto.__WORKTUAL_HREF_PATCH__ = true;
      }}
    }} catch (err) {{
      /* ignore */
    }}
  }}

  function rewriteAnchor(node) {{
    if (!node || !node.getAttribute) return;
    var href = node.getAttribute("href");
    if (!href || href.charAt(0) === "#" || /^(https?:|mailto:|tel:)/i.test(href)) return;
    var rewritten = rewriteNavigationUrl(href);
    if (rewritten !== href) node.setAttribute("href", rewritten);
  }}

  function rewriteAnchors(root) {{
    if (!root || !root.querySelectorAll) return;
    if (root.tagName === "A") rewriteAnchor(root);
    root.querySelectorAll("a[href]").forEach(rewriteAnchor);
  }}

  function rewriteFormAction(form) {{
    if (!form || !form.getAttribute) return;
    var action = form.getAttribute("action");
    if (!action || /^(https?:|mailto:|tel:)/i.test(action)) return;
    var rewritten = rewriteNavigationUrl(action);
    if (rewritten !== action) form.setAttribute("action", rewritten);
  }}

  function installAnchorHrefObserver() {{
    rewriteAnchors(document.documentElement);
    document.querySelectorAll("form[action]").forEach(rewriteFormAction);
    if (!window.MutationObserver) return;
    var observer = new MutationObserver(function (records) {{
      records.forEach(function (record) {{
        if (record.type === "attributes") {{
          if (record.target && record.target.tagName === "A") rewriteAnchor(record.target);
          if (record.target && record.target.tagName === "FORM") rewriteFormAction(record.target);
          return;
        }}
        record.addedNodes.forEach(function (node) {{
          if (node.nodeType !== 1) return;
          rewriteAnchors(node);
          if (node.tagName === "FORM") rewriteFormAction(node);
          if (node.querySelectorAll) node.querySelectorAll("form[action]").forEach(rewriteFormAction);
        }});
      }});
    }});
    observer.observe(document.documentElement, {{
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["href", "action"],
    }});
  }}

  function patchHistoryMethod(methodName) {{
    var original = history[methodName].bind(history);
    history[methodName] = function (state, title, url) {{
      if (arguments.length < 3) return original(state, title);
      var rewritten = rewriteNavigationUrl(url);
      var result = original(state, title, rewritten);
      syncPreviewRouteMeta();
      return result;
    }};
  }}

  patchHistoryMethod("pushState");
  patchHistoryMethod("replaceState");
  installLocationPathnamePatch();
  patchLocationMethods();
  syncPreviewRouteMeta();
  window.addEventListener("popstate", syncPreviewRouteMeta);

  function dispatchPreviewRouteChange() {{
    syncPreviewRouteMeta();
    window.dispatchEvent(new PopStateEvent("popstate", {{ state: history.state }}));
  }}

  function interceptPreviewNavigation(targetUrl, replace) {{
    var rewritten = rewriteNavigationUrl(targetUrl);
    if (!rewritten || rewritten === targetUrl) return false;
    history[replace ? "replaceState" : "pushState"]({{}}, "", rewritten);
    dispatchPreviewRouteChange();
    return true;
  }}

  if (window.navigation && typeof window.navigation.addEventListener === "function") {{
    window.navigation.addEventListener("navigate", function (event) {{
      if (!event || !event.destination || !event.destination.url) return;
      if (event.navigationType === "reload") return;
      try {{
        var parsed = new URL(event.destination.url);
        if (parsed.origin !== window.location.origin) return;
        if (parsed.pathname.indexOf("/api/previews/") === 0) return;
        var rewritten = rewriteNavigationUrl(event.destination.url);
        if (!rewritten || rewritten === event.destination.url) return;
        if (!event.canIntercept) return;
        event.preventDefault();
        event.intercept({{
          handler: function () {{
            history.pushState({{}}, "", rewritten);
            dispatchPreviewRouteChange();
          }},
        }});
      }} catch (navErr) {{
        /* ignore */
      }}
    }});
  }}

  document.addEventListener("submit", function (event) {{
    var form = event.target;
    if (!form || form.tagName !== "FORM") return;
    rewriteFormAction(form);
    var method = String(form.getAttribute("method") || "get").toLowerCase();
    if (method !== "get") return;
    var action = form.getAttribute("action") || window.location.href;
    var rewritten = rewriteNavigationUrl(action);
    if (!rewritten || rewritten === action) return;
    try {{
      var beforePath = new URL(action, window.location.href).pathname || "/";
      var afterPath = new URL(rewritten, window.location.href).pathname || "/";
      if (beforePath === afterPath) return;
    }} catch (compareErr) {{
      return;
    }}
    event.preventDefault();
    var nextUrl = rewritten;
    try {{
      var params = new URLSearchParams(new FormData(form));
      var qs = params.toString();
      if (qs) nextUrl += (nextUrl.indexOf("?") >= 0 ? "&" : "?") + qs;
    }} catch (formErr) {{
      /* ignore */
    }}
    history.pushState({{}}, "", nextUrl);
    dispatchPreviewRouteChange();
  }}, true);

  document.addEventListener("click", function (event) {{
    var link = event.target && event.target.closest ? event.target.closest("a[href]") : null;
    if (!link) return;
    var target = link.getAttribute("target");
    if (target && target !== "_self") return;
    var href = link.getAttribute("href");
    if (!href || href.charAt(0) === "#" || /^(https?:|mailto:|tel:|javascript:)/i.test(href)) return;
    var rewritten = rewriteNavigationUrl(href);
    if (!rewritten || rewritten === href) return;
    event.preventDefault();
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {{
      window.open(rewritten, "_blank");
      return;
    }}
    var replace = link.getAttribute("data-replace") === "true";
    history[replace ? "replaceState" : "pushState"]({{}}, "", rewritten);
    dispatchPreviewRouteChange();
  }}, true);

  function renderPreviewIdBadge() {{
    var ids = window.__WORKTUAL_PREVIEW_IDS__;
    if (!ids || !ids.projectId || !ids.versionId) return;
    if (document.querySelector("[data-worktual-preview-badge]")) return;
    var badge = document.createElement("div");
    badge.setAttribute("data-worktual-preview-badge", "true");
    badge.setAttribute("title", "Preview project/version IDs");
    badge.style.cssText =
      "position:fixed;bottom:10px;right:10px;z-index:2147483646;" +
      "max-width:min(92vw,420px);padding:6px 10px;border-radius:8px;" +
      "font:600 11px/1.35 ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;" +
      "color:#e2e8f0;background:rgba(15,23,42,0.92);border:1px solid rgba(148,163,184,0.35);" +
      "box-shadow:0 8px 24px rgba(15,23,42,0.35);pointer-events:none;word-break:break-all;";
    badge.textContent = "Preview " + ids.projectId + " / " + ids.versionId;
    (document.body || document.documentElement).appendChild(badge);
  }}

  function installPreviewIdBadge() {{
    if (document.body) {{
      renderPreviewIdBadge();
      return;
    }}
    document.addEventListener("DOMContentLoaded", renderPreviewIdBadge);
  }}

  document.addEventListener("DOMContentLoaded", installAnchorHrefObserver);
  if (document.readyState === "interactive" || document.readyState === "complete") {{
    installAnchorHrefObserver();
    installPreviewIdBadge();
  }} else {{
    document.addEventListener("DOMContentLoaded", installPreviewIdBadge);
  }}
}})();"""


def rewrite_preview_html(html: str, *, project_id: str = "", version_id: str = "") -> str:
  updated = (
    html.replace('src="/assets/', 'src="./assets/')
    .replace("src='/assets/", "src='./assets/")
    .replace('href="/assets/', 'href="./assets/')
    .replace("href='/assets/", "href='./assets/")
  )
  if not project_id or not version_id:
    return updated

  base_href = preview_base_path(project_id, version_id)
  base_tag = f'<base href="{base_href}">'
  if re.search(r"<base\s", updated, flags=re.IGNORECASE):
    updated = re.sub(
      r"<base\s[^>]*>",
      base_tag,
      updated,
      count=1,
      flags=re.IGNORECASE,
    )
  elif re.search(r"<head[^>]*>", updated, flags=re.IGNORECASE):
    updated = re.sub(
      r"(<head[^>]*>)",
      rf"\1\n  {base_tag}",
      updated,
      count=1,
      flags=re.IGNORECASE,
    )
  else:
    updated = f"{base_tag}\n{updated}"

  guard = preview_navigation_guard_script(base_href=base_href, project_id=project_id, version_id=version_id)
  if "__WORKTUAL_PREVIEW_NAV_GUARD__" not in updated:
    script = f"<script>{guard}</script>"
    if re.search(r"</head>", updated, flags=re.IGNORECASE):
      updated = re.sub(r"</head>", f"  {script}\n</head>", updated, count=1, flags=re.IGNORECASE)
    else:
      updated = f"{script}\n{updated}"

  return updated
