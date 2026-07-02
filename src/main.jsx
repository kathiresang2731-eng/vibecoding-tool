import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { createRoot } from "react-dom/client";
import Editor from "@monaco-editor/react";
import {
  AlertTriangle,
  Archive,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  FileCode2,
  FolderOpen,
  FolderPlus,
  Image as ImageIcon,
  Loader2,
  LogOut,
  Mic,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Paperclip,
  Plus,
  RefreshCw,
  Save,
  Search,
  Send,
  Server,
  Settings,
  ShieldCheck,
  Sparkles,
  Square,
  Trash2,
  Users,
  X,
} from "lucide-react";
import "./styles.css";

const USE_V1_RUNS_STREAM = import.meta.env.VITE_USE_V1_RUNS_STREAM === "true";
const platformStreamConfigRef = { useV1RunsStream: USE_V1_RUNS_STREAM };

function isLoopbackHost(hostname) {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]";
}

function resolveApiBaseUrl() {
  const configured = String(import.meta.env.VITE_API_BASE_URL || "").trim();
  const pageHost = window.location.hostname;
  const pagePort = window.location.port;

  // Vite dev/preview proxies /api on 5173/5174 — same origin works for LAN clients too.
  if (pagePort === "5174" || pagePort === "5173") {
    return "";
  }

  if (import.meta.env.DEV) {
    return "";
  }

  if (configured) {
    try {
      const url = new URL(configured);
      if (isLoopbackHost(url.hostname) && !isLoopbackHost(pageHost)) {
        return `${window.location.protocol}//${pageHost}:8787`;
      }
      return configured.replace(/\/$/, "");
    } catch {
      // Ignore invalid VITE_API_BASE_URL and derive from the page host.
    }
  }

  return `${window.location.protocol}//${pageHost}:8787`;
}

const API_BASE_URL = resolveApiBaseUrl();
const CHAT_INPUT_MIN_HEIGHT = 24;
const CHAT_INPUT_MAX_HEIGHT = 132;
const PROJECT_CHAT_HISTORY_LIMIT = 200;
const TOKEN_USAGE_COLLAPSED_REQUEST_LIMIT = 8;
const TOKEN_USAGE_EXPANDED_REQUEST_LIMIT = 100;
const SKILL_PICKER_MAX_HEIGHT_CLASS = "max-h-96";
const MAX_PROMPT_ATTACHMENTS = 8;
const MAX_PROMPT_ATTACHMENT_BYTES = 5 * 1024 * 1024;
const PROMPT_ATTACHMENT_ACCEPT = "image/*,.txt,.md,.json,.js,.jsx,.ts,.tsx,.css,.html,.htm,.log,.csv,.pdf,.svg,.yaml,.yml,.xml,.py";
const DEFAULT_ASSISTANT_MESSAGE =
  "Tell me what you want to build — a website, app feature, or code change — and I'll get started.";
const DEFAULT_PROJECT_NAME = "Untitled project";
const LIVE_PROGRESS_HISTORY_LIMIT = 80;
const CHAT_PROGRESS_ITEM_LIMIT = 7;
const BROWSER_WORKSPACES_STORAGE_KEY = "worktual.browserWorkspaces.v1";
const CHAT_SESSION_BY_PROJECT_KEY = "worktual.chatSessionByProject.v1";
const CHAT_SESSION_BY_USER_KEY = "worktual.chatSessionByUser.v1";
const LAST_ACTIVE_PROJECT_BY_USER_KEY = "worktual.lastActiveProjectByUser.v1";
const CLIENT_USER_ID_KEY = "worktual.clientUserId.v1";
const AUTH_TOKEN_KEY = "worktual.authToken.v1";
const CLIENT_SYSTEM_NAME_KEY = "worktual.clientSystemName.v1";
const LOCAL_HELPER_WORKSPACE_PATH_STORAGE_KEY = "worktual.localHelperWorkspacePath.v1";
const BROWSER_WORKSPACE_HANDLE_DB = "worktual-browser-workspaces";
const BROWSER_WORKSPACE_HANDLE_STORE = "directoryHandles";
const LOCAL_SKILLS_HELPER_URL = "http://127.0.0.1:8799";
const MAX_BROWSER_FILE_BYTES = 512 * 1024;
const LEFT_PANEL_MIN_WIDTH = 220;
const LEFT_PANEL_MAX_WIDTH = 380;
const RIGHT_PANEL_MIN_WIDTH = 420;
const RIGHT_PANEL_MAX_WIDTH = 760;
const CENTER_PANEL_MIN_WIDTH = 520;
const PANEL_RESIZER_WIDTH = 6;
const COLLAPSED_PANEL_WIDTH = 48;
const WORKSPACE_MOBILE_MAX = 767;
const WORKSPACE_TABLET_MAX = 1103;
const MODEL_OPTIONS = [
  { value: "server-default", label: "Default" },
  { value: "gemini-3.5-flash", label: "Flash" },
  { value: "gemini-3.1-pro-preview", label: "Pro" },
];
const IGNORED_BROWSER_DIRECTORIES = new Set([".git", ".runtime", ".venv", "__pycache__", "dist", "node_modules"]);
const ALLOWED_BROWSER_DOT_DIRECTORIES = new Set([".worktual", ".cursor", ".agents"]);
const IGNORED_BROWSER_FILE_NAMES = new Set([".DS_Store", ".env", ".env.development", ".env.local", ".env.production", "Thumbs.db"]);
const SUPPORTED_ROOT_FILES = new Set([
  "index.html",
  "app.js",
  "index.js",
  "main.js",
  "script.js",
  "main.css",
  "style.css",
  "styles.css",
  "package.json",
  "package-lock.json",
  "vite.config.js",
  "vite.config.mjs",
  "vite.config.cjs",
  "vite.config.ts",
  "tailwind.config.js",
  "tailwind.config.mjs",
  "tailwind.config.cjs",
  "tailwind.config.ts",
  "postcss.config.js",
  "postcss.config.mjs",
  "postcss.config.cjs",
  "eslint.config.js",
  "eslint.config.mjs",
  "eslint.config.cjs",
  "tsconfig.json",
  "tsconfig.app.json",
  "tsconfig.node.json",
  "jsconfig.json",
  "components.json",
  "vercel.json",
]);
const REQUIRED_BROWSER_PROJECT_ROOT_FILES = ["index.html", "package.json"];
const STATIC_BROWSER_PROJECT_ENTRY_FILE = "index.html";
const REQUIRED_BROWSER_PROJECT_SOURCE_PREFIX = "src/";
const BINARY_PUBLIC_ASSET_EXTENSIONS = new Set([
  ".avif",
  ".gif",
  ".ico",
  ".jpeg",
  ".jpg",
  ".otf",
  ".png",
  ".ttf",
  ".webp",
  ".woff",
  ".woff2",
]);
const IMPORT_SUMMARY_PATH_LIMIT = 8;
const GENERATION_STREAM_STALL_TIMEOUT_MS = 30000;
const CHAT_PROGRESS_HIDDEN_STEPS = new Set([
  "backend.waiting",
  "project.loading",
  "assistant.delta",
  "tool.requested",
  "provider.ready",
  "agent.run.started",
  "agent.runtime.persisting",
  "agent.runtime.persisted",
  "orchestrator.starting",
  "orchestrator.completed",
  "response.normalizing",
  "conversation.completed",
  "conversation.response",
  "conversation.response.completed",
  "generation.recording",
  "generation.completed",
  "local.sync",
  "local.sync.skipped",
  "local.sync.completed",
  "workspace.sync.started",
  "workspace.sync.completed",
]);
const CHAT_PROGRESS_VISIBLE_STEPS = new Set([
  "request.queued",
  "request.received",
  "project.loaded",
  "routing.started",
  "routing.completed",
  "agent.decision",
  "generate_simple_code_file.input",
  "generate_simple_code_file.output",
  "confirmation.brief.started",
  "confirmation.brief.completed",
  "confirmation.decision.started",
  "confirmation.decision.completed",
  "agent.runtime.loop.started",
  "agent.runtime.loop.completed",
  "update.summary",
  "plan.created",
  "files.materializing",
  "file.written",
  "files.materialized",
  "file.diff.ready",
  "patch.proposed",
  "patch.applied",
  "tool.read_file",
  "tool.write_file",
  "tool.str_replace",
  "tool.list_files",
  "streaming.file_agent.started",
  "streaming.file_agent.completed",
  "agent.parallel.started",
  "agent.parallel.completed",
  "agent.parallel.plan",
  "agent.parallel.wave.started",
  "agent.parallel.wave.completed",
  "orchestrator.wave.checkpoint",
  "context.greenfield",
  "context.analysis",
  "gate.syntax.wave",
  "files.wave.persisted",
  "agent.worker.started",
  "agent.worker.completed",
  "agent.worker.failed",
  "gate.started",
  "gate.passed",
  "gate.failed",
  "gate.build.started",
  "gate.build.passed",
  "gate.build.failed",
  "gate.build.skipped",
  "gate.repair.started",
  "gate.repair.completed",
  "gate.repair.skipped",
  "gate.repair.no_changes",
  "gate.deterministic.normalized",
  "gate.deterministic.repair",
  "gate.visual_qa.running",
  "gate.visual_qa.passed",
  "gate.visual_qa.failed",
  "patch.approval.required",
  "patch.approval.rejected",
  "agents.md.bootstrapped",
  "error.diagnosed",
  "scope.resolving",
  "scope.resolved",
  "commit.rejected",
  "tool.search_codebase",
  "files.persisting",
  "files.persisted",
  "preview.built",
  "browser.write_back",
  "browser.write_back.completed",
  "browser.write_back.skipped",
  "skills.matched",
  "skills.recommendation",
  "skill.create.queued",
  "skill.model.authoring",
  "skill.model.authored",
  "skill.home.saved",
  "skill.project.saving",
  "skill.project.saved",
  "skill.local.write_back",
  "skill.local.write_back.completed",
  "skill.local.write_back.skipped",
  "skill.create.completed",
  "generation.recovered",
  "generation.incomplete",
  "generation.failed",
]);
const CHAT_PROGRESS_HIDDEN_PREFIXES = [
  "stage.",
  "graph.",
  "adk.",
  "google_adk.",
  "tool_contract.",
  "tool_calling.",
  "gemini_tool_calling.",
  "runtime.projection.",
  "generate_website_artifact.",
  "artifact.validation",
  "legacy_generation.",
];

function getWorkspaceLayoutMode(width) {
  if (width <= WORKSPACE_MOBILE_MAX) return "mobile";
  if (width <= WORKSPACE_TABLET_MAX) return "tablet";
  return "desktop";
}

function App() {
  const layoutRef = useRef(null);
  const browserDirectoryHandlesRef = useRef(new Map());
  const pendingBrowserDirectoryHandlesRef = useRef(new Map());
  const generationAbortControllerRef = useRef(null);
  const generationProjectIdRef = useRef("");
  const generationV1RunIdRef = useRef("");
  const folderAccessFlowRef = useRef(null);
  const [leftPanelWidth, setLeftPanelWidth] = useState(260);
  const [rightPanelWidth, setRightPanelWidth] = useState(520);
  const [isLeftPanelOpen, setIsLeftPanelOpen] = useState(true);
  const [isRightPanelOpen, setIsRightPanelOpen] = useState(true);
  const [session, setSession] = useState(null);
  const [sessionUsage, setSessionUsage] = useState(null);
  const [authScreen, setAuthScreen] = useState(null);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isAdminPanelOpen, setIsAdminPanelOpen] = useState(false);
  const [projects, setProjects] = useState([]);
  const [activeProject, setActiveProject] = useState(null);
  const [files, setFiles] = useState([]);
  const [selectedPath, setSelectedPath] = useState("");
  const [editorValue, setEditorValue] = useState("");
  const [savedValue, setSavedValue] = useState("");
  const [prompt, setPrompt] = useState("");
  const [promptAttachments, setPromptAttachments] = useState([]);
  const [selectedModel, setSelectedModel] = useState("gemini-3.5-flash");
  const [isProjectSearchOpen, setIsProjectSearchOpen] = useState(false);
  const [projectSearchQuery, setProjectSearchQuery] = useState("");
  const [messagesByProjectId, setMessagesByProjectId] = useState({});
  const [conversationStateByProjectId, setConversationStateByProjectId] = useState({});
  const [episodicMemoriesByProjectId, setEpisodicMemoriesByProjectId] = useState({});
  const [chatSessionByProjectId, setChatSessionByProjectId] = useState(() => loadStoredChatSessions());
  const [events, setEvents] = useState([]);
  const [liveProgress, setLiveProgress] = useState([]);
  const [streamingAssistantText, setStreamingAssistantText] = useState("");
  const [liveWrittenPaths, setLiveWrittenPaths] = useState([]);
  const [patchDiffByProjectId, setPatchDiffByProjectId] = useState({});
  const [patchApprovalByProjectId, setPatchApprovalByProjectId] = useState({});
  const [editorJumpLine, setEditorJumpLine] = useState(null);
  const monacoEditorRef = useRef(null);
  const workspaceSyncAtRef = useRef(new Map());
  const [previewUrl, setPreviewUrl] = useState("");
  const [previewVersionId, setPreviewVersionId] = useState("");
  const [buildLog, setBuildLog] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isCancellingGeneration, setIsCancellingGeneration] = useState(false);
  const [isBuilding, setIsBuilding] = useState(false);
  const [isDirectoryBusy, setIsDirectoryBusy] = useState(false);
  const [isNewProjectModalOpen, setIsNewProjectModalOpen] = useState(false);
  const [folderAccessUi, setFolderAccessUi] = useState(null);
  const [localDirectoryName, setLocalDirectoryName] = useState("");
  const [browserWorkspaces, setBrowserWorkspaces] = useState(() => loadStoredBrowserWorkspaces());
  const [pendingBrowserPermissionProjectId, setPendingBrowserPermissionProjectId] = useState("");
  const [, setBrowserDirectoryHandleRevision] = useState(0);
  const [deletingProjectId, setDeletingProjectId] = useState("");
  const [error, setError] = useState("");
  const [localHelperCheck, setLocalHelperCheck] = useState({
    status: "idle",
    message: "",
    details: "",
    startupCommand: "",
  });
  const [isDownloadingProject, setIsDownloadingProject] = useState(false);
  const [skillsRefreshToken, setSkillsRefreshToken] = useState(0);
  const [viewportWidth, setViewportWidth] = useState(() => (typeof window !== "undefined" ? window.innerWidth : 1280));
  const layoutMode = getWorkspaceLayoutMode(viewportWidth);
  const isCompactWorkspace = layoutMode !== "desktop";
  const layoutModeRef = useRef(layoutMode);

  const selectedFile = useMemo(
    () => files.find((file) => file.path === selectedPath && !isHiddenProjectFilePath(file.path)),
    [files, selectedPath],
  );
  const messages = useMemo(() => {
    if (!activeProject) return defaultMessages();
    return messagesByProjectId[activeProject.id] || defaultMessages();
  }, [activeProject, messagesByProjectId]);
  const activeBrowserWorkspace = activeProject ? browserWorkspaces[activeProject.id] : null;
  const conversationState = activeProject ? conversationStateByProjectId[activeProject.id] : null;
  const episodicMemories = activeProject ? episodicMemoriesByProjectId[activeProject.id] || [] : [];
  const hasUnsavedChanges = Boolean(selectedPath && editorValue !== savedValue);
  const effectiveLeftPanelWidth = layoutMode === "tablet" ? Math.min(leftPanelWidth, 240) : leftPanelWidth;
  const effectiveRightPanelWidth = layoutMode === "tablet" ? Math.min(rightPanelWidth, 400) : rightPanelWidth;
  const layoutColumns = isCompactWorkspace
    ? "minmax(0, 1fr)"
    : `${isLeftPanelOpen ? effectiveLeftPanelWidth : COLLAPSED_PANEL_WIDTH}px ${
        isLeftPanelOpen ? PANEL_RESIZER_WIDTH : 0
      }px minmax(0, 1fr) ${isRightPanelOpen ? PANEL_RESIZER_WIDTH : 0}px ${
        isRightPanelOpen ? effectiveRightPanelWidth : COLLAPSED_PANEL_WIDTH
      }px`;

  useEffect(() => {
    function handleViewportResize() {
      setViewportWidth(window.innerWidth);
    }
    handleViewportResize();
    window.addEventListener("resize", handleViewportResize);
    return () => window.removeEventListener("resize", handleViewportResize);
  }, []);

  useEffect(() => {
    if (layoutModeRef.current === layoutMode) return;
    if (layoutMode === "mobile") {
      setIsLeftPanelOpen(false);
      setIsRightPanelOpen(false);
    }
    layoutModeRef.current = layoutMode;
  }, [layoutMode]);

  useEffect(() => {
    clearLegacyAuthToken();
    if (getAuthToken()) {
      bootstrap();
      return;
    }
    setAuthScreen("login");
    setIsLoading(false);
  }, []);

  useEffect(() => {
    storeBrowserWorkspaces(browserWorkspaces);
  }, [browserWorkspaces]);

  useEffect(() => {
    if (!activeProject?.id) {
      setPendingBrowserPermissionProjectId("");
      return undefined;
    }
    const workspace = browserWorkspaces[activeProject.id];
    if (!workspace || workspace.kind !== "directory" || activeProject.local_path) {
      setPendingBrowserPermissionProjectId("");
      return undefined;
    }
    let cancelled = false;
    restoreStoredBrowserDirectoryConnection(activeProject).then((status) => {
      if (cancelled) return;
      setPendingBrowserPermissionProjectId(status === "prompt" ? activeProject.id : "");
    });
    return () => {
      cancelled = true;
    };
  }, [activeProject?.id, activeProject?.local_path, browserWorkspaces]);

  useEffect(() => {
    if (!pendingBrowserPermissionProjectId) return undefined;
    const directoryHandle = pendingBrowserDirectoryHandlesRef.current.get(pendingBrowserPermissionProjectId);
    if (!directoryHandle?.requestPermission) return undefined;
    let attempted = false;
    const requestPermissionFromUserGesture = (event) => {
      if (attempted) return;
      if (event?.target instanceof Element && event.target.closest("[data-browser-folder-reconnect]")) return;
      attempted = true;
      window.removeEventListener("pointerdown", requestPermissionFromUserGesture, true);
      window.removeEventListener("keydown", requestPermissionFromUserGesture, true);
      directoryHandle
        .requestPermission({ mode: "readwrite" })
        .then((permission) => {
          if (permission !== "granted") return;
          activateBrowserDirectoryHandle(pendingBrowserPermissionProjectId, directoryHandle);
        })
        .catch(() => {
          // The explicit reconnect action remains available if the browser rejects background restoration.
        })
        .finally(() => {
          setPendingBrowserPermissionProjectId("");
        });
    };
    window.addEventListener("pointerdown", requestPermissionFromUserGesture, true);
    window.addEventListener("keydown", requestPermissionFromUserGesture, true);
    return () => {
      window.removeEventListener("pointerdown", requestPermissionFromUserGesture, true);
      window.removeEventListener("keydown", requestPermissionFromUserGesture, true);
    };
  }, [pendingBrowserPermissionProjectId]);

  async function bootstrap() {
    setIsLoading(true);
    setError("");
    try {
      const [sessionPayload, projectsPayload, capabilitiesPayload] = await Promise.all([
        api("/api/session"),
        api("/api/projects"),
        api("/api/v1/platform/capabilities").catch(() => null),
      ]);
      if (capabilitiesPayload?.stream?.use_v1_runs_stream === true) {
        platformStreamConfigRef.useV1RunsStream = true;
      }
      setSession(sessionPayload.user);
      setSessionUsage(sessionPayload.usage || sessionPayload.user?.usage || null);
      setAuthScreen(null);
      if (sessionPayload.user?.id) {
        window.localStorage.setItem(CLIENT_USER_ID_KEY, sessionPayload.user.id);
      }
      const nextProjects = projectsForSession(projectsPayload.projects || [], sessionPayload.user);
      setProjects(nextProjects);
      const userId = sessionPayload.user?.id;
      if (userId) {
        window.localStorage.setItem(CLIENT_USER_ID_KEY, userId);
      }
      const resumeProject = resolveResumeProject(nextProjects, userId);
      if (resumeProject) {
        await openProject(resumeProject, { refreshProjects: false });
      }
    } catch (nextError) {
      if (isAuthError(nextError)) {
        clearAuthToken();
        setSession(null);
        setAuthScreen("login");
        setError("Your session expired. Sign in again.");
      } else {
        setError(nextError.message);
      }
    } finally {
      setIsLoading(false);
    }
  }

  async function handleLogin({ email, password }) {
    setIsLoading(true);
    setError("");
    try {
      const payload = await api("/api/auth/login", {
        method: "POST",
        body: { email, password },
        skipAuth: true,
      });
      setAuthToken(payload.token);
      setSession(payload.user);
      setSessionUsage(payload.usage || payload.user?.usage || null);
      setAuthScreen(null);
      await bootstrap();
    } catch (nextError) {
      setError(nextError.message);
      setIsLoading(false);
    }
  }

  async function handleSignup() {
    setError("Accounts are created by your administrator. Use the credentials they shared with you to sign in.");
  }

  function handleLogout() {
    clearAuthToken();
    setSession(null);
    setSessionUsage(null);
    setProjects([]);
    setActiveProject(null);
    setFiles([]);
    setSelectedPath("");
    setMessagesByProjectId({});
    setConversationStateByProjectId({});
    setEpisodicMemoriesByProjectId({});
    setChatSessionByProjectId({});
    setAuthScreen("login");
    setIsSettingsOpen(false);
    setIsAdminPanelOpen(false);
    setError("");
  }

  const refreshSessionUsage = useCallback(async ({ recentRequestLimit } = {}) => {
    try {
      const hasRequestedLimit = recentRequestLimit !== null && recentRequestLimit !== undefined && recentRequestLimit !== "";
      const normalizedLimit = hasRequestedLimit && Number.isFinite(Number(recentRequestLimit))
        ? Math.max(1, Math.min(TOKEN_USAGE_EXPANDED_REQUEST_LIMIT, Number(recentRequestLimit)))
        : null;
      const usagePath = normalizedLimit
        ? `/api/users/me/usage?recent_request_limit=${normalizedLimit}`
        : "/api/users/me/usage";
      const usage = await api(usagePath);
      setSessionUsage(usage);
      setSession((current) => (current ? { ...current, usage } : current));
      return usage;
    } catch (usageError) {
      console.warn("Usage refresh failed:", usageError);
      throw usageError;
    }
  }, []);

  async function handleProfileUpdate(updates) {
    setIsLoading(true);
    setError("");
    try {
      const payload = await api("/api/users/me", {
        method: "PATCH",
        body: updates,
      });
      setSession(payload.user);
      setIsSettingsOpen(false);
    } catch (nextError) {
      setError(nextError.message);
      throw nextError;
    } finally {
      setIsLoading(false);
    }
  }

  function openNewProjectModal() {
    setLocalHelperCheck({
      status: "idle",
      message: "",
      details: "",
      startupCommand: "",
    });
    setIsNewProjectModalOpen(true);
    setError("");
  }

  async function checkLocalHelper() {
    const startupCommand = localSkillsHelperCommand();
    setLocalHelperCheck({
      status: "checking",
      message: "Checking this browser's local helper at 127.0.0.1:8799.",
      details: "",
      startupCommand: "",
    });
    try {
      const payload = await fetchLocalSkillsHelper("/health");
      setLocalHelperCheck({
        status: "healthy",
        message: `This customer machine can reach the local helper at ${LOCAL_SKILLS_HELPER_URL}.`,
        details: [
          payload.service ? `Service: ${payload.service}` : "",
          payload.home ? `Home: ${payload.home}` : "",
          payload.skills_dir ? `Skills dir: ${payload.skills_dir}` : "",
        ]
          .filter(Boolean)
          .join(" | "),
        startupCommand: "",
      });
      setError("");
      return payload;
    } catch (nextError) {
      const message = `The local helper is not reachable at ${LOCAL_SKILLS_HELPER_URL}. ${nextError.message}`;
      const details = `Run this in the customer/user terminal, not only on the Worktual server: ${startupCommand}`;
      setLocalHelperCheck({
        status: "unhealthy",
        message,
        details,
        startupCommand,
      });
      setError(`${message} ${details}`);
      if (activeProject?.id) {
        await recordLocalEnvironmentError(activeProject.id, {
          operation: "check_local_helper",
          message: nextError.message,
          workspaceName: browserWorkspaces[activeProject.id]?.name || activeProject?.name || "",
          workspaceKind: browserWorkspaces[activeProject.id]?.kind || "local_helper",
          helperUrl: LOCAL_SKILLS_HELPER_URL,
          recommendedAction: `Start the Worktual local skills helper in the customer/user terminal before importing a local project: ${startupCommand}`,
          details: {
            error: nextError.message,
            helper_url: LOCAL_SKILLS_HELPER_URL,
            startup_command: startupCommand,
          },
        });
      }
      return null;
    }
  }

  async function createProject({ workspaceMode = "backend", localPath = "", name = DEFAULT_PROJECT_NAME } = {}) {
    setIsCreating(true);
    setError("");
    try {
      const payload = await api("/api/projects", {
        method: "POST",
        body: {
          name: name.trim() || DEFAULT_PROJECT_NAME,
          description:
            workspaceMode === "local"
              ? "Local filesystem workspace project."
              : "Backend runtime workspace project.",
          workspace_mode: workspaceMode,
          ...(localPath ? { local_path: localPath } : {}),
        },
      });
      const project = payload.project;
      setProjects((current) => [project, ...current.filter((item) => item.id !== project.id)]);
      if (workspaceMode === "local") {
        setLocalDirectoryName(pathBaseName(project.local_path || localPath));
      } else {
        setLocalDirectoryName("");
      }
      if (payload.files?.length) {
        applySyncedFiles(payload.files);
      }
      await openProject(project, { refreshProjects: false });
      if (workspaceMode === "local") {
        appendProjectMessage(project.id, {
          role: "assistant",
          content: `Linked local folder: ${project.local_path || localPath}`,
        });
      } else {
        appendProjectMessage(project.id, {
          role: "assistant",
          content: "Started a backend workspace. Files will stay in the backend project store and preview runtime until you link a local folder.",
        });
      }
      setIsNewProjectModalOpen(false);
    } catch (nextError) {
      setError(nextError.message);
    } finally {
      setIsCreating(false);
    }
  }

  async function deleteProject(project) {
    if (!project || deletingProjectId) return;
    if (!window.confirm(`Delete ${project.name}? This removes the project and generated preview builds.`)) return;
    setDeletingProjectId(project.id);
    setError("");
    try {
      await api(`/api/projects/${project.id}`, { method: "DELETE" });
      const remainingProjects = projects.filter((item) => item.id !== project.id);
      setProjects(remainingProjects);
      setMessagesByProjectId((current) => {
        const next = { ...current };
        delete next[project.id];
        return next;
      });
      setConversationStateByProjectId((current) => {
        const next = { ...current };
        delete next[project.id];
        return next;
      });
      setEpisodicMemoriesByProjectId((current) => {
        const next = { ...current };
        delete next[project.id];
        return next;
      });
      setChatSessionByProjectId((current) => {
        const next = { ...current };
        delete next[project.id];
        clearStoredChatSessionId(project.id);
        return next;
      });
      browserDirectoryHandlesRef.current.delete(project.id);
      pendingBrowserDirectoryHandlesRef.current.delete(project.id);
      deleteStoredBrowserDirectoryHandle(project.id).catch(() => {});
      setBrowserWorkspaces((current) => {
        const next = { ...current };
        delete next[project.id];
        return next;
      });
      if (activeProject?.id === project.id) {
        if (remainingProjects[0]) {
          await openProject(remainingProjects[0], { refreshProjects: false });
        } else {
          clearWorkspace();
        }
      }
    } catch (nextError) {
      setError(nextError.message);
    } finally {
      setDeletingProjectId("");
    }
  }

  async function openProject(project, options = {}) {
    setActiveProject(project);
    const userId = session?.id || getStoredUserId();
    if (userId && project?.id) {
      setLastActiveProjectId(userId, project.id);
    }
    setLocalDirectoryName(pathBaseName(project.local_path || browserWorkspaces[project.id]?.name || ""));
    setPreviewUrl("");
    setBuildLog("");
    setLiveProgress([]);
    setError("");
    try {
      if (options.refreshProjects !== false) {
        const projectsPayload = await api("/api/projects");
        setProjects(projectsForSession(projectsPayload.projects || [], session));
      }
      const [filesPayload, eventsPayload] = await Promise.all([
        api(`/api/projects/${project.id}/files`),
        api(`/api/events?project_id=${encodeURIComponent(project.id)}`),
      ]);
      await loadProjectChatHistory(project.id);
      const nextFiles = filesPayload.files || [];
      setFiles(nextFiles);
      setEvents(eventsPayload.events || []);
      const preferred = nextFiles.find((file) => file.path === "src/App.jsx") || nextFiles[0];
      selectFile(preferred, nextFiles);
    } catch (nextError) {
      setError(nextError.message);
    }
  }

  function selectFile(file, sourceFiles = files) {
    if (!file || isHiddenProjectFilePath(file.path)) {
      setSelectedPath("");
      setEditorValue("");
      setSavedValue("");
      return;
    }
    const nextFile = sourceFiles.find((item) => item.path === file.path) || file;
    setSelectedPath(nextFile.path);
    setEditorValue(nextFile.content || "");
    setSavedValue(nextFile.content || "");
  }

  function selectFileAtLine(path, line = 1) {
    if (!path) return;
    const targetLine = Number.isFinite(Number(line)) ? Math.max(1, Number(line)) : 1;
    const nextFile = files.find((item) => item.path === path);
    if (!nextFile) return;
    setEditorJumpLine(targetLine);
    setIsRightPanelOpen(true);
    selectFile(nextFile);
  }

  function handleEditorMount(editor) {
    monacoEditorRef.current = editor;
    revealEditorLine(editor, editorJumpLine);
  }

  function revealEditorLine(editor, line) {
    if (!editor || !line) return;
    editor.revealLineInCenter(line);
    editor.setPosition({ lineNumber: line, column: 1 });
    editor.focus();
  }

  useEffect(() => {
    if (!editorJumpLine || !monacoEditorRef.current || !selectedPath) return;
    revealEditorLine(monacoEditorRef.current, editorJumpLine);
    setEditorJumpLine(null);
  }, [selectedPath, editorJumpLine]);

  function closeSelectedFile() {
    if (hasUnsavedChanges && !window.confirm("Close this file with unsaved changes?")) return;
    selectFile(null);
  }

  async function saveCurrentFile() {
    if (!activeProject || !selectedPath || !hasUnsavedChanges) return null;
    setIsSaving(true);
    setError("");
    try {
      const payload = await api(`/api/projects/${activeProject.id}/files/${encodePath(selectedPath)}`, {
        method: "PUT",
        body: { content: editorValue },
      });
      const savedFile = payload.file;
      setFiles((current) => current.map((file) => (file.path === savedFile.path ? { ...file, ...savedFile } : file)));
      setSavedValue(savedFile.content);
      try {
        const browserSync = await writeProjectFilesToBrowserWorkspace(activeProject.id, [savedFile]);
        if (!browserSync) {
          const writeBackNotice = browserWorkspaceWriteBackNotice(activeProject.id);
          if (writeBackNotice) setError(writeBackNotice);
        } else {
          appendProjectMessage(activeProject.id, {
            role: "assistant",
            content: localWriteBackMessage(browserSync, [savedFile]),
          });
        }
      } catch (syncError) {
        setError(`Saved in backend, but system folder write failed: ${syncError.message}`);
      await recordLocalEnvironmentError(activeProject.id, {
        operation: "save_file_browser_write_back",
        message: syncError.message,
        workspaceName: browserWorkspaces[activeProject.id]?.name,
        workspaceKind: browserWorkspaces[activeProject.id]?.kind,
        recommendedAction: "Use terminal helper actions to inspect folder permissions and rerun local validation after fixing write access.",
      });
      }
      await refreshEvents(activeProject.id);
      return savedFile;
    } catch (nextError) {
      setError(nextError.message);
      throw nextError;
    } finally {
      setIsSaving(false);
    }
  }

  async function generateWebsite(event) {
    event.preventDefault();
    if (isGenerating) {
      if (isCancellingGeneration) return;
      await stopWebsiteGeneration();
      return;
    }
    if (!prompt.trim() && !promptAttachments.length) return;
    await submitWebsitePrompt(prompt.trim(), {}, promptAttachments);
  }

  async function stopWebsiteGeneration() {
    if (!isGenerating || isCancellingGeneration) return;
    const projectId = generationProjectIdRef.current || activeProject?.id;
    if (!projectId) return;
    setIsCancellingGeneration(true);
    setError("");
    setLiveProgress((current) =>
      mergeLiveProgress(completeRunningLiveProgress(current), {
        step: "generation.cancelling",
        message: "Requesting backend cancellation…",
        status: "running",
        created_at: new Date().toISOString(),
      }),
    );

    try {
      const cancelPayload = shouldUseV1RunsStream()
        ? await api("/api/v1/runs/cancel", {
            method: "POST",
            body: {
              workspace_id: projectId,
              run_id: generationV1RunIdRef.current || null,
            },
          })
        : await api(`/api/projects/${encodeURIComponent(projectId)}/generate/cancel`, { method: "POST" });

      let backendStopped = Boolean(cancelPayload?.stopped);
      for (let attempt = 0; !backendStopped && attempt < 370; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 500));
        const statusPayload = await api(`/api/projects/${encodeURIComponent(projectId)}/generate/status`);
        backendStopped = Boolean(statusPayload?.stopped);
      }

      if (!backendStopped) {
        const message =
          "Cancellation was requested, but the backend is still finishing the active model call. The workspace will remain locked until it exits.";
        setError(message);
        setLiveProgress((current) =>
          mergeLiveProgress(current, {
            step: "generation.cancelling",
            message,
            status: "running",
            created_at: new Date().toISOString(),
          }),
        );
        return;
      }

      generationAbortControllerRef.current?.abort();
      setIsGenerating(false);
      setStreamingAssistantText("");
      setLiveWrittenPaths([]);
    } catch (cancelError) {
      const message = `Backend cancellation failed: ${cancelError.message}`;
      setError(message);
      setLiveProgress((current) =>
        mergeLiveProgress(current, {
          step: "generation.cancel.failed",
          message,
          status: "failed",
          created_at: new Date().toISOString(),
        }),
      );
    } finally {
      setIsCancellingGeneration(false);
    }
  }

  function isGenerationCancelledError(error) {
    return (
      Boolean(error?.cancelled) ||
      error?.name === "AbortError" ||
      error?.generationError?.category === "cancellation" ||
      error?.generationError?.code === "generation_cancelled"
    );
  }

  async function ensureBackendProjectForChat() {
    if (activeProject) return activeProject;
    const payload = await api("/api/projects", {
      method: "POST",
      body: {
        name: DEFAULT_PROJECT_NAME,
        description: "Backend runtime workspace project.",
        workspace_mode: "backend",
      },
    });
    const project = payload.project;
    setProjects((current) => [project, ...current.filter((item) => item.id !== project.id)]);
    setActiveProject(project);
    setLocalDirectoryName("");
    if (payload.files?.length) {
      applySyncedFiles(payload.files);
    } else {
      applySyncedFiles([]);
    }
    setIsNewProjectModalOpen(false);
    const userId = session?.id || getStoredUserId();
    if (userId) {
      setLastActiveProjectId(userId, project.id);
    }
    await persistProjectMessage(project.id, {
      role: "assistant",
      content:
        "Started a backend workspace. You can chat normally for code, debugging, or website ideas — linking a local folder is optional.",
    });
    await loadProjectChatHistory(project.id);
    return project;
  }

  async function syncWorkspaceToBackend(projectId, { force = false } = {}) {
    const project = activeProject?.id === projectId ? activeProject : projects.find((item) => item.id === projectId);
    const lastSync = workspaceSyncAtRef.current.get(projectId) || 0;
    if (!force && Date.now() - lastSync < 45_000) {
      return { source: "cached", count: 0, skipped: true, reason: "recent_sync" };
    }
    const directoryHandle = browserDirectoryHandlesRef.current.get(projectId);
    const workspace = browserWorkspaces[projectId];
    if (project?.local_path && (!directoryHandle || workspace?.kind !== "directory")) {
      workspaceSyncAtRef.current.set(projectId, Date.now());
      return {
        source: "backend_preflight",
        count: 0,
        skipped: true,
        reason: "linked_local_folder",
        name: pathBaseName(project.local_path),
      };
    }
    if (directoryHandle && workspace?.kind === "directory") {
      await ensureBrowserDirectoryPermission(directoryHandle);
      const snapshot = await readBrowserProjectDirectory(directoryHandle);
      if (snapshot.files.length) {
        const payload = await api(`/api/projects/${projectId}/import-directory`, {
          method: "POST",
          body: { files: snapshot.files },
        });
        applySyncedFiles(payload.files || []);
        workspaceSyncAtRef.current.set(projectId, Date.now());
        return {
          source: "browser",
          count: snapshot.files.length,
          name: workspace.name || directoryHandle.name,
        };
      }
    }
    if (project?.local_path) {
      const payload = await api(`/api/projects/${projectId}/sync-local`, {
        method: "POST",
        body: { direction: "pull" },
      });
      applySyncedFiles(payload.files || []);
      workspaceSyncAtRef.current.set(projectId, Date.now());
      return {
        source: "local",
        count: payload.files?.length || 0,
        name: pathBaseName(project.local_path),
      };
    }
    return null;
  }

  async function submitWebsitePrompt(nextPrompt, action = {}, attachments = []) {
    const outgoingAttachments = Array.isArray(attachments) ? attachments : [];
    const effectivePrompt =
      nextPrompt ||
      (outgoingAttachments.length
        ? "Use the attached screenshot or files to diagnose the issue and update the project accordingly."
        : "");
    if (!effectivePrompt && !outgoingAttachments.length) return;
    if (isCancelPendingExecutionPrompt(nextPrompt) && activeProject && hasPendingConfirmation(activeProject.id)) {
      await handleChatAction(nextPrompt, { type: "cancel_confirmation" });
      return;
    }
    if (isGenerating) return;
    let project = activeProject;
    if (!project) {
      try {
        project = await ensureBackendProjectForChat();
      } catch (nextError) {
        setError(nextError.message);
        return;
      }
    }
    const projectId = project.id;
    if (isCreateSkillPrompt(effectivePrompt)) {
      setIsGenerating(true);
      setError("");
      setPrompt("");
      revokePromptAttachmentUrls(outgoingAttachments);
      setPromptAttachments([]);
      setLiveProgress([
        skillProgressEvent("skill.create.queued", "Preparing the skill creation request.", "running", {
          model: selectedModel || "server-default",
        }),
      ]);
      appendProjectMessage(projectId, { role: "user", content: effectivePrompt }, { persist: false });
      try {
        setLiveProgress((current) =>
          mergeLiveProgress(
            current,
            skillProgressEvent(
              "skill.model.authoring",
              "Sending the request to the selected model so it can write the skill workflow, analysis guidance, and web-search instructions.",
              "running",
              { model: selectedModel || "server-default" }
            )
          )
        );
        const payload = await createSkillFromPrompt(effectivePrompt, project, selectedModel);
        setLiveProgress((current) =>
          mergeLiveProgress(
            current,
            skillProgressEvent("skill.model.authored", `The model authored /${payload.name} and returned the skill content.`, "completed", {
              skill: payload.name,
              path: payload.project_file?.path,
              model_authored: payload.model_authored,
            })
          )
        );
        setLiveProgress((current) =>
          mergeLiveProgress(
            current,
            skillProgressEvent("skill.home.saved", `Saved /${payload.name} under the user's skills home.`, "completed", {
              skill: payload.name,
              path: payload.path,
              home: payload.home,
            })
          )
        );
        setLiveProgress((current) =>
          mergeLiveProgress(
            current,
            skillProgressEvent("skill.project.saving", `Saving /${payload.name} into this project's .worktual skills folder.`, "running", {
              skill: payload.name,
              path: payload.project_file?.path,
            })
          )
        );
        const syncedProjectSkill = await persistCreatedSkillProjectFile(
          projectId,
          payload.project_file,
          (progressEvent) => {
            setLiveProgress((current) => mergeLiveProgress(current, progressEvent));
          },
          payload.saved_project_file || null
        );
        const syncedProjectFiles = [];
        if (syncedProjectSkill) {
          syncedProjectFiles.push(syncedProjectSkill);
        }
        if (payload.project_index_file) {
          const indexPayload = payload.saved_project_index || payload.project_index_file;
          if (indexPayload?.path) {
            try {
              await writeProjectFilesToBrowserWorkspace(projectId, [indexPayload]);
            } catch (indexWriteError) {
              console.warn("Created skill index saved in backend, but local folder write failed:", indexWriteError);
            }
            syncedProjectFiles.push(indexPayload);
          }
        }
        if (syncedProjectFiles.length) {
          applySyncedFiles(
            [
              ...(files || []).filter(
                (file) => !syncedProjectFiles.some((synced) => synced.path === file.path),
              ),
              ...syncedProjectFiles,
            ],
            syncedProjectSkill?.path || syncedProjectFiles[0]?.path,
          );
        }
        if (payload.user_home_files?.length) {
          setLiveProgress((current) =>
            mergeLiveProgress(
              current,
              skillProgressEvent("skill.home.installing", `Installing /${payload.name} into this folder's skills home.`, "running", {
                skill: payload.name,
              }),
            ),
          );
          const homeSync = await installSkillsToUserHome(payload);
          setLiveProgress((current) =>
            mergeLiveProgress(
              current,
              skillProgressEvent(
                homeSync?.status === "completed" ? "skill.home.installed" : "skill.home.install_failed",
                homeSync?.status === "completed"
                  ? `Installed /${payload.name} in ${homeSync.folder || "the local skills folder"}.`
                  : homeSync?.reason || "Local skills home installation was skipped.",
                homeSync?.status === "completed" ? "completed" : "failed",
                { skill: payload.name, home_sync: homeSync },
              ),
            ),
          );
        }
        setSkillsRefreshToken((current) => current + 1);
        setLiveProgress((current) =>
          mergeLiveProgress(
            current,
            skillProgressEvent("skill.create.completed", `Finished creating /${payload.name}. Next step: invoke it from chat with /${payload.name}.`, "completed", {
              skill: payload.name,
              path: payload.project_file?.path,
            })
          )
        );
        appendProjectMessage(projectId, {
          role: "assistant",
          content: `${payload.message}. Also added ${payload.project_file?.path || ".worktual/skills"} to this project. You can now invoke it with /${payload.name}.`,
        });
      } catch (nextError) {
        setLiveProgress((current) =>
          mergeLiveProgress(
            current,
            skillProgressEvent("generation.failed", `Skill creation failed: ${nextError.message}`, "failed")
          )
        );
        appendProjectMessage(projectId, { role: "assistant", content: `Skill creation failed: ${nextError.message}` });
        setError(nextError.message);
      } finally {
        setIsGenerating(false);
      }
      return;
    }
    setIsGenerating(true);
    setIsCancellingGeneration(false);
    setError("");
    setPrompt("");
    setPreviewUrl("");
    setBuildLog("");
    setLiveProgress([
      {
        id: "request-queued",
        step: "request.queued",
        message: "Sending prompt to backend",
        status: "running",
        created_at: new Date().toISOString(),
      },
    ]);
    setStreamingAssistantText("");
    setLiveWrittenPaths([]);
    try {
      await renameProjectFromPromptIfNeeded(project, effectivePrompt);
    } catch (renameError) {
      setError(`Project name update failed: ${renameError.message}`);
    }
    const preparedAttachments = await prepareOutgoingAttachments(outgoingAttachments);
    appendProjectMessage(
      projectId,
      {
        role: "user",
        content: effectivePrompt,
        attachments: preparedAttachments,
      },
      {
        persist: false,
        metadata: preparedAttachments.length ? { attachments: preparedAttachments } : {},
      },
    );
    revokePromptAttachmentUrls(outgoingAttachments);
    setPromptAttachments([]);
    const abortController = new AbortController();
    generationAbortControllerRef.current = abortController;
    generationProjectIdRef.current = projectId;
    generationV1RunIdRef.current = "";
    let streamHadSavedProgress = false;
    let streamLastSavedStep = "";
    try {
      if (!isCreateSkillPrompt(effectivePrompt)) {
        setLiveProgress((current) =>
          mergeLiveProgress(current, {
            step: "workspace.sync.started",
            message: "Loading your latest project files before planning",
            status: "running",
            created_at: new Date().toISOString(),
          }),
        );
        const workspaceSync = await syncWorkspaceToBackend(projectId);
        if (workspaceSync?.count) {
          setLiveProgress((current) =>
            mergeLiveProgress(completeRunningLiveProgress(current), {
              step: "workspace.sync.completed",
              message:
                workspaceSync.source === "browser"
                  ? `Loaded ${workspaceSync.count} files from ${workspaceSync.name}`
                  : workspaceSync.source === "local"
                    ? `Loaded ${workspaceSync.count} files from linked local folder`
                    : workspaceSync.skipped
                      ? `Using linked workspace (${workspaceSync.name || "local folder"}); backend will load files during planning`
                      : `Loaded ${workspaceSync.count} files`,
              status: "completed",
              detail: workspaceSync,
              created_at: new Date().toISOString(),
            }),
          );
        } else if (workspaceSync?.skipped) {
          setLiveProgress((current) =>
            mergeLiveProgress(completeRunningLiveProgress(current), {
              step: "workspace.sync.skipped",
              message: "Skipped redundant folder sync; backend loads the linked workspace during planning",
              status: "completed",
              detail: workspaceSync,
              created_at: new Date().toISOString(),
            }),
          );
        } else {
          setLiveProgress((current) => completeRunningLiveProgress(current));
        }
      }
      const liveSyncedPaths = new Set();
      const payload = await streamGeneration(projectId, effectivePrompt, selectedModel, async (progressEvent) => {
        if (abortController.signal.aborted) return;
        if (progressEvent?.step === "assistant.delta") {
          const delta = progressEvent?.detail?.delta || progressEvent?.message || "";
          if (delta) setStreamingAssistantText((current) => `${current}${delta}`.slice(0, 400));
          return;
        }
        setLiveProgress((current) => mergeLiveProgress(current, progressEvent));
        await applyRealtimeGenerationProgress(projectId, progressEvent);
        const progressStep = progressEvent?.step || "";
        const progressDetail = progressEvent?.detail || {};
        if (isSavedGenerationProgressStep(progressStep, progressEvent?.status)) {
          streamHadSavedProgress = true;
          streamLastSavedStep = progressStep;
        }
        if (progressStep === "file.diff.ready" || (progressStep === "patch.proposed" && Array.isArray(progressDetail.diffs))) {
          const diffDetail = visibleDiffDetail(progressDetail);
          if (diffDetail?.diffs?.length) {
            setPatchDiffByProjectId((current) => ({
              ...current,
              [projectId]: {
                ...diffDetail,
                staged: Boolean(progressDetail.staged),
                persisted: Boolean(progressDetail.persisted),
              },
            }));
          }
        }
        if (progressStep === "patch.approval.required") {
          const approvalDetail = progressDetail?.patch_approval || progressDetail;
          if (approvalDetail?.status === "pending" || approvalDetail?.diff_detail) {
            setPatchApprovalByProjectId((current) => ({ ...current, [projectId]: approvalDetail }));
            const diffDetail = visibleDiffDetail(approvalDetail?.diff_detail || progressDetail);
            if (diffDetail?.diffs?.length) {
              setPatchDiffByProjectId((current) => ({ ...current, [projectId]: diffDetail }));
            }
          }
        }
        if (["file.written", "files.materialized", "files.persisted", "patch.proposed"].includes(progressStep)) {
          const progressFiles = progressFilesFromDetail(progressDetail);
          progressFiles.forEach((file) => {
            if (file?.path) liveSyncedPaths.add(file.path);
          });
        }
      }, {
        confirmationAction: action?.type === "confirm_confirmation" ? "confirm" : action?.type === "cancel_confirmation" ? "cancel" : null,
        patchAction: action?.type === "approve_patch" ? "approve" : action?.type === "reject_patch" ? "reject" : null,
        attachments: attachmentsForGenerationApi(preparedAttachments),
        signal: abortController.signal,
        runIdRef: generationV1RunIdRef,
      });
      if (abortController.signal.aborted) {
        throw createGenerationCancelledError();
      }
      const generationMessage =
        payload.generation?.multi_agent_system?.conversation_response?.message ||
        "Generated project files from your prompt.";
      const confirmationStatus = payload.generation?.multi_agent_system?.conversation_response?.confirmation?.status || null;
      if (action?.type === "confirm_confirmation" && confirmationStatus !== "pending") {
        markPendingConfirmation(projectId, "confirmed");
      }
      const patchApproval =
        payload.patch_approval ||
        payload.generation?.multi_agent_system?.conversation_response?.patch_approval ||
        null;
      if (patchApproval?.status === "pending") {
        setPatchApprovalByProjectId((current) => ({ ...current, [projectId]: patchApproval }));
        const pendingDiff = visibleDiffDetail(patchApproval?.diff_detail);
        if (pendingDiff?.diffs?.length) {
          setPatchDiffByProjectId((current) => ({ ...current, [projectId]: pendingDiff }));
        }
      } else if (patchApproval?.status === "approved" || patchApproval?.status === "rejected") {
        setPatchApprovalByProjectId((current) => {
          const next = { ...current };
          delete next[projectId];
          return next;
        });
      }
      appendProjectMessage(
        projectId,
        {
          role: "assistant",
          content: generationMessage,
          confirmation: payload.generation?.multi_agent_system?.conversation_response?.confirmation || null,
          patch_approval: patchApproval?.status === "pending" ? patchApproval : null,
        },
        { persist: false },
      );
      const persistedFiles = payload.files || [];
      const generatedFiles = generatedWriteBackFilesFromPayload(payload);
      let filesToApply = persistedFiles.length ? persistedFiles : generatedFiles;
      try {
        const refreshedFiles = await refreshProjectFilesFromApi(projectId, {
          preferredPath: generatedFiles[0]?.path || selectedPath,
          merge: false,
        });
        if (refreshedFiles.length) {
          filesToApply = refreshedFiles;
        } else if (filesToApply.length) {
          applySyncedFiles(filesToApply, generatedFiles[0]?.path);
        }
      } catch (refreshError) {
        if (filesToApply.length) {
          applySyncedFiles(filesToApply, generatedFiles[0]?.path);
        } else {
          setError(`Generated files saved, but workspace refresh failed: ${refreshError.message}`);
        }
      }
      const generatedPreview = previewVersionFromGenerationPayload(payload);
      if (generatedPreview?.preview_url && generatedPreview.status === "ready") {
        setPreviewUrl(cacheBustedApiUrl(generatedPreview.preview_url));
        setBuildLog(generatedPreview.build_log || "");
      }
      setLiveProgress((current) => completeRunningLiveProgress(current));
      setStreamingAssistantText("");
      setLiveWrittenPaths([]);
      setIsGenerating(false);
      void refreshSessionUsage();
      const unsyncedFiles = generatedFiles.filter((file) => file?.path && !liveSyncedPaths.has(file.path));
      if (unsyncedFiles.length) {
        await syncGeneratedFilesToBrowserWorkspace(projectId, unsyncedFiles);
      }
      void refreshEvents(projectId);
      void loadProjectChatHistory(projectId);
      if (payload.chat_session_id) {
        setStoredChatSessionId(projectId, payload.chat_session_id);
        setChatSessionByProjectId((current) => ({ ...current, [projectId]: payload.chat_session_id }));
      }
      if (payload.local_sync_error) {
        appendProjectMessage(projectId, {
          role: "assistant",
          content: `Generated files, but local disk sync failed: ${payload.local_sync_error}`,
        });
      }
    } catch (nextError) {
      if (isRecoverableGenerationStreamDisconnect(nextError) && streamHadSavedProgress) {
        try {
          const filesPayload = await api(`/api/projects/${encodeURIComponent(projectId)}/files`);
          applySyncedFiles(filesPayload.files || []);
          setLiveProgress((current) =>
            mergeLiveProgress(completeRunningLiveProgress(current), {
              step: "generation.recovered",
              message: "Code changes were saved. The live stream disconnected before the final response, so the workspace was refreshed.",
              status: "completed",
              detail: {
                recovered: true,
                last_saved_step: streamLastSavedStep,
                reason: nextError.message,
              },
              created_at: new Date().toISOString(),
            }),
          );
          appendProjectMessage(projectId, {
            role: "assistant",
            content: "Code changes were saved, but the live update stream disconnected before the final response. I refreshed the project files from the backend.",
          });
          setStreamingAssistantText("");
          setLiveWrittenPaths([]);
          setError("");
          void refreshEvents(projectId);
          void loadProjectChatHistory(projectId);
          void refreshSessionUsage();
        } catch (recoveryError) {
          const message = `${nextError.message} Also failed to refresh saved files: ${recoveryError.message}`;
          setLiveProgress((current) =>
            mergeLiveProgress(current, {
              step: "generation.failed",
              message,
              status: "failed",
              detail: { recovered: false, last_saved_step: streamLastSavedStep },
              created_at: new Date().toISOString(),
            }),
          );
          appendProjectMessage(projectId, { role: "assistant", content: `Generation finished saving files, but refresh failed: ${recoveryError.message}` });
          setError(message);
        }
      } else if (isGenerationCancelledError(nextError)) {
        setLiveProgress((current) =>
          mergeLiveProgress(completeRunningLiveProgress(current), {
            step: "generation.cancelled",
            message: "Generation stopped.",
            status: "completed",
            created_at: new Date().toISOString(),
          }),
        );
        appendProjectMessage(projectId, { role: "assistant", content: "Generation stopped." });
        setStreamingAssistantText("");
        setLiveWrittenPaths([]);
      } else {
        const failureDetail = nextError.generationError || {};
        if (failureDetail.code === "ai_credit_limit_exceeded") {
          window.alert(nextError.message || "You have completed your user limit.");
          void refreshSessionUsage();
        }
        setLiveProgress((current) =>
          mergeLiveProgress(current, {
            step: "generation.failed",
            message: nextError.message,
            status: "failed",
            detail: failureDetail,
            created_at: new Date().toISOString(),
          }),
        );
        appendProjectMessage(projectId, { role: "assistant", content: `Generation failed: ${nextError.message}` });
        setError(nextError.message);
      }
    } finally {
      generationAbortControllerRef.current = null;
      generationProjectIdRef.current = "";
      generationV1RunIdRef.current = "";
      setIsGenerating(false);
      setIsCancellingGeneration(false);
    }
  }

  function hasPendingConfirmation(projectId) {
    const existing = messagesByProjectId[projectId] || defaultMessages();
    return existing.some((message) => message.role === "assistant" && message.confirmation?.status === "pending");
  }

  async function previewWebsite() {
    if (!activeProject || isBuilding || isGenerating) return;
    const previewWindow = window.open("about:blank", "_blank");
    if (previewWindow) {
      previewWindow.document.title = "Building preview…";
      previewWindow.document.body.innerHTML =
        "<p style='font-family:Inter,sans-serif;padding:24px;color:#0f172a'>Building preview…</p>";
    }
    try {
      const version = await runPreviewBuild(activeProject.id, { allowFailed: true });
      if (version.status === "ready" && version.preview_url) {
        const url = cacheBustedApiUrl(version.preview_url);
        setPreviewUrl(url);
        setPreviewVersionId(version.id || "");
        try {
          const previewBase = String(version.preview_url || "").trim();
          if (previewBase) {
            sessionStorage.setItem(
              "worktual_active_preview_base",
              previewBase.endsWith("/") ? previewBase : `${previewBase}/`,
            );
            sessionStorage.setItem("worktual_active_preview_project", activeProject.id || "");
            sessionStorage.setItem("worktual_active_preview_version", version.id || "");
            sessionStorage.setItem("worktual_active_preview_at", String(Date.now()));
            localStorage.setItem(
              "worktual_active_preview_base",
              previewBase.endsWith("/") ? previewBase : `${previewBase}/`,
            );
            localStorage.setItem("worktual_active_preview_project", activeProject.id || "");
            localStorage.setItem("worktual_active_preview_version", version.id || "");
            localStorage.setItem("worktual_active_preview_at", String(Date.now()));
          }
        } catch {
          /* ignore storage failures */
        }
        if (previewWindow && !previewWindow.closed) {
          previewWindow.location.href = url;
          return;
        }
        const fallbackWindow = window.open(url, "_blank");
        if (!fallbackWindow) {
          setError("");
          appendProjectMessage(activeProject.id, {
            role: "assistant",
            content: `Preview is ready (version ${version.id || "latest"}).\nOpen: ${url}\n\nRefresh-safe URL — routes stay under /api/previews/ so you won't land on the Worktual login page.`,
          });
        }
        return;
      }

      const devOpened = await openDevPreviewFallback({
        projectId: activeProject.id,
        previewWindow,
        failedVersion: version,
      });
      if (devOpened) {
        setError("");
        appendProjectMessage(activeProject.id, {
          role: "assistant",
          content:
            "Production preview build failed, so I opened **dev preview** in a new tab instead.\n\n"
            + "Open DevTools (F12) → **Console** and copy any red errors here so I can fix them.\n\n"
            + formatPreviewBuildError(version, { includeLog: true }),
        });
        return;
      }
      throw new Error(formatPreviewBuildError(version));
    } catch (nextError) {
      if (previewWindow && !previewWindow.closed) {
        showPreviewFailurePage(previewWindow, nextError.message || "Preview failed.");
      }
      setError(nextError.message);
    }
  }

  async function openDevPreviewFallback({ projectId, previewWindow, failedVersion }) {
    try {
      if (previewWindow && !previewWindow.closed) {
        previewWindow.document.body.innerHTML =
          "<p style='font-family:Inter,sans-serif;padding:24px;color:#0f172a'>Build failed — starting Vite dev preview…</p>";
      }
      const payload = await api(`/api/projects/${projectId}/dev-preview`, { method: "POST" });
      const devUrl = String(payload?.dev_preview_url || "").trim();
      if (!devUrl || payload?.status !== "ready") {
        return false;
      }
      const url = devUrl.includes("?") ? devUrl : `${devUrl}${devUrl.endsWith("/") ? "" : "/"}?t=${Date.now()}`;
      setPreviewUrl(url);
      setPreviewVersionId("");
      setBuildLog(failedVersion?.build_log || "");
      if (previewWindow && !previewWindow.closed) {
        previewWindow.location.href = url;
        return true;
      }
      const fallbackWindow = window.open(url, "_blank");
      return Boolean(fallbackWindow);
    } catch (devError) {
      console.warn("Dev preview fallback failed:", devError);
      return false;
    }
  }

  function showPreviewFailurePage(previewWindow, message) {
    if (!previewWindow || previewWindow.closed) return;
    const safeMessage = String(message || "Preview failed.").replace(/</g, "&lt;");
    previewWindow.document.open();
    previewWindow.document.write(`<!doctype html>
<html><head><meta charset="utf-8"><title>Preview failed</title></head>
<body style="font-family:Inter,sans-serif;padding:24px;line-height:1.5;color:#0f172a;max-width:960px">
<h1 style="margin-top:0">Preview failed</h1>
<pre style="white-space:pre-wrap;background:#f8fafc;border:1px solid #e2e8f0;padding:16px;border-radius:8px">${safeMessage}</pre>
<p>Retry Preview in Worktual, or paste the browser console error into chat after dev preview opens.</p>
</body></html>`);
    previewWindow.document.close();
  }

  async function runPreviewBuild(projectId, { allowFailed = false } = {}) {
    if (hasUnsavedChanges) {
      await saveCurrentFile();
    }
    setIsBuilding(true);
    setError("");
    try {
      await syncWorkspaceToBackend(projectId);
      let version = await requestPreviewBuildVersion(projectId);
      if (version.status !== "ready" && isDependencyFailureLog(version.build_log || "")) {
        const repairedVersion = await repairLocalDependenciesForPreview(projectId, version);
        if (repairedVersion) {
          version = repairedVersion;
        }
      }
      if (version.status !== "ready") {
        if (allowFailed) {
          return version;
        }
        throw new Error(formatPreviewBuildError(version));
      }
      return version;
    } finally {
      setIsBuilding(false);
    }
  }

  async function requestPreviewBuildVersion(projectId) {
    const payload = await api(`/api/projects/${projectId}/build-preview`, { method: "POST" });
    const version = payload.version;
    setBuildLog(version.build_log || "");
    await refreshEvents(projectId);
    return version;
  }

  async function repairLocalDependenciesForPreview(projectId, failedVersion) {
    const project = activeProject?.id === projectId ? activeProject : projects.find((item) => item.id === projectId);
    const workspacePath = resolveLocalHelperWorkspacePath(projectId, project);
    if (!workspacePath) return null;

    setLiveProgress((current) =>
      mergeLiveProgress(current, {
        step: "local.dependencies.install",
        message: "Installing local dependencies and retrying the local build",
        status: "running",
        detail: { workspace: workspacePath, action: "frontend_install_and_build" },
        created_at: new Date().toISOString(),
      }),
    );

    try {
      const repair = await fetchLocalSkillsHelper("/run-action", {
        method: "POST",
        allowOkFalse: true,
        body: {
          action: "frontend_install_and_build",
          workspace: workspacePath,
          timeout_seconds: 1200,
        },
      });
      const repairSummary = terminalActionSummary(repair);
      setBuildLog((current) => appendBuildLogSection(current || failedVersion.build_log || "", "Local dependency repair", repairSummary));

      if (!repair.ok) {
        setLiveProgress((current) =>
          mergeLiveProgress(current, {
            step: "local.dependencies.install",
            message: "Local dependency install or retry build failed",
            status: "failed",
            detail: { workspace: workspacePath, action: repair.action, exit_code: repair.exit_code },
            created_at: new Date().toISOString(),
          }),
        );
        await recordLocalEnvironmentError(projectId, {
          operation: "local_dependency_repair",
          message: repairSummary || "Local dependency repair failed.",
          workspaceName: workspacePath,
          workspaceKind: project?.local_path ? "linked_local_path" : browserWorkspaces[projectId]?.kind || "local_helper",
          recommendedAction: "Install the missing dependencies in the customer terminal and retry the failed build action.",
          details: repair,
        });
        return null;
      }

      setLiveProgress((current) =>
        mergeLiveProgress(current, {
          step: "local.dependencies.install",
          message: "Local dependencies installed and local build retry passed",
          status: "completed",
          detail: { workspace: workspacePath, action: repair.action },
          created_at: new Date().toISOString(),
        }),
      );
      appendProjectMessage(projectId, {
        role: "assistant",
        content: project?.local_path
          ? "Installed missing dependencies in the linked local workspace and retried the local build. Retrying preview now."
          : "Installed missing dependencies in the customer local workspace and retried the local build. Browser-imported projects still use the backend preview runtime, so server preview may need its own dependency install if it fails again.",
      });

      if (!project?.local_path) {
        return null;
      }
      return await requestPreviewBuildVersion(projectId);
    } catch (repairError) {
      const startupCommand = localSkillsHelperCommand();
      const message = `Local dependency repair could not run: ${repairError.message}`;
      setBuildLog((current) =>
        appendBuildLogSection(current || failedVersion.build_log || "", "Local dependency repair", `${message}\nRun in customer terminal: ${startupCommand}`),
      );
      setLiveProgress((current) =>
        mergeLiveProgress(current, {
          step: "local.dependencies.install",
          message,
          status: "failed",
          detail: { workspace: workspacePath, error: repairError.message },
          created_at: new Date().toISOString(),
        }),
      );
      await recordLocalEnvironmentError(projectId, {
        operation: "local_dependency_repair",
        message,
        workspaceName: workspacePath,
        workspaceKind: project?.local_path ? "linked_local_path" : browserWorkspaces[projectId]?.kind || "local_helper",
        recommendedAction: `Start the helper in the customer/user terminal, then retry dependency repair: ${startupCommand}`,
        details: { error: repairError.message, startup_command: startupCommand },
      });
      return null;
    }
  }

  async function downloadProjectCode({ projectId = null, project = null } = {}) {
    const targetProjectId = projectId || project?.id || activeProject?.id;
    if (!targetProjectId) {
      setError("Select a project before downloading generated code.");
      return;
    }
    const projectName = project?.name || activeProject?.name || "project";
    setIsDownloadingProject(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/projects/${targetProjectId}/download`, {
        method: "GET",
        headers: {
          ...apiAuthHeader(),
          ...apiSystemNameHeader(),
        },
      });
      if (!response.ok) {
        const payload = await readPayload(response);
        throw new Error(formatApiError(payload, response.status));
      }
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="([^"]+)"/i);
      const filename = match?.[1] || `${projectName.replace(/[^\w.-]+/g, "-") || "project"}-worktual.zip`;
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
      appendProjectMessage(targetProjectId, {
        role: "assistant",
        content: `Downloaded ${filename} with the generated project files from the backend workspace.`,
      });
    } catch (downloadError) {
      setError(downloadError.message || "Project download failed.");
    } finally {
      setIsDownloadingProject(false);
    }
  }

  function resolveLocalHelperWorkspacePath(projectId, project) {
    if (project?.local_path) return project.local_path;
    const workspace = browserWorkspaces[projectId];
    if (!workspace) return "";
    const storageKey = localHelperWorkspacePathStorageKey(projectId);
    const storedPath = window.localStorage.getItem(storageKey) || "";
    const hintedPath = window.prompt(
      `Enter the full local folder path for "${workspace.name}" on this customer machine so Worktual can install dependencies and retry the build locally.`,
      storedPath,
    );
    const trimmedPath = String(hintedPath || "").trim();
    if (trimmedPath) {
      window.localStorage.setItem(storageKey, trimmedPath);
    }
    return trimmedPath;
  }

  async function chooseLocalDirectory() {
    if (!activeProject || isDirectoryBusy) return;
    await attachBrowserDirectoryToProject(activeProject);
  }

  function beginFolderAccessFlow(options = {}) {
    return new Promise((resolve) => {
      folderAccessFlowRef.current = { resolve, ...options };
      setFolderAccessUi({
        step: "intro",
        purpose: options.purpose || "import",
        folderHint: options.folderHint || "",
        folderName: "",
        directoryHandle: null,
        error: "",
      });
    });
  }

  function finishFolderAccessFlow(result) {
    folderAccessFlowRef.current?.resolve(result);
    folderAccessFlowRef.current = null;
    setFolderAccessUi(null);
  }

  function cancelFolderAccessFlow() {
    finishFolderAccessFlow({ cancelled: true });
  }

  async function confirmFolderAccessPicker() {
    if (!folderAccessUi || folderAccessUi.step !== "intro") return;
    setFolderAccessUi((current) => ({ ...current, step: "picking", error: "" }));
    try {
      const directoryHandle = await window.showDirectoryPicker({ mode: "readwrite" });
      const permission =
        directoryHandle.queryPermission ? await directoryHandle.queryPermission({ mode: "readwrite" }) : "prompt";
      if (permission === "granted") {
        finishFolderAccessFlow({ mode: "directory", directoryHandle });
        return;
      }
      setFolderAccessUi((current) => ({
        ...current,
        step: "permission",
        folderName: directoryHandle.name,
        directoryHandle,
        error: "",
      }));
    } catch (nextError) {
      if (nextError.name === "AbortError") {
        cancelFolderAccessFlow();
        return;
      }
      setFolderAccessUi((current) => ({
        ...current,
        step: "error",
        error: nextError.message || "Folder selection failed.",
      }));
    }
  }

  async function confirmFolderAccessPermission() {
    const directoryHandle = folderAccessUi?.directoryHandle;
    if (!directoryHandle || folderAccessUi?.step !== "permission") return;
    setFolderAccessUi((current) => ({ ...current, step: "permission-pending", error: "" }));
    try {
      await requestBrowserDirectoryPermission(directoryHandle);
      finishFolderAccessFlow({ mode: "directory", directoryHandle });
    } catch (nextError) {
      setFolderAccessUi((current) => ({
        ...current,
        step: "error",
        error: nextError.message || "Folder write permission was not granted.",
      }));
    }
  }

  async function chooseFolderAccessReadOnlyUpload() {
    finishFolderAccessFlow({ mode: "readonly" });
  }

  async function chooseLocalWorkspaceForNewProject() {
    if (isCreating) return;
    setError("");
    let project = null;
    let projectSource = null;
    try {
      const accessChoice = await beginFolderAccessFlow({ purpose: "import-new" });
      if (accessChoice?.cancelled) return;
      setIsCreating(true);
      projectSource =
        accessChoice?.mode === "readonly"
          ? await requestUploadedProjectDirectory()
          : await buildBrowserProjectSourceFromHandle(accessChoice.directoryHandle);
      const initialFiles = projectSource.files;
      const payload = await api("/api/projects", {
        method: "POST",
        body: {
          name: DEFAULT_PROJECT_NAME,
          description:
            projectSource.kind === "directory"
              ? `Browser-selected local workspace: ${projectSource.name}`
              : `Browser-uploaded project folder: ${projectSource.name}`,
          workspace_mode: "backend",
        },
      });
      project = payload.project;
      if (projectSource.directoryHandle) {
        activateBrowserDirectoryHandle(project.id, projectSource.directoryHandle);
        await saveStoredBrowserDirectoryHandle(project.id, projectSource.directoryHandle);
      } else {
        browserDirectoryHandlesRef.current.delete(project.id);
        pendingBrowserDirectoryHandlesRef.current.delete(project.id);
        await deleteStoredBrowserDirectoryHandle(project.id);
      }
      setBrowserWorkspaces((current) => ({
        ...current,
        [project.id]: {
          name: projectSource.name,
          kind: projectSource.kind,
          systemName: ensureClientSystemName(),
        },
      }));
      setLocalDirectoryName(projectSource.name);
      setProjects((current) => [project, ...current.filter((item) => item.id !== project.id)]);
      setActiveProject(project);
      applySyncedFiles([]);
      setEvents([]);
      setPreviewUrl("");
      setBuildLog("");
      setLiveProgress([]);
      setIsNewProjectModalOpen(false);
      const importPayload = await api(`/api/projects/${project.id}/import-directory`, {
        method: "POST",
        body: { files: initialFiles },
      });
      applyProjectUpdate(importPayload.project || project);
      applySyncedFiles(importPayload.files || []);
      if (initialFiles.length) {
        assertBackendKeptImportedRootFiles(initialFiles, importPayload.files || []);
      }
      try {
        await refreshEvents(project.id);
      } catch (refreshError) {
        setError(`Connected folder, but event refresh failed: ${refreshError.message}`);
      }
      setError("");
      appendProjectMessage(project.id, {
        role: "assistant",
        content: browserImportSummary(projectSource.name, initialFiles, projectSource.diagnostics, {
          canWriteBack: projectSource.kind === "directory",
        }),
      });
    } catch (nextError) {
      if (nextError.name !== "AbortError") {
        setError(nextError.message);
        if (project?.id) {
          await recordLocalEnvironmentError(project.id, {
            operation: "import_local_project",
            message: nextError.message,
            workspaceName: projectSource?.name,
            workspaceKind: projectSource?.kind,
            recommendedAction: "Use the terminal helper to inspect folder permissions, dependencies, and workspace access before retrying import.",
          });
        }
      }
    } finally {
      setIsCreating(false);
    }
  }

  function closeNewProjectModal() {
    if (isCreating || isDirectoryBusy) return;
    setIsNewProjectModalOpen(false);
  }

  async function refreshEvents(projectId) {
    const payload = await api(`/api/events?project_id=${encodeURIComponent(projectId)}`);
    setEvents(payload.events || []);
  }

  function applyProjectUpdate(project) {
    if (!project) return;
    setActiveProject(project);
    setProjects((current) => current.map((item) => (item.id === project.id ? project : item)));
  }

  async function renameProjectFromPromptIfNeeded(project, firstPrompt) {
    if (!shouldAutoNameProject(project)) return null;
    const name = projectTitleFromPrompt(firstPrompt);
    if (!name || name === project.name) return null;
    const payload = await api(`/api/projects/${project.id}`, {
      method: "PATCH",
      body: { name },
    });
    applyProjectUpdate(payload.project);
    return payload.project;
  }

  function mergeIncomingProjectFiles(current, incomingFiles = []) {
    const byPath = new Map((current || []).map((file) => [file.path, file]));
    for (const file of incomingFiles) {
      if (file?.path) {
        byPath.set(file.path, { ...byPath.get(file.path), ...file });
      }
    }
    return [...byPath.values()].sort((left, right) => String(left.path).localeCompare(String(right.path)));
  }

  function progressFilesFromDetail(detail = {}) {
    if (Array.isArray(detail.files)) {
      return detail.files.filter((item) => item?.path);
    }
    if (detail.file?.path) {
      return [detail.file];
    }
    if (Array.isArray(detail.paths)) {
      return detail.paths.map((path) => ({ path: String(path) }));
    }
    return [];
  }

  async function refreshProjectFilesFromApi(projectId, { preferredPath = selectedPath, merge = false } = {}) {
    if (!projectId) return [];
    const filesPayload = await api(`/api/projects/${encodeURIComponent(projectId)}/files`);
    const nextFiles = filesPayload.files || [];
    if (merge) {
      setFiles((current) => {
        const merged = mergeIncomingProjectFiles(current, nextFiles);
        const visibleProjectFiles = merged.filter((file) => !isHiddenProjectFilePath(file.path));
        const preferred =
          visibleProjectFiles.find((file) => file.path === preferredPath) ||
          visibleProjectFiles.find((file) => file.path === "src/App.jsx") ||
          visibleProjectFiles[0];
        if (preferred) selectFile(preferred, merged);
        return merged;
      });
    } else {
      applySyncedFiles(nextFiles, preferredPath);
    }
    return nextFiles;
  }

  function applySyncedFiles(nextFiles, preferredPath = selectedPath) {
    setFiles(nextFiles);
    const visibleProjectFiles = nextFiles.filter((file) => !isHiddenProjectFilePath(file.path));
    const preferred =
      visibleProjectFiles.find((file) => file.path === preferredPath) ||
      visibleProjectFiles.find((file) => file.path === "src/App.jsx") ||
      visibleProjectFiles[0];
    selectFile(preferred, nextFiles);
  }

  function clearWorkspace() {
    setActiveProject(null);
    setFiles([]);
    setSelectedPath("");
    setEditorValue("");
    setSavedValue("");
    setEvents([]);
    setLiveProgress([]);
    setPreviewUrl("");
    setBuildLog("");
    setLocalDirectoryName("");
    setIsNewProjectModalOpen(false);
  }

  async function ensureProjectChatSession(projectId) {
    if (!projectId) return null;
    try {
      const payload = await api(`/api/projects/${encodeURIComponent(projectId)}/chat/sessions/active`);
      const session = payload.session;
      if (session?.id) {
        setStoredChatSessionId(projectId, session.id);
        setChatSessionByProjectId((current) => ({ ...current, [projectId]: session.id }));
      }
      return session;
    } catch (sessionError) {
      console.warn("Failed to ensure chat session:", sessionError);
      return null;
    }
  }

  async function startNewChatSession(projectId) {
    if (!projectId || isGenerating) return null;
    try {
      const payload = await api(`/api/projects/${encodeURIComponent(projectId)}/chat/sessions`, {
        method: "POST",
        body: { title: "" },
      });
      const session = payload.session;
      if (session?.id) {
        setStoredChatSessionId(projectId, session.id);
        setChatSessionByProjectId((current) => ({ ...current, [projectId]: session.id }));
        setMessagesByProjectId((current) => ({ ...current, [projectId]: defaultMessages() }));
        setConversationStateByProjectId((current) => ({
          ...current,
          [projectId]: {
            chat_session_id: session.id,
            message_count: 0,
            has_pending_confirmation: false,
            resume_hint: "Started a new chat session for this project.",
            episodic_count: 0,
          },
        }));
        setEpisodicMemoriesByProjectId((current) => ({ ...current, [projectId]: [] }));
      }
      return session;
    } catch (nextError) {
      setError(nextError.message);
      return null;
    }
  }

  async function loadProjectChatHistory(projectId) {
    if (!projectId) return null;
    const storedSessionId = getStoredChatSessionId(projectId);
    const params = new URLSearchParams({ limit: String(PROJECT_CHAT_HISTORY_LIMIT) });
    if (storedSessionId) params.set("chat_session_id", storedSessionId);
    try {
      let payload;
      try {
        payload = await api(`/api/projects/${encodeURIComponent(projectId)}/chat?${params.toString()}`);
      } catch (primaryError) {
        if (!storedSessionId) throw primaryError;
        clearStoredChatSessionId(projectId);
        payload = await api(
          `/api/projects/${encodeURIComponent(projectId)}/chat?limit=${PROJECT_CHAT_HISTORY_LIMIT}`,
        );
      }
      if (payload.chat_session?.id) {
        setStoredChatSessionId(projectId, payload.chat_session.id);
        setChatSessionByProjectId((current) => ({ ...current, [projectId]: payload.chat_session.id }));
      }
      const messages = (payload.messages || []).map(deserializeStoredChatMessage);
      setMessagesByProjectId((current) => {
        const previous = current[projectId] || [];
        const merged = messages.length ? messages : defaultMessages();
        const withAttachments = merged.map((message) => {
          if (message.attachments?.length) return message;
          const localMatch = [...previous].reverse().find(
            (item) =>
              item.role === message.role &&
              item.content === message.content &&
              item.attachments?.length,
          );
          if (localMatch?.attachments?.length) {
            return { ...message, attachments: localMatch.attachments };
          }
          return message;
        });
        return {
          ...current,
          [projectId]: withAttachments,
        };
      });
      if (payload.conversation) {
        setConversationStateByProjectId((current) => ({
          ...current,
          [projectId]: payload.conversation,
        }));
      }
      setEpisodicMemoriesByProjectId((current) => ({
        ...current,
        [projectId]: payload.episodic_memories || [],
      }));
      return payload;
    } catch (chatError) {
      console.warn("Failed to load project chat history:", chatError);
      return null;
    }
  }

  async function persistProjectMessage(projectId, message, metadata = {}) {
    if (!projectId || !message?.content) return null;
    const chatSessionId = getStoredChatSessionId(projectId);
    try {
      const payload = await api(`/api/projects/${encodeURIComponent(projectId)}/chat`, {
        method: "POST",
        headers: apiChatSessionHeader(projectId),
        body: {
          role: message.role,
          content: message.content,
          chat_session_id: chatSessionId || undefined,
          metadata: {
            source: "browser_ui",
            display_content: message.content,
            ...(message.confirmation ? { confirmation: message.confirmation } : {}),
            ...(Array.isArray(message.attachments) && message.attachments.length
              ? { attachments: message.attachments }
              : {}),
            ...metadata,
          },
        },
      });
      if (payload.chat_session?.id) {
        setStoredChatSessionId(projectId, payload.chat_session.id);
        setChatSessionByProjectId((current) => ({ ...current, [projectId]: payload.chat_session.id }));
      }
      return payload.message || null;
    } catch (persistError) {
      console.warn("Failed to persist chat message:", persistError);
      return null;
    }
  }

  function appendProjectMessage(projectId, message, options = {}) {
    const shouldPersist = options.persist !== false;
    setMessagesByProjectId((current) => {
      const existing = current[projectId] || defaultMessages();
      return { ...current, [projectId]: [...existing, message] };
    });
    if (shouldPersist) {
      void persistProjectMessage(projectId, message, options.metadata || {});
    }
  }

  function markPendingConfirmation(projectId, status) {
    setMessagesByProjectId((current) => {
      const existing = current[projectId] || defaultMessages();
      let updated = false;
      const nextMessages = [...existing].reverse().map((message) => {
        if (!updated && message.role === "assistant" && message.confirmation?.status === "pending") {
          updated = true;
          return { ...message, confirmation: { ...message.confirmation, status } };
        }
        return message;
      }).reverse();
      return { ...current, [projectId]: nextMessages };
    });
  }

  async function handleChatAction(actionPrompt, action = {}) {
    if (action?.type === "cancel_confirmation") {
      if (!activeProject) return;
      markPendingConfirmation(activeProject.id, "cancelled");
      await submitWebsitePrompt(actionPrompt, action);
      return;
    }
    await submitWebsitePrompt(actionPrompt, action);
  }

  function startPanelResize(panel, event) {
    if (isCompactWorkspace) return;
    const layout = layoutRef.current;
    if (!layout) return;
    event.preventDefault();

    const bounds = layout.getBoundingClientRect();
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    function onPointerMove(moveEvent) {
      if (panel === "left") {
        const maxLeft = Math.max(
          LEFT_PANEL_MIN_WIDTH,
          Math.min(
            LEFT_PANEL_MAX_WIDTH,
            bounds.width - rightPanelWidth - CENTER_PANEL_MIN_WIDTH - PANEL_RESIZER_WIDTH * 2,
          ),
        );
        setLeftPanelWidth(clamp(moveEvent.clientX - bounds.left, LEFT_PANEL_MIN_WIDTH, maxLeft));
      } else {
        const maxRight = Math.max(
          RIGHT_PANEL_MIN_WIDTH,
          Math.min(
            RIGHT_PANEL_MAX_WIDTH,
            bounds.width - leftPanelWidth - CENTER_PANEL_MIN_WIDTH - PANEL_RESIZER_WIDTH * 2,
          ),
        );
        setRightPanelWidth(clamp(bounds.right - moveEvent.clientX, RIGHT_PANEL_MIN_WIDTH, maxRight));
      }
    }

    function stopResize() {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stopResize);
      window.removeEventListener("pointercancel", stopResize);
    }

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stopResize);
    window.addEventListener("pointercancel", stopResize);
  }

  function toggleProjectsPanel() {
    setIsLeftPanelOpen((current) => {
      const nextOpen = !current;
      if (isCompactWorkspace && nextOpen) setIsRightPanelOpen(false);
      return nextOpen;
    });
  }

  function toggleCodePanel() {
    setIsRightPanelOpen((current) => {
      const nextOpen = !current;
      if (isCompactWorkspace && nextOpen) setIsLeftPanelOpen(false);
      return nextOpen;
    });
  }

  async function attachBrowserDirectoryToProject(project) {
    setIsDirectoryBusy(true);
    setError("");
    let projectSource = null;
    try {
      const accessChoice = await beginFolderAccessFlow({ purpose: "attach", folderHint: project?.name || "" });
      if (accessChoice?.cancelled) return;
      projectSource =
        accessChoice?.mode === "readonly"
          ? await requestUploadedProjectDirectory()
          : await buildBrowserProjectSourceFromHandle(accessChoice.directoryHandle);
      const localFiles = projectSource.files;
      if (projectSource.directoryHandle) {
        activateBrowserDirectoryHandle(project.id, projectSource.directoryHandle);
        await saveStoredBrowserDirectoryHandle(project.id, projectSource.directoryHandle);
      } else {
        browserDirectoryHandlesRef.current.delete(project.id);
        pendingBrowserDirectoryHandlesRef.current.delete(project.id);
        await deleteStoredBrowserDirectoryHandle(project.id);
      }
      setBrowserWorkspaces((current) => ({
        ...current,
        [project.id]: {
          name: projectSource.name,
          kind: projectSource.kind,
          systemName: ensureClientSystemName(),
        },
      }));
      setLocalDirectoryName(projectSource.name);
      const payload = await api(`/api/projects/${project.id}/import-directory`, {
        method: "POST",
        body: { files: localFiles },
      });
      applyProjectUpdate(payload.project);
      applySyncedFiles(payload.files || []);
      if (localFiles.length) {
        assertBackendKeptImportedRootFiles(localFiles, payload.files || []);
      }
      await refreshEvents(project.id);
      appendProjectMessage(project.id, {
        role: "assistant",
        content: browserImportSummary(projectSource.name, localFiles, projectSource.diagnostics, {
          canWriteBack: projectSource.kind === "directory",
        }),
      });
    } catch (nextError) {
      if (nextError.name !== "AbortError") {
        setError(nextError.message);
        await recordLocalEnvironmentError(project.id, {
          operation: "link_local_project",
          message: nextError.message,
          workspaceName: projectSource?.name,
          workspaceKind: projectSource?.kind,
          recommendedAction: "Use terminal helper actions to validate folder access and dependency setup before retrying.",
        });
      }
    } finally {
      setIsDirectoryBusy(false);
    }
  }

  async function reconnectBrowserDirectory(project) {
    if (!project || isDirectoryBusy) return;
    const existingWorkspace = browserWorkspaces[project.id];
    if (!existingWorkspace || existingWorkspace.kind !== "directory") return;

    setIsDirectoryBusy(true);
    setError("");
    try {
      const storedHandle =
        pendingBrowserDirectoryHandlesRef.current.get(project.id) ||
        (await loadStoredBrowserDirectoryHandle(project.id));
      if (storedHandle && (!existingWorkspace.name || storedHandle.name === existingWorkspace.name)) {
        const permission = storedHandle.requestPermission
          ? await storedHandle.requestPermission({ mode: "readwrite" })
          : "denied";
        if (permission === "granted") {
          activateBrowserDirectoryHandle(project.id, storedHandle);
          setLocalDirectoryName(storedHandle.name);
          appendProjectMessage(project.id, {
            role: "assistant",
            content: `Restored writable access to system folder: ${storedHandle.name}.`,
          });
          return;
        }
      }
      const accessChoice = await beginFolderAccessFlow({
        purpose: "reconnect",
        folderHint: existingWorkspace.name,
      });
      if (accessChoice?.cancelled) return;
      if (accessChoice?.mode === "readonly") {
        throw new Error("Reconnecting a writable folder requires full folder access, not read-only upload.");
      }
      const directoryHandle = accessChoice.directoryHandle;
      if (existingWorkspace.name && directoryHandle.name !== existingWorkspace.name) {
        throw new Error(
          `Selected folder "${directoryHandle.name}" does not match the original folder "${existingWorkspace.name}". Select the same folder to restore local write-back.`,
        );
      }
      activateBrowserDirectoryHandle(project.id, directoryHandle);
      await saveStoredBrowserDirectoryHandle(project.id, directoryHandle);
      setBrowserWorkspaces((current) => ({
        ...current,
        [project.id]: {
          name: directoryHandle.name,
          kind: "directory",
          systemName: existingWorkspace.systemName || ensureClientSystemName(),
        },
      }));
      setLocalDirectoryName(directoryHandle.name);
      appendProjectMessage(project.id, {
        role: "assistant",
        content: `Restored writable access to system folder: ${directoryHandle.name}. Future generated changes will be saved back to this local folder.`,
      });
    } catch (nextError) {
      if (nextError.name !== "AbortError") {
        setError(nextError.message);
      }
    } finally {
      setIsDirectoryBusy(false);
    }
  }

  function activateBrowserDirectoryHandle(projectId, directoryHandle) {
    if (!projectId || !directoryHandle) return;
    browserDirectoryHandlesRef.current.set(projectId, directoryHandle);
    pendingBrowserDirectoryHandlesRef.current.delete(projectId);
    setPendingBrowserPermissionProjectId((current) => (current === projectId ? "" : current));
    setBrowserDirectoryHandleRevision((current) => current + 1);
  }

  async function restoreStoredBrowserDirectoryConnection(project) {
    if (!project?.id) return "missing";
    const workspace = browserWorkspaces[project.id];
    if (!workspace || workspace.kind !== "directory" || project.local_path) return "missing";
    if (browserDirectoryHandlesRef.current.has(project.id)) return "granted";

    const directoryHandle =
      pendingBrowserDirectoryHandlesRef.current.get(project.id) ||
      (await loadStoredBrowserDirectoryHandle(project.id));
    if (!directoryHandle) return "missing";
    if (workspace.name && directoryHandle.name !== workspace.name) {
      pendingBrowserDirectoryHandlesRef.current.delete(project.id);
      return "mismatch";
    }

    const permission = directoryHandle.queryPermission
      ? await directoryHandle.queryPermission({ mode: "readwrite" })
      : "prompt";
    if (permission === "granted") {
      activateBrowserDirectoryHandle(project.id, directoryHandle);
      return "granted";
    }
    if (permission === "prompt") {
      pendingBrowserDirectoryHandlesRef.current.set(project.id, directoryHandle);
      return "prompt";
    }
    pendingBrowserDirectoryHandlesRef.current.delete(project.id);
    return permission || "denied";
  }

  async function writeProjectFilesToBrowserWorkspace(projectId, nextFiles) {
    let directoryHandle = browserDirectoryHandlesRef.current.get(projectId);
    if (!directoryHandle) {
      directoryHandle = await loadStoredBrowserDirectoryHandle(projectId);
      if (directoryHandle) {
        const permission = directoryHandle.queryPermission
          ? await directoryHandle.queryPermission({ mode: "readwrite" })
          : "prompt";
        if (permission === "granted") {
          activateBrowserDirectoryHandle(projectId, directoryHandle);
        } else {
          pendingBrowserDirectoryHandlesRef.current.set(projectId, directoryHandle);
          directoryHandle = null;
        }
      }
    }
    if (!directoryHandle || !nextFiles.length) return null;
    await ensureBrowserDirectoryPermission(directoryHandle);
    const count = await writeBrowserProjectFiles(directoryHandle, nextFiles);
    return { count, name: directoryHandle.name };
  }

  async function applyRealtimeGenerationProgress(projectId, progressEvent) {
    const step = progressEvent?.step || "";
    const detail = progressEvent?.detail || {};
    const fileSteps = new Set(["file.written", "files.materialized", "files.persisted", "patch.proposed"]);
    if (!fileSteps.has(step)) return;
    let files = progressFilesFromDetail(detail);
    if (!files.length && step === "files.persisted" && Number(detail.file_count || 0) > 0) {
      try {
        files = await refreshProjectFilesFromApi(projectId, { merge: true });
      } catch (syncError) {
        setError(`Live file refresh failed: ${syncError.message}`);
        return;
      }
      if (files.length) {
        setLiveWrittenPaths((current) => [...new Set([...current, ...files.map((file) => file.path).filter(Boolean)])]);
      }
      return;
    }
    if (!files.length) return;

    try {
      if (step === "file.written" && detail.file?.path) {
        await writeProjectFilesToBrowserWorkspace(projectId, [detail.file]);
      } else if (["files.materialized", "files.persisted", "patch.proposed"].includes(step)) {
        await writeProjectFilesToBrowserWorkspace(projectId, files);
      }
    } catch (syncError) {
      setError(`Live file sync failed: ${syncError.message}`);
      await recordLocalEnvironmentError(projectId, {
        operation: "realtime_browser_write_back",
        message: syncError.message,
        workspaceName: browserWorkspaces[projectId]?.name,
        workspaceKind: browserWorkspaces[projectId]?.kind,
        recommendedAction: "Use terminal helper actions to inspect folder permissions and validate generated files locally.",
      });
    }

    if (step === "file.written") {
      const writtenPath = detail.file?.path || files[files.length - 1]?.path;
      if (writtenPath) {
        setLiveWrittenPaths((current) => [...new Set([...current, writtenPath])]);
      }
      setFiles((current) => {
        const merged = mergeIncomingProjectFiles(current, files);
        const newest = detail.file || files[files.length - 1];
        if (newest?.path) {
          selectFile(newest, merged);
        }
        return merged;
      });
    } else {
      setFiles((current) => mergeIncomingProjectFiles(current, files));
      setLiveWrittenPaths((current) => [...new Set([...current, ...files.map((file) => file.path).filter(Boolean)])]);
    }
  }

  async function syncGeneratedFilesToBrowserWorkspace(projectId, nextFiles) {
    const workspace = browserWorkspaces[projectId];
    if (!workspace || !nextFiles.length) return null;
    setLiveProgress((current) =>
      mergeLiveProgress(current, {
        step: "browser.write_back",
        message: `Writing ${nextFiles.length} files to the selected browser folder`,
        status: "running",
        detail: { file_count: nextFiles.length, workspace: workspace.name, workspace_kind: workspace.kind },
        created_at: new Date().toISOString(),
      }),
    );
    try {
      const browserSync = await writeProjectFilesToBrowserWorkspace(projectId, nextFiles);
      if (browserSync) {
        setLiveProgress((current) =>
          mergeLiveProgress(current, {
            step: "browser.write_back.completed",
            message: `Wrote ${browserSync.count} files to ${browserSync.name}`,
            status: "completed",
            detail: { count: browserSync.count, workspace: browserSync.name, workspace_kind: workspace.kind },
            created_at: new Date().toISOString(),
          }),
        );
        appendProjectMessage(projectId, {
          role: "assistant",
          content: localWriteBackMessage(browserSync, nextFiles),
        });
        return browserSync;
      }
      const writeBackNotice = browserWorkspaceWriteBackNotice(projectId);
      if (writeBackNotice) {
        setLiveProgress((current) =>
          mergeLiveProgress(current, {
            step: "browser.write_back.skipped",
            message: writeBackNotice,
            status: "completed",
            detail: { reason: writeBackNotice, workspace: workspace.name, workspace_kind: workspace.kind },
            created_at: new Date().toISOString(),
          }),
        );
        appendProjectMessage(projectId, { role: "assistant", content: writeBackNotice });
        setError(writeBackNotice);
      }
      return null;
    } catch (syncError) {
      const message = `Generated files, but browser folder write failed: ${syncError.message}`;
      setLiveProgress((current) =>
        mergeLiveProgress(current, {
          step: "browser.write_back.failed",
          message,
          status: "failed",
          detail: { error: syncError.message, workspace: workspace.name, workspace_kind: workspace.kind },
          created_at: new Date().toISOString(),
        }),
      );
      appendProjectMessage(projectId, { role: "assistant", content: message });
      setError(message);
      await recordLocalEnvironmentError(projectId, {
        operation: "generation_browser_write_back",
        message,
        workspaceName: workspace.name,
        workspaceKind: workspace.kind,
        recommendedAction: "Use terminal helper actions to inspect the local workspace, install missing dependencies, and rerun build/tests before retrying write-back.",
        details: { error: syncError.message },
      });
      return null;
    }
  }

  function browserWorkspaceWriteBackNotice(projectId) {
    const workspace = browserWorkspaces[projectId];
    if (!workspace) return "";
    if (workspace.kind === "upload") {
      const lanHint = localFolderAccessHint();
      return `Updated backend and preview only. This folder upload is read-only because the browser did not provide writable folder access.${lanHint ? ` ${lanHint}` : " Use HTTPS or localhost with the writable folder picker to save generated files back to disk."}`;
    }
    if (workspace.kind === "directory" && !browserDirectoryHandlesRef.current.has(projectId)) {
      return `Updated backend and preview only. Browser folder write access for "${workspace.name}" is not available in this tab; reconnect the same folder to resume local write-back without using a backend static path.`;
    }
    return "";
  }

  if (authScreen) {
    return (
      <AuthScreen
        error={error}
        isLoading={isLoading}
        onLogin={handleLogin}
      />
    );
  }

  return (
    <div className="wt-workspace-shell flex h-screen min-h-0 flex-col overflow-hidden bg-canvas text-ink">
      <Header
        session={session}
        sessionUsage={sessionUsage}
        isLoading={isLoading}
        onRefresh={bootstrap}
        onOpenSettings={() => setIsSettingsOpen(true)}
        onOpenAdmin={() => setIsAdminPanelOpen(true)}
        onLogout={handleLogout}
      />
      {error ? <ErrorBanner message={error} /> : null}
      <main
        ref={layoutRef}
        className="grid min-h-0 min-w-0 flex-1 overflow-hidden border-t border-line"
        style={{
          gridTemplateColumns: layoutColumns,
        }}
      >
        <ProjectHistory
          activeProject={activeProject}
          deletingProjectId={deletingProjectId}
          isCreating={isCreating}
          isProjectSearchOpen={isProjectSearchOpen}
          isCollapsed={!isLeftPanelOpen}
          projectSearchQuery={projectSearchQuery}
          projects={projects}
          onCreateProject={openNewProjectModal}
          onDeleteProject={deleteProject}
          onOpenProject={openProject}
          onProjectSearchChange={setProjectSearchQuery}
          onTogglePanel={() => setIsLeftPanelOpen((current) => !current)}
          onToggleProjectSearch={() => setIsProjectSearchOpen((current) => !current)}
        />
        {isLeftPanelOpen ? (
          <PanelResizeHandle label="Resize project history panel" onPointerDown={(event) => startPanelResize("left", event)} />
        ) : (
          <div aria-hidden="true" />
        )}
        <ConversationPanel
          activeProject={activeProject}
          conversationState={conversationState}
          chatSessionId={activeProject ? chatSessionByProjectId[activeProject.id] || getStoredChatSessionId(activeProject.id) : ""}
          episodicMemories={episodicMemories}
          isBuilding={isBuilding}
          isGenerating={isGenerating}
          isCancellingGeneration={isCancellingGeneration}
          isImportingDirectory={isDirectoryBusy}
          liveProgress={liveProgress}
          streamingAssistantText={streamingAssistantText}
          messages={messages}
          previewUrl={previewUrl}
          previewVersionId={previewVersionId}
          prompt={prompt}
          promptAttachments={promptAttachments}
          selectedModel={selectedModel}
          setSelectedModel={setSelectedModel}
          setPrompt={setPrompt}
          setPromptAttachments={setPromptAttachments}
          onGenerate={generateWebsite}
          onStopGeneration={stopWebsiteGeneration}
          onStartNewChatSession={() => activeProject && startNewChatSession(activeProject.id)}
          onSubmitPrompt={handleChatAction}
          onOpenFileLine={selectFileAtLine}
          skillsRefreshToken={skillsRefreshToken}
          onEpisodesUpdated={(nextEpisodes) => {
            if (!activeProject?.id) return;
            setEpisodicMemoriesByProjectId((current) => ({
              ...current,
              [activeProject.id]: nextEpisodes,
            }));
          }}
        />
        {isRightPanelOpen ? (
          <PanelResizeHandle label="Resize code panel" onPointerDown={(event) => startPanelResize("right", event)} />
        ) : (
          <div aria-hidden="true" />
        )}
        <CodeWorkspace
          activeProject={activeProject}
          browserWorkspace={activeProject ? browserWorkspaces[activeProject.id] : null}
          hasBrowserDirectoryHandle={Boolean(activeProject && browserDirectoryHandlesRef.current.has(activeProject.id))}
          editorValue={editorValue}
          file={selectedFile}
          files={files}
          hasUnsavedChanges={hasUnsavedChanges}
          isCollapsed={!isRightPanelOpen}
          isBuilding={isBuilding}
          isGenerating={isGenerating}
          liveWrittenPaths={liveWrittenPaths}
          patchDiff={activeProject ? patchDiffByProjectId[activeProject.id] : null}
          patchApproval={activeProject ? patchApprovalByProjectId[activeProject.id] : null}
          onApprovePatch={() => activeProject && handleChatAction("Approve and apply the proposed patch.", { type: "approve_patch" })}
          onRejectPatch={() => activeProject && handleChatAction("Reject the proposed patch.", { type: "reject_patch" })}
          isReconnectingBrowserFolder={isDirectoryBusy}
          isSaving={isSaving}
          selectedPath={selectedPath}
          onChange={setEditorValue}
          onCloseFile={closeSelectedFile}
          onPreview={previewWebsite}
          onDownloadCode={() => downloadProjectCode({ projectId: activeProject?.id, project: activeProject })}
          isDownloadingProject={isDownloadingProject}
          onReconnectBrowserFolder={() => reconnectBrowserDirectory(activeProject)}
          onSave={saveCurrentFile}
          onSelectFile={selectFile}
          onOpenDiffFile={selectFileAtLine}
          onEditorMount={handleEditorMount}
          onTogglePanel={() => setIsRightPanelOpen((current) => !current)}
        />
      </main>
      {isNewProjectModalOpen ? (
        <NewProjectModal
          isBusy={isCreating}
          helperCheck={localHelperCheck}
          onClose={closeNewProjectModal}
          onCheckLocalHelper={checkLocalHelper}
          onCreateBackend={() => createProject({ workspaceMode: "backend" })}
          onChooseLocal={chooseLocalWorkspaceForNewProject}
        />
      ) : null}
      {folderAccessUi ? (
        <FolderAccessModal
          ui={folderAccessUi}
          onAllowPermission={confirmFolderAccessPermission}
          onCancel={cancelFolderAccessFlow}
          onChooseFolder={confirmFolderAccessPicker}
          onReadOnlyUpload={chooseFolderAccessReadOnlyUpload}
          onRetry={() => setFolderAccessUi((current) => ({ ...current, step: "intro", error: "" }))}
        />
      ) : null}
      {isSettingsOpen ? (
        <UserSettingsModal
          session={session}
          usage={sessionUsage || session?.usage}
          onRefreshUsage={refreshSessionUsage}
          activeProject={activeProject}
          chatSessionId={activeProject ? chatSessionByProjectId[activeProject.id] || getStoredChatSessionId(activeProject.id) : ""}
          onClose={() => setIsSettingsOpen(false)}
          onSave={handleProfileUpdate}
        />
      ) : null}
      {isAdminPanelOpen ? (
        <AdminUsersPanel
          onClose={() => setIsAdminPanelOpen(false)}
          onChanged={async () => {
            await bootstrap();
          }}
        />
      ) : null}
    </div>
  );
}

function formatTokenCount(value) {
  const amount = Number(value || 0);
  if (amount >= 1_000_000) return `${(amount / 1_000_000).toFixed(1)}M`;
  if (amount >= 1_000) return `${Math.round(amount / 1_000)}K`;
  return String(amount);
}

function formatTokenCountExact(value) {
  const amount = Number(value || 0);
  return amount.toLocaleString();
}

function formatUsdCost(value) {
  const amount = Number(value || 0);
  if (!amount) return "$0.000000";
  return `$${amount.toFixed(6)}`;
}

function formatCredits(value) {
  const amount = Number(value || 0);
  if (!amount) return "0.0000";
  return amount.toLocaleString(undefined, {
    minimumFractionDigits: amount < 10 ? 4 : 2,
    maximumFractionDigits: 4,
  });
}

function formatCreditUsdFromCredits(value, creditUsdValue = 0.01) {
  return formatUsdCost(Number(value || 0) * Number(creditUsdValue || 0.01));
}

function usageProgressPercent(used, limit) {
  const usedAmount = Number(used || 0);
  const limitAmount = Number(limit || 0);
  if (!limitAmount) return 0;
  return Math.min(100, Math.round((usedAmount / limitAmount) * 100));
}

function UsageProgressRow({ label, periodLabel, used, limit, remaining }) {
  const percent = usageProgressPercent(used, limit);
  const nearLimit = percent >= 90;
  const atLimit = percent >= 100;
  const barClass = atLimit ? "bg-red-500" : nearLimit ? "bg-amber-500" : "bg-worktual-500";
  return (
    <div className="rounded-xl border border-line bg-black/30 p-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-black text-white">{label}</p>
          <p className="text-[11px] uppercase tracking-wide text-slate-500">{periodLabel}</p>
        </div>
        <div className="text-right">
          <p className="text-sm font-bold text-slate-200">
            {formatTokenCount(used)} <span className="text-slate-500">/ {formatTokenCount(limit)}</span>
          </p>
          <p className="text-[11px] text-slate-500" title={`${formatTokenCountExact(used)} / ${formatTokenCountExact(limit)}`}>
            {formatTokenCountExact(used)} / {formatTokenCountExact(limit)} tokens
          </p>
        </div>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-white/10">
        <div className={`h-full rounded-full transition-all ${barClass}`} style={{ width: `${percent}%` }} />
      </div>
      <p className="mt-2 text-xs text-slate-400">
        {formatTokenCount(remaining)} remaining · {percent}% used
      </p>
    </div>
  );
}

function CreditUsageCard({ usage }) {
  const account = usage?.model_usage?.credit_account || {};
  const used = Number(account.used_credits || 0);
  const reserved = Number(account.reserved_credits || 0);
  const limit = Number(account.included_monthly_credits || 0);
  const remaining = Number(account.remaining_included_credits || 0);
  const creditUsdValue = Number(account.credit_usd_value || 0.01);
  const consumed = used + reserved;
  const percent = usageProgressPercent(consumed, limit);
  const blocked = Boolean(account.limit_reached || usage?.blocked_reason);
  const barClass = blocked ? "bg-red-500" : percent >= 80 ? "bg-amber-500" : "bg-worktual-500";
  return (
    <div className={`rounded-xl border p-4 ${blocked ? "border-red-500/50 bg-red-500/10" : "border-line bg-black/30"}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-black text-white">AI credits</p>
          <p className="mt-1 text-xs text-slate-400">1 credit = {formatUsdCost(creditUsdValue)}. Generation stops at {formatCredits(limit)} credits.</p>
        </div>
        <div className="text-right">
          <p className="text-lg font-black text-white">
            {formatCredits(consumed)} <span className="text-sm text-slate-500">/ {formatCredits(limit)}</span>
          </p>
          <p className="text-xs text-slate-400">{formatCreditUsdFromCredits(consumed, creditUsdValue)} used</p>
        </div>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
        <div className={`h-full rounded-full transition-all ${barClass}`} style={{ width: `${percent}%` }} />
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
        <span>{formatCredits(remaining)} credits remaining</span>
        <span>{percent}% used this month</span>
      </div>
      {blocked ? (
        <p className="mt-3 rounded-lg border border-red-400/40 bg-red-500/10 px-3 py-2 text-sm font-semibold text-red-100">
          {account.blocked_reason || usage?.blocked_reason || "You have completed your user limit."}
        </p>
      ) : null}
    </div>
  );
}

function CreditUsageInline({ usage }) {
  const account = usage?.model_usage?.credit_account || {};
  const used = Number(account.used_credits || 0);
  const reserved = Number(account.reserved_credits || 0);
  const limit = Number(account.included_monthly_credits || 0);
  const remaining = Number(account.remaining_included_credits || 0);
  const consumed = used + reserved;
  const percent = usageProgressPercent(consumed, limit);
  const blocked = Boolean(account.limit_reached || usage?.blocked_reason);
  return (
    <div className="mt-3 space-y-1.5">
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="font-bold text-slate-300">AI credits</span>
        <span className={blocked ? "font-black text-red-300" : "font-black text-cyan-200"}>
          {formatCredits(consumed)} / {formatCredits(limit)}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
        <div
          className={`h-full rounded-full ${blocked ? "bg-red-500" : percent >= 80 ? "bg-amber-500" : "bg-worktual-500"}`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="text-[11px] text-slate-500">{formatCredits(remaining)} credits remaining</p>
    </div>
  );
}

function formatUsageTimestamp(value) {
  if (!value) return "Recent";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Recent";
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function TokenMetricPill({ label, value, formatter = formatTokenCount }) {
  return (
    <div className="rounded-lg border border-line bg-black/25 px-3 py-2">
      <p className="text-[10px] font-black uppercase tracking-normal text-slate-500">{label}</p>
      <p className="mt-1 text-sm font-black text-white">{formatter(value || 0)}</p>
    </div>
  );
}

function TokenUsageBreakdown({ usage, compact = false, onLoadAllRequests = null }) {
  const [showAll, setShowAll] = useState(false);
  const [isLoadingAll, setIsLoadingAll] = useState(false);
  const [loadAllError, setLoadAllError] = useState("");
  const modelUsage = usage?.model_usage || {};
  const monthly = modelUsage.monthly || {};
  const recentRequests = Array.isArray(modelUsage.recent_requests) ? modelUsage.recent_requests : [];
  const hasDetails = monthly.call_count || monthly.input_tokens || monthly.output_tokens || monthly.thought_tokens || recentRequests.length;
  if (!hasDetails) {
    return (
      <div className="rounded-lg border border-line bg-black/20 px-3 py-2 text-xs text-slate-500">
        Per-request input/output token details will appear after the next model call.
      </div>
    );
  }
  const collapsedLimit = compact ? 3 : TOKEN_USAGE_COLLAPSED_REQUEST_LIMIT;
  const visibleRequests = showAll ? recentRequests : recentRequests.slice(0, collapsedLimit);
  const canShowAll = !compact && !showAll && recentRequests.length >= TOKEN_USAGE_COLLAPSED_REQUEST_LIMIT;

  async function handleShowAll() {
    if (isLoadingAll) return;
    setLoadAllError("");
    setIsLoadingAll(true);
    try {
      if (typeof onLoadAllRequests === "function") {
        await onLoadAllRequests();
      }
      setShowAll(true);
    } catch (error) {
      setLoadAllError(error?.message || "Could not load the complete usage history.");
    } finally {
      setIsLoadingAll(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className={`grid gap-2 ${compact ? "grid-cols-2" : "grid-cols-2 sm:grid-cols-4 xl:grid-cols-7"}`}>
        <TokenMetricPill label="Month input" value={monthly.input_tokens} />
        <TokenMetricPill label="Month output" value={monthly.output_tokens} />
        {!compact ? <TokenMetricPill label="Month thinking" value={monthly.thought_tokens} /> : null}
        {!compact ? <TokenMetricPill label="Month total" value={monthly.total_tokens} /> : null}
        {!compact ? <TokenMetricPill label="Month credits" value={monthly.estimated_credits} formatter={formatCredits} /> : null}
        {!compact ? <TokenMetricPill label="Month cost" value={monthly.estimated_cost_usd} formatter={formatUsdCost} /> : null}
        {!compact ? <TokenMetricPill label="Model calls" value={monthly.call_count} /> : null}
      </div>
      {visibleRequests.length ? (
        <div
          className={`rounded-lg border border-line bg-black/20 ${
            showAll ? "max-h-[min(28rem,50vh)] overflow-y-auto overscroll-contain" : "overflow-hidden"
          }`}
        >
          <div className={`grid grid-cols-[minmax(0,1fr)_auto_auto_auto_auto_auto_auto] gap-2 border-b border-line bg-panel px-3 py-2 text-[10px] font-black uppercase tracking-normal text-slate-500 ${showAll ? "sticky top-0 z-10" : ""}`}>
            <span>Request</span>
            <span>Input</span>
            <span>Output</span>
            <span>Think</span>
            <span>Total</span>
            <span>Credits</span>
            <span>Cost</span>
          </div>
          {visibleRequests.map((request, index) => (
            <div key={request.request_id || `${request.created_at}-${index}`} className="grid grid-cols-[minmax(0,1fr)_auto_auto_auto_auto_auto_auto] gap-2 border-b border-line/60 px-3 py-2 text-xs last:border-b-0">
              <div className="min-w-0">
                <p className="truncate font-bold text-slate-200">{formatUsageTimestamp(request.created_at)}</p>
                <p className="truncate text-[11px] text-slate-500">
                  {(request.models || []).join(", ") || "model"} · {request.call_count || 0} call{request.call_count === 1 ? "" : "s"}
                </p>
                {Array.isArray(request.execution_stages) && request.execution_stages.length ? (
                  <p className="truncate text-[10px] uppercase tracking-normal text-slate-600">
                    {request.execution_stages.join(" / ")}
                  </p>
                ) : null}
              </div>
              <span className="font-semibold text-cyan-200">{formatTokenCountExact(request.input_tokens || 0)}</span>
              <span className="font-semibold text-emerald-200">{formatTokenCountExact(request.output_tokens || 0)}</span>
              <span className="font-semibold text-violet-200">{formatTokenCountExact(request.thought_tokens || 0)}</span>
              <span className="font-black text-white">{formatTokenCountExact(request.total_tokens || 0)}</span>
              <span className="font-semibold text-amber-100">{formatCredits(request.estimated_credits || 0)}</span>
              <span className="font-semibold text-amber-100" title={`${formatCredits(request.estimated_credits || 0)} credits`}>
                {formatUsdCost(request.estimated_cost_usd || 0)}
              </span>
            </div>
          ))}
        </div>
      ) : null}
      {!compact && (canShowAll || showAll) ? (
        <div className="flex items-center justify-between gap-3">
          {loadAllError ? <p className="text-xs text-amber-300">{loadAllError}</p> : <span />}
          <button
            type="button"
            className="ml-auto inline-flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-xs font-bold text-slate-300 hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-60"
            onClick={showAll ? () => setShowAll(false) : handleShowAll}
            disabled={isLoadingAll}
          >
            {isLoadingAll ? <Loader2 className="animate-spin" size={14} /> : showAll ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            {isLoadingAll ? "Loading history..." : showAll ? "Show less" : "Show all"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function TokenUsagePanel({ usage, isRefreshing, onRefresh, onLoadAllRequests, refreshError = "" }) {
  if (!usage) {
    return (
      <div className="rounded-xl border border-line bg-black/30 p-6 text-center text-sm text-slate-400">
        Token usage is not available right now.
        {refreshError ? <p className="mt-2 text-xs text-amber-300">{refreshError}</p> : null}
        <div className="mt-4">
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-lg border border-line px-4 py-2 text-sm font-bold text-slate-300 hover:bg-white/5 disabled:opacity-60"
            onClick={onRefresh}
            disabled={isRefreshing}
          >
            {isRefreshing ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}
            {isRefreshing ? "Refreshing..." : "Refresh usage"}
          </button>
        </div>
      </div>
    );
  }

  if (usage.unlimited) {
    return (
      <div className="space-y-4">
        <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-4">
          <p className="text-sm font-black text-emerald-200">Unlimited admin account</p>
          <p className="mt-1 text-sm text-emerald-100/80">Your account is not subject to AI credit limits. Detailed model usage is still tracked for cost visibility.</p>
        </div>
        <CreditUsageCard usage={usage} />
        <TokenUsageBreakdown usage={usage} onLoadAllRequests={onLoadAllRequests} />
        <div className="flex justify-end">
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-lg border border-line px-4 py-2 text-sm font-bold text-slate-300 hover:bg-white/5 disabled:opacity-60"
            onClick={onRefresh}
            disabled={isRefreshing}
          >
            {isRefreshing ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}
            {isRefreshing ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>
    );
  }

  const blocked = Boolean(usage.blocked_reason);

  return (
    <div className="space-y-4">
      <CreditUsageCard usage={usage} />
      {blocked ? (
        <div className="rounded-xl border border-amber-500/50 bg-amber-500/10 px-4 py-3 text-sm font-semibold text-amber-200">
          {usage.blocked_reason}
        </div>
      ) : null}
      <p className="text-sm text-slate-400">
        Monthly AI credits are the subscription limit. Raw input/output tokens remain below for debugging and cost transparency. Raw user prompts are not shown here.
      </p>
      <TokenUsageBreakdown usage={usage} onLoadAllRequests={onLoadAllRequests} />
      <div className="flex items-center justify-between gap-3">
        {refreshError ? <p className="text-xs text-amber-300">{refreshError}</p> : <span />}
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded-lg border border-line px-4 py-2 text-sm font-bold text-slate-300 hover:bg-white/5 disabled:opacity-60"
          onClick={onRefresh}
          disabled={isRefreshing}
        >
          {isRefreshing ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}
          {isRefreshing ? "Refreshing..." : "Refresh usage"}
        </button>
      </div>
    </div>
  );
}

function UsageLimitBadge({ usage }) {
  if (!usage || usage.unlimited) return null;
  const creditAccount = usage.model_usage?.credit_account || {};
  const usedCredits = Number(creditAccount.used_credits || 0) + Number(creditAccount.reserved_credits || 0);
  const includedCredits = Number(creditAccount.included_monthly_credits || 0);
  const blocked = Boolean(usage.blocked_reason);
  return (
    <span
      className={`hidden items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-black uppercase tracking-wide md:inline-flex ${
        blocked ? "border border-red-400/40 bg-red-500/15 text-red-200" : "wt-status-chip"
      }`}
      title={usage.blocked_reason || "AI credit usage limit"}
    >
      <span className={`size-1.5 rounded-full ${blocked ? "bg-red-300" : "bg-emerald-300"}`} />
      {blocked ? "Limit reached" : `${formatCredits(usedCredits)}/${formatCredits(includedCredits)} credits`}
    </span>
  );
}

function Header({ session, sessionUsage, isLoading, onRefresh, onOpenSettings, onOpenAdmin, onLogout }) {
  const isAdmin = session?.role === "admin";
  return (
    <header className="wt-command-header wt-header-accent wt-app-header flex shrink-0 items-center justify-between gap-4 border-b border-line px-4 text-ink">
      <div className="flex min-w-0 items-center gap-3">
        <div className="flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-md bg-black">
          <img
            className="size-full object-contain"
            src="/assets/worktual-logo.png"
            alt="Worktual"
          />
        </div>
        <div className="min-w-0">
          <h1 className="truncate text-lg font-black leading-tight text-ink">Worktual Open Head</h1>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <UsageLimitBadge usage={sessionUsage || session?.usage} />
        {isAdmin ? (
          <IconButton compact label="Manage users" onClick={onOpenAdmin} disabled={isLoading}>
            <Users size={14} />
          </IconButton>
        ) : null}
        <IconButton compact label="Account settings" onClick={onOpenSettings} disabled={isLoading}>
          <Settings size={14} />
        </IconButton>
        <IconButton compact label="Sign out" onClick={onLogout} disabled={isLoading}>
          <LogOut size={14} />
        </IconButton>
        <IconButton compact label="Refresh workspace" onClick={onRefresh} disabled={isLoading}>
          {isLoading ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}
        </IconButton>
      </div>
    </header>
  );
}

function AuthScreen({ isLoading, error, onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  function handleSubmit(event) {
    event.preventDefault();
    onLogin({ email, password });
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4 py-10 text-ink">
      <div className="grid w-full max-w-4xl gap-8 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="hidden flex-col justify-center lg:flex">
          <div className="space-y-3">
            <p className="eyebrow">Worktual</p>
            <h2 className="text-3xl font-black text-white">Build websites with AI, your way.</h2>
            <p className="max-w-md text-sm text-slate-300">
              Sign in with the credentials your administrator shared. Each account has its own projects, AI credits, and chat history.
            </p>
          </div>
        </div>
        <div className="rounded-2xl border border-line bg-panel p-6 shadow-2xl sm:p-8">
          <div className="mb-6">
            <p className="text-xs font-black uppercase tracking-normal text-worktual-700">Welcome back</p>
            <h1 className="text-2xl font-black text-white">Sign in</h1>
          </div>
          {error ? <ErrorBanner message={error} /> : null}
          <form className="space-y-4" onSubmit={handleSubmit}>
            <label className="block space-y-1.5">
              <span className="text-xs font-bold uppercase tracking-wide text-slate-400">Email</span>
              <input
                className="w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none ring-worktual-500 focus:ring-2"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@company.com"
                autoComplete="email"
                required
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-xs font-bold uppercase tracking-wide text-slate-400">Password</span>
              <input
                className="w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none ring-worktual-500 focus:ring-2"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Your account password"
                autoComplete="current-password"
                minLength={8}
                required
              />
            </label>
            <button
              type="submit"
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-worktual-700 px-4 py-2.5 text-sm font-black text-white transition hover:bg-worktual-600 disabled:opacity-60"
              disabled={isLoading}
            >
              {isLoading ? <Loader2 className="animate-spin" size={16} /> : null}
              Sign in
            </button>
          </form>
          <p className="mt-5 text-center text-sm text-slate-400">
            Need access? Contact your platform administrator to create an account.
          </p>
        </div>
      </div>
    </div>
  );
}

function AdminUsersPanel({ onClose, onChanged }) {
  const [users, setUsers] = useState([]);
  const [selectedUserId, setSelectedUserId] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [form, setForm] = useState({
    email: "",
    password: "",
    display_name: "",
    monthly_ai_credits: "1000",
  });

  async function loadUsers() {
    setIsLoading(true);
    setError("");
    try {
      const payload = await api("/api/admin/users");
      const nextUsers = Array.isArray(payload.users) ? payload.users : [];
      setUsers(nextUsers);
      setSelectedUserId((current) => (nextUsers.some((item) => item.id === current) ? current : ""));
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadUsers();
  }, []);

  async function handleCreateUser(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    const username = form.display_name.trim();
    if (!username) {
      setError("Username is required.");
      return;
    }
    if (username === form.password) {
      setError("Username cannot be the same as the password.");
      return;
    }
    try {
      const payload = await api("/api/admin/users", {
        method: "POST",
        body: {
          email: form.email,
          password: form.password,
          display_name: username,
          monthly_ai_credits: Number(form.monthly_ai_credits || 0),
        },
      });
      setNotice(`Created ${payload.user?.email}. Share the password manually with the user.`);
      setForm({
        email: "",
        password: "",
        display_name: "",
        monthly_ai_credits: form.monthly_ai_credits,
      });
      await loadUsers();
      await onChanged();
    } catch (createError) {
      setError(createError.message);
    }
  }

  async function toggleUserActive(userItem) {
    setError("");
    try {
      await api(`/api/admin/users/${encodeURIComponent(userItem.id)}`, {
        method: "PATCH",
        body: { is_active: !userItem.is_active },
      });
      await loadUsers();
      await onChanged();
    } catch (toggleError) {
      setError(toggleError.message);
    }
  }

  async function resetUserUsage(userItem) {
    setError("");
    try {
      await api(`/api/admin/users/${encodeURIComponent(userItem.id)}`, {
        method: "PATCH",
        body: { reset_usage: true },
      });
      setNotice(`Reset usage and AI credits for ${userItem.email}.`);
      await loadUsers();
      await onChanged();
    } catch (resetError) {
      setError(resetError.message);
    }
  }

  async function saveUserCredits(userItem, limits) {
    setError("");
    setNotice("");
    try {
      await api(`/api/admin/users/${encodeURIComponent(userItem.id)}`, {
        method: "PATCH",
        body: {
          monthly_ai_credits: Number(limits.monthly_ai_credits || 0),
        },
      });
      setNotice(`Updated AI credits for ${userItem.email}.`);
      await loadUsers();
      await onChanged();
    } catch (saveError) {
      setError(saveError.message);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-line bg-panel shadow-2xl">
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <div>
            <p className="text-xs font-black uppercase tracking-normal text-worktual-700">Admin</p>
            <h2 className="text-xl font-black text-white">User accounts & AI credits</h2>
          </div>
          <IconButton label="Close admin panel" onClick={onClose}>
            <X size={16} />
          </IconButton>
        </div>
        <div className="grid min-h-0 flex-1 gap-0 overflow-hidden lg:grid-cols-[340px_minmax(0,1fr)]">
          <form className="space-y-3 overflow-y-auto border-b border-line p-5 lg:border-b-0 lg:border-r" autoComplete="off" onSubmit={handleCreateUser}>
            <p className="text-sm font-black text-white">Create user</p>
            <label className="block space-y-1.5">
              <span className="text-xs font-bold uppercase tracking-wide text-slate-400">Username</span>
              <input
                className="w-full rounded-lg border border-line px-3 py-2 text-sm"
                name="new-account-username"
                placeholder="Username"
                autoComplete="off"
                value={form.display_name}
                onChange={(e) => setForm((current) => ({ ...current, display_name: e.target.value }))}
                required
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-xs font-bold uppercase tracking-wide text-slate-400">Email</span>
              <input
                className="w-full rounded-lg border border-line px-3 py-2 text-sm"
                name="new-account-email"
                placeholder="Email"
                type="email"
                autoComplete="off"
                value={form.email}
                onChange={(e) => setForm((current) => ({ ...current, email: e.target.value }))}
                required
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-xs font-bold uppercase tracking-wide text-slate-400">Password</span>
              <input
                className="w-full rounded-lg border border-line px-3 py-2 text-sm"
                name="new-account-password"
                placeholder="Password"
                type="password"
                autoComplete="new-password"
                value={form.password}
                onChange={(e) => setForm((current) => ({ ...current, password: e.target.value }))}
                minLength={8}
                required
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-xs font-bold uppercase tracking-wide text-slate-400">Monthly AI credits</span>
              <input
                className="w-full rounded-lg border border-line px-3 py-2 text-sm"
                placeholder="1000"
                type="number"
                min="0"
                step="1"
                value={form.monthly_ai_credits}
                onChange={(e) => setForm((c) => ({ ...c, monthly_ai_credits: e.target.value }))}
              />
              <span className="block text-[11px] text-slate-500">1 credit = $0.01. 1000 credits = $10.</span>
            </label>
            <button
              type="submit"
              className="w-full rounded-lg border border-line bg-[#161616] px-3 py-2 text-xs font-semibold text-slate-200 transition hover:border-white/25 hover:bg-[#202020] hover:text-white"
            >
              Create account
            </button>
            {notice ? <p className="text-xs font-semibold text-emerald-300">{notice}</p> : null}
            {error ? <p className="text-xs font-semibold text-red-400">{error}</p> : null}
          </form>
          <div className="min-h-0 overflow-y-auto p-5">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-sm font-black text-white">Existing users</p>
              <button type="button" className="text-xs font-bold text-worktual-300" onClick={loadUsers}>Refresh</button>
            </div>
            {notice ? <p className="mb-3 text-xs font-semibold text-emerald-300">{notice}</p> : null}
            {error ? <p className="mb-3 text-xs font-semibold text-red-400">{error}</p> : null}
            {isLoading ? <p className="text-sm text-slate-400">Loading users...</p> : null}
            <div className="space-y-3">
              {users.map((userItem) => (
                <AdminUserLimitCard
                  key={userItem.id}
                  userItem={userItem}
                  isOpen={selectedUserId === userItem.id}
                  onToggleOpen={() => setSelectedUserId((current) => (current === userItem.id ? "" : userItem.id))}
                  onToggleActive={() => toggleUserActive(userItem)}
                  onResetUsage={() => resetUserUsage(userItem)}
                  onSaveCredits={(limits) => saveUserCredits(userItem, limits)}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function AdminUserLimitCard({ userItem, isOpen, onToggleOpen, onToggleActive, onResetUsage, onSaveCredits }) {
  const usage = userItem.usage || {};
  const monthly = usage.model_usage?.monthly || {};
  const creditAccount = usage.model_usage?.credit_account || {};
  const [showEditor, setShowEditor] = useState(false);
  const [limits, setLimits] = useState({
    monthly_ai_credits: String(creditAccount.included_monthly_credits || 1000),
  });

  useEffect(() => {
    setLimits({
      monthly_ai_credits: String(creditAccount.included_monthly_credits || 1000),
    });
  }, [creditAccount.included_monthly_credits, userItem.id]);

  const blocked = Boolean(usage.blocked_reason);

  return (
    <div className={`rounded-xl border p-3 ${blocked ? "border-amber-500/60 bg-amber-500/10" : "border-line bg-white/5"}`}>
      <button type="button" className="flex w-full items-start justify-between gap-3 text-left" onClick={onToggleOpen}>
        <div className="min-w-0">
          <p className="text-sm font-black text-white">{userItem.display_name || userItem.email}</p>
          <p className="text-xs text-slate-400">{userItem.email}</p>
          <p className="mt-1 text-[11px] font-bold uppercase tracking-wide text-slate-500">
            {userItem.role} · {userItem.is_active ? "active" : "suspended"}
          </p>
        </div>
        <span className="mt-1 inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-[11px] font-bold text-slate-300">
          {isOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          {isOpen ? "Hide details" : "View details"}
        </span>
      </button>
      {!isOpen ? null : (
        <>
        {userItem.role !== "admin" ? (
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" className="rounded-md border border-line px-2 py-1 text-[11px] font-bold" onClick={onToggleActive}>
              {userItem.is_active ? "Suspend" : "Activate"}
            </button>
            <button type="button" className="rounded-md border border-line px-2 py-1 text-[11px] font-bold" onClick={() => setShowEditor((v) => !v)}>
              {showEditor ? "Hide credit limit" : "Edit credit limit"}
            </button>
            <button type="button" className="rounded-md border border-line px-2 py-1 text-[11px] font-bold" onClick={onResetUsage}>
              Reset usage and credits
            </button>
          </div>
        ) : null}
        <CreditUsageInline usage={usage} />
        {showEditor && userItem.role !== "admin" ? (
          <div className="mt-3 grid gap-2 rounded-lg border border-line bg-black/20 p-3 sm:grid-cols-[minmax(0,1fr)_auto]">
            <label className="block space-y-1.5">
              <span className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Monthly AI credits</span>
              <input
                className="w-full rounded-md border border-line px-2 py-1.5 text-xs"
                type="number"
                min="0"
                step="1"
                value={limits.monthly_ai_credits}
                onChange={(e) => setLimits((current) => ({ ...current, monthly_ai_credits: e.target.value }))}
                placeholder="1000"
              />
            </label>
            <button
              type="button"
              className="self-end rounded-md bg-worktual-700 px-3 py-1.5 text-xs font-black text-white"
              onClick={() => onSaveCredits(limits)}
            >
              Save credits
            </button>
          </div>
        ) : null}
        {usage.unlimited ? (
          <div className="mt-2 space-y-2">
            <p className="text-xs text-emerald-300">Unlimited admin account</p>
            <TokenUsageBreakdown usage={usage} compact />
          </div>
        ) : (
          <>
          <p className="mt-2 text-xs text-slate-400">
            Monthly token diagnostics: {formatTokenCount(monthly.total_tokens)} tokens · {formatCredits(monthly.estimated_credits)} credits · {formatUsdCost(monthly.estimated_cost_usd)}
          </p>
          <div className="mt-3">
            <TokenUsageBreakdown usage={usage} compact />
          </div>
          {blocked ? <p className="mt-1 text-xs font-semibold text-amber-300">{usage.blocked_reason}</p> : null}
          </>
        )}
        </>
      )}
    </div>
  );
}

function UserSettingsModal({ session, usage, onClose, onSave, onRefreshUsage, activeProject = null, chatSessionId = "" }) {
  const [activeTab, setActiveTab] = useState("usage");
  const [displayName, setDisplayName] = useState(session?.display_name || "");
  const [email, setEmail] = useState(session?.email || "");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [profileSaveError, setProfileSaveError] = useState("");
  const [isRefreshingUsage, setIsRefreshingUsage] = useState(false);
  const [usageRefreshError, setUsageRefreshError] = useState("");
  const [usageRequestLimit, setUsageRequestLimit] = useState(null);

  const passwordMismatch = newPassword && newPassword !== confirmPassword;

  useEffect(() => {
    if (activeTab !== "usage" || typeof onRefreshUsage !== "function") return;
    let active = true;
    setIsRefreshingUsage(true);
    setUsageRefreshError("");
    onRefreshUsage()
      .catch((error) => {
        if (active) {
          setUsageRefreshError(error?.message || "Could not refresh token usage.");
        }
      })
      .finally(() => {
        if (active) setIsRefreshingUsage(false);
      });
    return () => {
      active = false;
      setIsRefreshingUsage(false);
    };
  }, [activeTab, onRefreshUsage]);

  async function handleRefreshUsage() {
    if (typeof onRefreshUsage !== "function" || isRefreshingUsage) return;
    setIsRefreshingUsage(true);
    setUsageRefreshError("");
    try {
      await onRefreshUsage({ recentRequestLimit: usageRequestLimit });
    } catch (error) {
      setUsageRefreshError(error?.message || "Could not refresh token usage.");
    } finally {
      setIsRefreshingUsage(false);
    }
  }

  async function handleLoadAllUsageRequests() {
    if (typeof onRefreshUsage !== "function") return;
    setUsageRequestLimit(TOKEN_USAGE_EXPANDED_REQUEST_LIMIT);
    return onRefreshUsage({ recentRequestLimit: TOKEN_USAGE_EXPANDED_REQUEST_LIMIT });
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (passwordMismatch || isSavingProfile) return;
    setProfileSaveError("");
    const updates = {};
    if (displayName.trim() !== (session?.display_name || "")) {
      updates.display_name = displayName.trim();
    }
    if (email.trim().toLowerCase() !== (session?.email || "").toLowerCase()) {
      updates.email = email.trim();
    }
    if (newPassword) {
      updates.current_password = currentPassword;
      updates.new_password = newPassword;
    }
    if (!Object.keys(updates).length) {
      onClose();
      return;
    }
    setIsSavingProfile(true);
    try {
      await onSave(updates);
    } catch (error) {
      setProfileSaveError(error?.message || "Could not save profile changes.");
    } finally {
      setIsSavingProfile(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4 py-6">
      <div className="flex max-h-[calc(100vh-3rem)] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-line bg-panel shadow-2xl">
        <div className="shrink-0 border-b border-line bg-panel/95 px-6 pb-4 pt-5 backdrop-blur">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-xs font-black uppercase tracking-normal text-worktual-700">Account</p>
              <h2 className="text-xl font-black text-white">User settings</h2>
              <p className="mt-1 text-sm text-slate-400">
                {activeTab === "usage"
                  ? "Track AI credits, estimated cost, and raw token diagnostics."
                  : activeTab === "memory"
                    ? "Teach the agent your durable coding preferences across projects."
                    : activeTab === "session"
                      ? "Review and manage remembered runs for the active project chat."
                      : "Update your display name, email, or password."}
              </p>
              {usage && !usage.unlimited ? (
                <p className="mt-2 text-xs font-semibold text-slate-300">
                  {formatCredits((usage.model_usage?.credit_account?.used_credits || 0) + (usage.model_usage?.credit_account?.reserved_credits || 0))}
                  /{formatCredits(usage.model_usage?.credit_account?.included_monthly_credits || 0)} credits monthly
                </p>
              ) : null}
            </div>
            <IconButton label="Close settings" onClick={onClose}>
              <X size={16} />
            </IconButton>
          </div>
        </div>
        <div className="shrink-0 overflow-x-auto border-b border-line bg-panel/95 px-6 py-3">
          <div className="flex min-w-max gap-2">
            <button
              type="button"
              className={`rounded-lg px-3 py-2 text-xs font-black uppercase tracking-wide ${
                activeTab === "usage" ? "bg-[#202020] text-white ring-1 ring-white/15" : "text-slate-400 hover:bg-white/5 hover:text-white"
              }`}
              onClick={() => setActiveTab("usage")}
            >
              AI credits
            </button>
            <button
              type="button"
              className={`rounded-lg px-3 py-2 text-xs font-black uppercase tracking-wide ${
                activeTab === "profile" ? "bg-[#202020] text-white ring-1 ring-white/15" : "text-slate-400 hover:bg-white/5 hover:text-white"
              }`}
              onClick={() => setActiveTab("profile")}
            >
              Profile
            </button>
            <button
              type="button"
              className={`rounded-lg px-3 py-2 text-xs font-black uppercase tracking-wide ${
                activeTab === "memory" ? "bg-[#202020] text-white ring-1 ring-white/15" : "text-slate-400 hover:bg-white/5 hover:text-white"
              }`}
              onClick={() => setActiveTab("memory")}
            >
              Memory preferences
            </button>
            <button
              type="button"
              className={`rounded-lg px-3 py-2 text-xs font-black uppercase tracking-wide ${
                activeTab === "session" ? "bg-[#202020] text-white ring-1 ring-white/15" : "text-slate-400 hover:bg-white/5 hover:text-white"
              }`}
              onClick={() => setActiveTab("session")}
            >
              Session memory
            </button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {activeTab === "usage" ? (
            <TokenUsagePanel
              usage={usage}
              isRefreshing={isRefreshingUsage}
              onRefresh={handleRefreshUsage}
              onLoadAllRequests={handleLoadAllUsageRequests}
              refreshError={usageRefreshError}
            />
          ) : activeTab === "profile" ? (
            <form className="space-y-4" onSubmit={handleSubmit}>
              {profileSaveError ? <ErrorBanner message={profileSaveError} /> : null}
              <label className="block space-y-1.5">
                <span className="text-xs font-bold uppercase tracking-wide text-slate-400">Display name</span>
                <input
                  className="w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none ring-worktual-500 focus:ring-2"
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  placeholder="Your name"
                />
              </label>
              <label className="block space-y-1.5">
                <span className="text-xs font-bold uppercase tracking-wide text-slate-400">Email</span>
                <input
                  className="w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none ring-worktual-500 focus:ring-2"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  required
                />
              </label>
              <div className="rounded-xl border border-line bg-black/30 p-4">
                <p className="mb-3 text-xs font-black uppercase tracking-wide text-slate-400">Change password</p>
                <div className="space-y-3">
                  <input
                    className="w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none ring-worktual-500 focus:ring-2"
                    type="password"
                    value={currentPassword}
                    onChange={(event) => setCurrentPassword(event.target.value)}
                    placeholder="Current password"
                    autoComplete="current-password"
                  />
                  <input
                    className="w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none ring-worktual-500 focus:ring-2"
                    type="password"
                    value={newPassword}
                    onChange={(event) => setNewPassword(event.target.value)}
                    placeholder="New password"
                    autoComplete="new-password"
                    minLength={8}
                  />
                  <input
                    className="w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none ring-worktual-500 focus:ring-2"
                    type="password"
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    placeholder="Confirm new password"
                    autoComplete="new-password"
                    minLength={8}
                  />
                  {passwordMismatch ? <span className="text-xs font-semibold text-red-400">New passwords do not match.</span> : null}
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  className="rounded-lg border border-line px-4 py-2 text-sm font-bold text-slate-300 hover:bg-white/5"
                  onClick={onClose}
                  disabled={isSavingProfile}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="rounded-lg bg-worktual-700 px-4 py-2 text-sm font-black text-white hover:bg-worktual-600 disabled:opacity-60"
                  disabled={isSavingProfile || passwordMismatch}
                >
                  {isSavingProfile ? "Saving..." : "Save changes"}
                </button>
              </div>
            </form>
          ) : activeTab === "session" ? (
            <SessionMemoryPanel
              projectId={activeProject?.id || ""}
              chatSessionId={chatSessionId || ""}
              projectName={activeProject?.name || ""}
            />
          ) : (
            <MemoryPreferencesPanel onClose={onClose} />
          )}
        </div>
      </div>
    </div>
  );
}

function MemoryPreferencesPanel({ onClose }) {
  const [preferences, setPreferences] = useState([]);
  const [injectionRules, setInjectionRules] = useState(null);
  const [isLoadingPrefs, setIsLoadingPrefs] = useState(true);
  const [isSavingPref, setIsSavingPref] = useState(false);
  const [prefError, setPrefError] = useState("");
  const [category, setCategory] = useState("coding_style");
  const [preferenceText, setPreferenceText] = useState("");
  const [polarity, setPolarity] = useState("positive");
  const [durability, setDurability] = useState("long_term");

  useEffect(() => {
    let cancelled = false;
    async function loadPreferences() {
      setIsLoadingPrefs(true);
      setPrefError("");
      try {
        const payload = await api("/api/users/me/memory/preferences");
        if (cancelled) return;
        setPreferences(Array.isArray(payload.preferences) ? payload.preferences : []);
        setInjectionRules(payload.injection_rules || null);
      } catch (nextError) {
        if (!cancelled) setPrefError(nextError.message);
      } finally {
        if (!cancelled) setIsLoadingPrefs(false);
      }
    }
    loadPreferences();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleAddPreference(event) {
    event.preventDefault();
    const trimmedCategory = category.trim();
    const trimmedPreference = preferenceText.trim();
    if (!trimmedCategory || !trimmedPreference) return;
    setIsSavingPref(true);
    setPrefError("");
    try {
      const payload = await api("/api/users/me/memory/preferences", {
        method: "POST",
        body: {
          category: trimmedCategory,
          preference: trimmedPreference,
          polarity,
          durability,
          confidence: 0.85,
        },
      });
      const saved = payload.preference;
      setPreferences((current) => {
        const withoutDuplicate = current.filter(
          (item) => !(item.category === saved.category && item.preference === saved.preference),
        );
        return [saved, ...withoutDuplicate];
      });
      setPreferenceText("");
    } catch (nextError) {
      setPrefError(nextError.message);
    } finally {
      setIsSavingPref(false);
    }
  }

  async function handleDeletePreference(preferenceId) {
    if (!preferenceId) return;
    setPrefError("");
    try {
      await api(`/api/users/me/memory/preferences/${encodeURIComponent(preferenceId)}`, { method: "DELETE" });
      setPreferences((current) => current.filter((item) => item.id !== preferenceId));
    } catch (nextError) {
      setPrefError(nextError.message);
    }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-line bg-black/20 p-4">
        <div className="mb-2 flex items-center gap-2 text-xs font-black uppercase tracking-wide text-slate-300">
          <ShieldCheck size={14} />
          Agent memory preferences
        </div>
        <p className="text-sm text-slate-400">
          Preferences with confidence ≥ {injectionRules?.min_confidence ?? 0.6} and long-term durability are injected into
          every generation context for your account.
        </p>
      </div>
      {prefError ? <ErrorBanner message={prefError} /> : null}
      <form className="grid gap-3 rounded-xl border border-line bg-black/30 p-4" onSubmit={handleAddPreference}>
        <p className="text-xs font-black uppercase tracking-wide text-slate-400">Add preference</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block space-y-1.5">
            <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Category</span>
            <select
              className="w-full rounded-lg border border-line bg-panel px-3 py-2.5 text-sm outline-none ring-worktual-500 focus:ring-2"
              value={category}
              onChange={(event) => setCategory(event.target.value)}
            >
              <option value="coding_style">Coding style</option>
              <option value="stack">Stack / framework</option>
              <option value="workflow">Workflow</option>
              <option value="communication">Communication</option>
              <option value="general">General</option>
            </select>
          </label>
          <label className="block space-y-1.5">
            <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Type</span>
            <select
              className="w-full rounded-lg border border-line bg-panel px-3 py-2.5 text-sm outline-none ring-worktual-500 focus:ring-2"
              value={polarity}
              onChange={(event) => setPolarity(event.target.value)}
            >
              <option value="positive">Prefer</option>
              <option value="negative">Avoid</option>
            </select>
          </label>
        </div>
        <label className="block space-y-1.5">
          <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Preference</span>
          <input
            className="w-full rounded-lg border border-line px-3 py-2.5 text-sm outline-none ring-worktual-500 focus:ring-2"
            value={preferenceText}
            onChange={(event) => setPreferenceText(event.target.value)}
            placeholder="e.g. Use functional React components with hooks"
          />
        </label>
        <label className="block space-y-1.5">
          <span className="text-xs font-bold uppercase tracking-wide text-slate-500">Durability</span>
          <select
            className="w-full rounded-lg border border-line bg-panel px-3 py-2.5 text-sm outline-none ring-worktual-500 focus:ring-2"
            value={durability}
            onChange={(event) => setDurability(event.target.value)}
          >
            <option value="long_term">Long term (injected into agent context)</option>
            <option value="session">Session only</option>
          </select>
        </label>
        <div className="flex justify-end">
          <button
            type="submit"
            className="rounded-lg bg-worktual-700 px-4 py-2 text-sm font-black text-white hover:bg-worktual-600 disabled:opacity-60"
            disabled={isSavingPref || !preferenceText.trim()}
          >
            {isSavingPref ? "Saving..." : "Save preference"}
          </button>
        </div>
      </form>
      <div className="rounded-xl border border-line bg-black/20 p-4">
        <p className="mb-3 text-xs font-black uppercase tracking-wide text-slate-400">Saved preferences</p>
        {isLoadingPrefs ? (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Loader2 className="animate-spin" size={16} />
            Loading preferences...
          </div>
        ) : preferences.length ? (
          <div className="grid gap-2">
            {preferences.map((item) => (
              <div key={item.id || `${item.category}-${item.preference}`} className="rounded-lg border border-line bg-panel/40 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-md bg-slate-800 px-2 py-0.5 text-[10px] font-black uppercase tracking-wide text-slate-300">
                        {item.category}
                      </span>
                      {item.injected_into_agent_context ? (
                        <span className="rounded-md bg-emerald-950/50 px-2 py-0.5 text-[10px] font-black uppercase tracking-wide text-emerald-300">
                          Active in agent context
                        </span>
                      ) : (
                        <span className="rounded-md bg-slate-800 px-2 py-0.5 text-[10px] font-black uppercase tracking-wide text-slate-500">
                          Stored only
                        </span>
                      )}
                    </div>
                    <p className="mt-2 text-sm font-semibold text-white">
                      {item.polarity === "negative" ? "Avoid" : "Prefer"}: {item.preference}
                    </p>
                  </div>
                  <button
                    type="button"
                    className="shrink-0 rounded-md border border-line px-2 py-1 text-[11px] font-bold text-slate-400 hover:bg-white/5 hover:text-red-300"
                    onClick={() => handleDeletePreference(item.id)}
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-500">No preferences saved yet. Add one above to guide future generations.</p>
        )}
      </div>
      <div className="flex justify-end">
        <button
          type="button"
          className="rounded-lg border border-line px-4 py-2 text-sm font-bold text-slate-300 hover:bg-white/5"
          onClick={onClose}
        >
          Close
        </button>
      </div>
    </div>
  );
}

function ErrorBanner({ message }) {
  return (
    <div className="shrink-0 overflow-hidden border-y border-line bg-slate-100 px-4 py-2 text-sm font-bold text-ink">
      <span className="wt-wrap-anywhere inline-flex max-w-full items-start gap-2">
        <AlertTriangle className="mt-0.5 shrink-0" size={16} />
        <span className="min-w-0">{message}</span>
      </span>
    </div>
  );
}

function PanelResizeHandle({ label, onPointerDown }) {
  return (
    <button
      className="group z-0 flex min-w-0 cursor-col-resize items-center justify-center self-stretch border-x border-transparent bg-canvas transition hover:bg-worktual-50 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-worktual-500"
      type="button"
      aria-label={label}
      title={label}
      onPointerDown={onPointerDown}
    >
      <span className="h-10 w-px rounded-full bg-line transition group-hover:bg-worktual-500" />
    </button>
  );
}

function ProjectHistory({
  activeProject,
  deletingProjectId,
  isCreating,
  isCollapsed,
  isProjectSearchOpen,
  projectSearchQuery,
  projects,
  onCreateProject,
  onDeleteProject,
  onOpenProject,
  onProjectSearchChange,
  onTogglePanel,
  onToggleProjectSearch,
}) {
  const visibleProjects = useMemo(() => {
    const query = projectSearchQuery.trim().toLowerCase();
    if (!query) return projects;
    return projects.filter((project) => projectSidebarTitle(project).toLowerCase().includes(query));
  }, [projects, projectSearchQuery]);

  if (isCollapsed) {
    return (
      <aside className="flex min-h-0 flex-col items-center border-r border-line bg-panel py-3 text-ink">
        <IconButton label="Open project panel" onClick={onTogglePanel}>
          <PanelRightOpen size={16} />
        </IconButton>
        <span
          className="mt-3 text-[11px] font-semibold uppercase tracking-normal text-slate-500"
          style={{ writingMode: "vertical-rl" }}
        >
          Projects
        </span>
      </aside>
    );
  }

  return (
    <aside className="wt-project-sidebar flex min-h-0 min-w-0 flex-col overflow-hidden border-r border-line bg-panel text-ink">
      <div className="grid gap-1.5 border-b border-line bg-panel p-2">
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_32px] items-center gap-1.5">
        <button
          className="wt-control-button flex min-h-8 min-w-0 items-center justify-center gap-1.5 rounded-md px-2 text-[10px] font-bold transition disabled:cursor-not-allowed disabled:opacity-50"
          type="button"
          onClick={onCreateProject}
          disabled={isCreating}
          title="Create project"
        >
          {isCreating ? <Loader2 className="animate-spin" size={14} /> : <FolderPlus size={14} />}
          <span className="truncate">Create</span>
        </button>
        <button
          className={`flex min-h-8 min-w-0 items-center justify-center gap-1.5 rounded-md px-2 text-[10px] font-bold transition ${
            isProjectSearchOpen ? "bg-worktual-50 text-worktual-700 ring-1 ring-worktual-300/40" : "wt-control-button"
          }`}
          type="button"
          onClick={onToggleProjectSearch}
          title="Search projects"
        >
          <Search size={14} />
          <span className="truncate">Search</span>
        </button>
          <IconButton compact label="Minimize project panel" onClick={onTogglePanel}>
            <PanelLeftClose size={14} />
          </IconButton>
        </div>
      </div>
      {isProjectSearchOpen ? (
        <div className="border-b border-line bg-panel p-2">
          <label className="sr-only" htmlFor="project-search">Search projects</label>
          <div className="flex min-h-9 items-center gap-2 rounded-lg border border-line bg-black/20 px-2 focus-within:border-worktual-500">
            <Search className="shrink-0 text-slate-400" size={15} />
            <input
              id="project-search"
              className="min-w-0 flex-1 border-0 bg-transparent text-[10.5px] font-bold text-ink outline-none placeholder:text-slate-400"
              placeholder="Search projects..."
              value={projectSearchQuery}
              onChange={(event) => onProjectSearchChange(event.target.value)}
            />
          </div>
        </div>
      ) : null}
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {visibleProjects.length ? (
          <div className="grid gap-2">
            {visibleProjects.map((project) => (
              <div
                key={project.id}
                className={`group grid grid-cols-[minmax(0,1fr)_32px] items-center rounded-lg border-l-4 transition ${
                  activeProject?.id === project.id
                    ? "wt-active-project text-ink shadow-sm ring-1 ring-line"
                    : "border-transparent bg-white/30 text-slate-700 hover:bg-white"
                }`}
              >
                <button className="min-w-0 px-3 py-2.5 text-left" type="button" onClick={() => onOpenProject(project)}>
                  <span className="block truncate text-[10.5px] font-semibold">{projectSidebarTitle(project)}</span>
                </button>
                <button
                  className="mr-1 inline-flex size-8 items-center justify-center rounded-md text-slate-400 opacity-70 transition hover:bg-slate-100 hover:text-slate-950 group-hover:opacity-100 disabled:cursor-not-allowed disabled:opacity-40"
                  type="button"
                  title={`Delete ${project.name}`}
                  aria-label={`Delete ${project.name}`}
                  onClick={() => onDeleteProject(project)}
                  disabled={Boolean(deletingProjectId)}
                >
                  {deletingProjectId === project.id ? <Loader2 className="animate-spin" size={15} /> : <Trash2 size={15} />}
                </button>
              </div>
            ))}
          </div>
        ) : projects.length ? (
          <div className="p-3">
            <p className="text-[10.5px] leading-relaxed text-slate-500">No matching projects.</p>
          </div>
        ) : (
          <div className="p-3">
            <p className="text-[10.5px] leading-relaxed text-slate-500">No projects yet.</p>
          </div>
        )}
      </div>
    </aside>
  );
}

function NewProjectModal({
  isBusy,
  helperCheck,
  onChooseLocal,
  onClose,
  onCheckLocalHelper,
  onCreateBackend,
}) {
  const helperStatus = helperCheck?.status || "idle";
  const helperIsChecking = helperStatus === "checking";
  const helperIsHealthy = helperStatus === "healthy";
  const helperIsUnhealthy = helperStatus === "unhealthy";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 px-4">
      <div className="w-full max-w-2xl overflow-hidden rounded-xl border border-line bg-[#0f0f0f] font-sans shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-line bg-[#0f0f0f] px-4 py-3 text-ink">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">New project session</p>
            <h2 className="mt-0.5 text-base font-semibold text-white">Choose workspace mode</h2>
          </div>
          <IconButton label="Close new project dialog" onClick={onClose} disabled={isBusy}>
            <X size={17} />
          </IconButton>
        </div>
        <div className="grid gap-3 p-4">
          <p className="text-xs font-medium leading-relaxed text-slate-400">
            The project name will be created from your first website request.
          </p>
          <div className="grid gap-3 md:grid-cols-[1fr_auto] md:items-start">
            <button
              className="group rounded-lg border border-line bg-[#151515] px-3 py-2.5 text-left transition hover:border-white/20 hover:bg-[#1c1c1c] disabled:cursor-not-allowed disabled:opacity-50"
              type="button"
              onClick={onCheckLocalHelper}
              disabled={isBusy || helperIsChecking}
            >
              <span className="flex items-start gap-3">
                <span
                  className={`mt-0.5 inline-flex size-8 items-center justify-center rounded-md ${
                    helperIsHealthy
                      ? "bg-emerald-500/10 text-emerald-300"
                      : helperIsUnhealthy
                        ? "bg-rose-500/10 text-rose-300"
                        : "bg-white/5 text-slate-300"
                  }`}
                >
                  {helperIsChecking ? (
                    <Loader2 className="animate-spin" size={14} />
                  ) : helperIsHealthy ? (
                    <CheckCircle2 size={14} />
                  ) : helperIsUnhealthy ? (
                    <AlertTriangle size={14} />
                  ) : (
                    <Server size={14} />
                  )}
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-slate-100">Check Local Helper</span>
                  <span className="mt-1 block text-xs font-medium leading-relaxed text-slate-400">
                    Verify this customer browser can reach the helper running on this same machine before importing or reconnecting a local project.
                  </span>
                </span>
              </span>
            </button>
            {helperStatus !== "idle" ? (
              <div
                className={`rounded-lg border px-3 py-2 text-xs leading-relaxed ${
                  helperIsHealthy
                    ? "border-emerald-400/25 bg-emerald-500/10 text-emerald-200"
                    : helperIsUnhealthy
                      ? "border-rose-400/25 bg-rose-500/10 text-rose-200"
                      : "border-line bg-white/5 text-slate-300"
                }`}
              >
                <div className="flex items-center gap-2">
                  {helperIsChecking ? (
                    <Loader2 className="animate-spin" size={13} />
                  ) : helperIsHealthy ? (
                    <CheckCircle2 size={13} />
                  ) : (
                    <AlertTriangle size={13} />
                  )}
                  <p className="text-xs font-semibold">
                    {helperIsChecking
                      ? "Checking helper..."
                      : helperIsHealthy
                        ? "Local helper is ready"
                        : "Local helper is not reachable"}
                  </p>
                </div>
                {helperCheck?.message ? <p className="mt-2 font-medium">{helperCheck.message}</p> : null}
                {helperCheck?.details ? <p className="mt-1 text-[11px] font-medium opacity-80">{helperCheck.details}</p> : null}
                {helperCheck?.startupCommand ? (
                  <pre className="wt-log-pre mt-3 rounded-lg bg-slate-950 px-3 py-2 text-[11px] leading-relaxed text-slate-100">
                    {helperCheck.startupCommand}
                  </pre>
                ) : null}
              </div>
            ) : null}
          </div>
          {localFolderAccessHint() ? (
            <p className="rounded-lg border border-amber-400/25 bg-amber-500/10 px-3 py-2 text-xs font-medium leading-relaxed text-amber-200">
              {localFolderAccessHint()}
            </p>
          ) : null}
          <div className="grid gap-3 md:grid-cols-2">
            <button
              className="group min-h-36 rounded-lg border border-line bg-[#151515] p-3 text-left transition hover:border-white/20 hover:bg-[#1c1c1c] disabled:cursor-not-allowed disabled:opacity-50"
              type="button"
              onClick={onChooseLocal}
              disabled={isBusy}
            >
              <span className="mb-3 inline-flex size-8 items-center justify-center rounded-md bg-white/5 text-slate-300 group-hover:bg-white/10 group-hover:text-white">
                <FolderOpen size={15} />
              </span>
              <span className="block text-sm font-semibold text-slate-100">Import local project</span>
              <span className="mt-2 block text-xs font-medium leading-relaxed text-slate-400">
                Pick a local folder with guided access approval. Worktual will explain permissions in-app before your browser asks to allow edits.
              </span>
            </button>
            <button
              className="group min-h-36 rounded-lg border border-line bg-[#151515] p-3 text-left transition hover:border-white/20 hover:bg-[#1c1c1c] disabled:cursor-not-allowed disabled:opacity-50"
              type="button"
              onClick={onCreateBackend}
              disabled={isBusy}
            >
              <span className="mb-3 inline-flex size-8 items-center justify-center rounded-md bg-white/5 text-slate-300 group-hover:bg-white/10 group-hover:text-white">
                {isBusy ? <Loader2 className="animate-spin" size={15} /> : <Server size={15} />}
              </span>
              <span className="block text-sm font-semibold text-slate-100">Backend workspace</span>
              <span className="mt-2 block text-xs font-medium leading-relaxed text-slate-400">
                Keep project files in the backend store and use the per-project runtime folder only when previewing.
              </span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function FolderAccessModal({ ui, onAllowPermission, onCancel, onChooseFolder, onReadOnlyUpload, onRetry }) {
  const step = ui?.step || "intro";
  const purpose = ui?.purpose || "import";
  const folderHint = ui?.folderHint || "";
  const folderName = ui?.folderName || folderHint || "your project folder";
  const showReadOnlyOption = purpose !== "reconnect" && supportsWritableBrowserDirectoryPicker();
  const isBusy = step === "picking" || step === "permission-pending";
  const title =
    purpose === "reconnect"
      ? "Reconnect local folder"
      : purpose === "attach"
        ? "Link local folder"
        : "Allow folder access";
  const introCopy =
    purpose === "reconnect"
      ? `Worktual needs write access to "${folderHint || folderName}" so generated files and edits can sync back to disk.`
      : "Worktual needs permission to read and save files in the folder you choose. Generated code and manual edits will sync back to that folder.";

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 px-4">
      <div className="wt-hidden-scrollbar max-h-[calc(100vh-4rem)] w-full max-w-lg overflow-y-auto rounded-xl border border-line bg-[#0f0f0f] font-sans shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-line px-4 py-3">
          <div className="flex items-start gap-3">
            <span className="inline-flex size-8 shrink-0 items-center justify-center rounded-md bg-white/5 text-slate-200">
              <ShieldCheck size={15} />
            </span>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Local folder access</p>
              <h2 className="mt-0.5 text-base font-semibold text-white">{title}</h2>
            </div>
          </div>
          <IconButton label="Close folder access dialog" onClick={onCancel} disabled={isBusy}>
            <X size={17} />
          </IconButton>
        </div>

        <div className="grid gap-3 p-4">
          {step === "intro" ? (
            <>
              <p className="text-xs font-medium leading-relaxed text-slate-400">{introCopy}</p>
              <ul className="grid gap-2 rounded-lg border border-line bg-[#151515] px-3 py-3 text-xs font-medium leading-relaxed text-slate-300">
                <li>1. Choose your project folder in the system picker.</li>
                <li>2. Approve edit access when your browser asks — click Allow.</li>
                <li>3. Worktual will import files and write generated changes back to that folder.</li>
              </ul>
              {localFolderAccessHint() ? (
                <p className="rounded-lg border border-amber-400/25 bg-amber-500/10 px-3 py-2 text-xs font-medium leading-relaxed text-amber-200">
                  {localFolderAccessHint()}
                </p>
              ) : null}
            </>
          ) : null}

          {step === "picking" ? (
            <div className="flex items-center gap-3 rounded-lg border border-line bg-[#151515] px-3 py-3 text-xs font-medium text-slate-300">
              <Loader2 className="animate-spin text-slate-200" size={14} />
              Select your project folder in the system dialog…
            </div>
          ) : null}

          {step === "permission" || step === "permission-pending" ? (
            <>
              <p className="text-xs font-medium leading-relaxed text-slate-400">
                Allow Worktual to edit files in <span className="font-semibold text-white">{folderName}</span> so generated
                changes can be saved back to disk.
              </p>
              <div className="rounded-lg border border-line bg-[#151515] px-3 py-3 text-xs font-medium leading-relaxed text-slate-300">
                Your browser will show a permission prompt next. Click <span className="font-semibold text-white">Allow</span> to
                enable local write-back.
              </div>
            </>
          ) : null}

          {step === "error" && ui?.error ? (
            <div className="rounded-lg border border-rose-400/25 bg-rose-500/10 px-3 py-3 text-xs font-medium leading-relaxed text-rose-200">
              {ui.error}
            </div>
          ) : null}

          <div className="flex flex-wrap items-center justify-end gap-2">
            {step === "error" ? (
              <button
                className="rounded-lg border border-line bg-[#151515] px-3 py-2 text-xs font-semibold text-slate-200 transition hover:border-white/20 hover:bg-[#202020] hover:text-white"
                type="button"
                onClick={onRetry}
              >
                Try again
              </button>
            ) : null}
            <button
              className="rounded-lg border border-line bg-[#151515] px-3 py-2 text-xs font-semibold text-slate-200 transition hover:border-white/20 hover:bg-[#202020] hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
              type="button"
              onClick={onCancel}
              disabled={isBusy}
            >
              Cancel
            </button>
            {showReadOnlyOption && step === "intro" ? (
              <button
                className="rounded-lg border border-line bg-[#151515] px-3 py-2 text-xs font-semibold text-slate-200 transition hover:border-white/20 hover:bg-[#202020] hover:text-white"
                type="button"
                onClick={onReadOnlyUpload}
              >
                Read-only upload
              </button>
            ) : null}
            {step === "intro" ? (
              <button
                className="inline-flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-xs font-semibold text-black transition hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50"
                type="button"
                onClick={onChooseFolder}
              >
                <FolderOpen size={13} />
                Choose folder
              </button>
            ) : null}
            {step === "permission" ? (
              <button
                className="inline-flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-xs font-semibold text-black transition hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50"
                type="button"
                onClick={onAllowPermission}
                disabled={step === "permission-pending"}
              >
                {step === "permission-pending" ? <Loader2 className="animate-spin" size={13} /> : <ShieldCheck size={13} />}
                Allow access
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function buildMemoryEpisodesUrl(projectId, chatSessionId, prompt = "") {
  const params = new URLSearchParams({
    project_id: projectId,
    chat_session_id: chatSessionId,
  });
  const trimmedPrompt = String(prompt || "").trim();
  if (trimmedPrompt) {
    params.set("prompt", trimmedPrompt);
  }
  return `/api/users/me/memory/episodes?${params.toString()}`;
}

function formatMemoryTimestamp(value = "") {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function SessionMemoryPanel({
  projectId = "",
  chatSessionId = "",
  projectName = "",
  prompt = "",
  compact = false,
  onEpisodesChange,
}) {
  const [episodes, setEpisodes] = useState([]);
  const [sessionState, setSessionState] = useState(null);
  const [injectionRules, setInjectionRules] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [isOpen, setIsOpen] = useState(true);
  const loadGenerationRef = useRef(0);
  const promptRefreshGenerationRef = useRef(0);

  function applyEpisodesPayload(payload) {
    const nextEpisodes = Array.isArray(payload?.episodes) ? payload.episodes : [];
    setEpisodes(nextEpisodes);
    setSessionState(payload?.session_memory_state || null);
    setInjectionRules(payload?.injection_rules || null);
    onEpisodesChange?.(nextEpisodes);
  }

  // Load session memory when the project or chat session changes — not on every keystroke.
  useEffect(() => {
    const generation = ++loadGenerationRef.current;
    let cancelled = false;

    async function loadEpisodes() {
      if (!projectId || !chatSessionId) {
        if (loadGenerationRef.current === generation) {
          setEpisodes([]);
          setSessionState(null);
          setIsLoading(false);
        }
        return;
      }
      setIsLoading(true);
      setError("");
      try {
        const payload = await api(buildMemoryEpisodesUrl(projectId, chatSessionId, ""));
        if (cancelled || loadGenerationRef.current !== generation) return;
        applyEpisodesPayload(payload);
      } catch (nextError) {
        if (!cancelled && loadGenerationRef.current === generation) {
          setError(nextError.message);
        }
      } finally {
        if (!cancelled && loadGenerationRef.current === generation) {
          setIsLoading(false);
        }
      }
    }
    loadEpisodes();
    return () => {
      cancelled = true;
    };
  }, [projectId, chatSessionId]);

  // Debounced relevance refresh for "active in agent context" badges while drafting a prompt.
  useEffect(() => {
    const trimmedPrompt = String(prompt || "").trim();
    if (!projectId || !chatSessionId || !trimmedPrompt || isLoading) return;

    const generation = ++promptRefreshGenerationRef.current;
    const timer = window.setTimeout(async () => {
      try {
        const payload = await api(buildMemoryEpisodesUrl(projectId, chatSessionId, trimmedPrompt));
        if (promptRefreshGenerationRef.current !== generation) return;
        applyEpisodesPayload(payload);
      } catch {
        // Keep the last loaded episode list if relevance refresh fails.
      }
    }, 400);

    return () => {
      window.clearTimeout(timer);
    };
  }, [projectId, chatSessionId, prompt, isLoading]);

  async function handleDeleteEpisode(episodeId) {
    if (!episodeId || !projectId) return;
    setError("");
    try {
      await api(
        `/api/users/me/memory/episodes/${encodeURIComponent(episodeId)}?project_id=${encodeURIComponent(projectId)}`,
        { method: "DELETE" },
      );
      setEpisodes((current) => {
        const next = current.filter((item) => item.id !== episodeId);
        onEpisodesChange?.(next);
        return next;
      });
    } catch (nextError) {
      setError(nextError.message);
    }
  }

  if (!projectId || !chatSessionId) {
    return compact ? null : (
      <div className="rounded-xl border border-line bg-black/20 p-4 text-sm text-slate-500">
        Open a project chat to view session memory.
      </div>
    );
  }

  const hasSessionSummary = Boolean(String(sessionState?.rolling_summary || "").trim());
  const hasVisibleMemory = episodes.length > 0 || hasSessionSummary;
  if (compact && !isLoading && !hasVisibleMemory) {
    return null;
  }

  const shellClassName = compact
    ? "rounded-xl border border-line bg-white/80 px-4 py-3"
    : "space-y-4";

  return (
    <div className={shellClassName}>
      {compact ? (
        <button
          type="button"
          className="flex w-full items-center justify-between gap-3 text-left"
          onClick={() => setIsOpen((current) => !current)}
        >
          <span className="text-xs font-black uppercase tracking-wide text-worktual-700">
            Session memory · {episodes.length} remembered run{episodes.length === 1 ? "" : "s"}
          </span>
          {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
      ) : (
        <div className="rounded-xl border border-line bg-black/20 p-4">
          <div className="mb-2 flex items-center gap-2 text-xs font-black uppercase tracking-wide text-slate-300">
            <ShieldCheck size={14} />
            Session memory
          </div>
          <p className="text-sm text-slate-400">
            {projectName ? `${projectName} · ` : ""}
            Episodes scoped to this chat only. Up to {injectionRules?.max_injected_episodes ?? 5} runs may be injected
            into the agent prompt based on relevance.
          </p>
        </div>
      )}
      {error ? <ErrorBanner message={error} /> : null}
      {(!compact || isOpen) ? (
        <div className={compact ? "mt-3 space-y-3" : "space-y-4"}>
          {hasSessionSummary ? (
            <div className={`rounded-lg border border-line ${compact ? "bg-slate-50 px-3 py-2" : "bg-panel/40 p-3"}`}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[10px] font-black uppercase tracking-wide text-worktual-700">Session summary</span>
                {sessionState?.update_count ? (
                  <span className="text-[10px] font-bold text-muted">{sessionState.update_count} update(s)</span>
                ) : null}
              </div>
              <p className={`mt-2 whitespace-pre-wrap ${compact ? "text-xs text-muted" : "text-sm text-slate-300"}`}>
                {String(sessionState.rolling_summary).slice(0, compact ? 320 : 1200)}
              </p>
            </div>
          ) : null}
          {isLoading ? (
            <div className={`flex items-center gap-2 ${compact ? "text-xs text-muted" : "text-sm text-slate-400"}`}>
              <Loader2 className="animate-spin" size={16} />
              Loading session memory...
            </div>
          ) : episodes.length ? (
            <ul className="space-y-2">
              {episodes.map((memory) => (
                <li
                  key={memory.id || memory.key}
                  className={`rounded-lg border border-line ${compact ? "bg-slate-50 px-3 py-2" : "bg-panel/40 p-3"}`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`font-black capitalize text-ink ${compact ? "text-xs" : "text-sm"}`}>
                          {formatEpisodicIntent(memory.intent)}
                        </span>
                        <span
                          className={`font-bold ${memory.outcome === "failed" ? "text-red-600" : "text-worktual-700"} ${compact ? "text-xs" : "text-sm"}`}
                        >
                          {memory.outcome || "completed"}
                        </span>
                        {memory.injected_into_agent_context ? (
                          <span className="rounded-md bg-emerald-950/50 px-2 py-0.5 text-[10px] font-black uppercase tracking-wide text-emerald-300">
                            Active in agent context
                          </span>
                        ) : (
                          <span className="rounded-md bg-slate-800 px-2 py-0.5 text-[10px] font-black uppercase tracking-wide text-slate-500">
                            Stored only
                          </span>
                        )}
                      </div>
                      {memory.searchable_summary || memory.content ? (
                        <p className={`mt-2 whitespace-pre-wrap ${compact ? "text-xs text-muted" : "text-sm text-slate-300"}`}>
                          {String(memory.searchable_summary || memory.content).slice(0, compact ? 220 : 600)}
                        </p>
                      ) : null}
                      {memory.changed_paths?.length ? (
                        <p className={`mt-1 font-medium text-muted ${compact ? "text-xs" : "text-sm"}`}>
                          Files: {memory.changed_paths.slice(0, 3).join(", ")}
                          {memory.changed_paths.length > 3 ? ` +${memory.changed_paths.length - 3} more` : ""}
                        </p>
                      ) : null}
                      {formatMemoryTimestamp(memory.recorded_at || memory.updated_at) ? (
                        <p className={`mt-1 text-muted ${compact ? "text-[11px]" : "text-xs"}`}>
                          {formatMemoryTimestamp(memory.recorded_at || memory.updated_at)}
                        </p>
                      ) : null}
                    </div>
                    <button
                      type="button"
                      className="shrink-0 rounded-md border border-line px-2 py-1 text-[11px] font-bold text-slate-400 hover:bg-white/5 hover:text-red-300"
                      onClick={() => handleDeleteEpisode(memory.id)}
                    >
                      Remove
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className={`${compact ? "text-xs text-muted" : "text-sm text-slate-500"}`}>
              No remembered runs yet. Code-changing generations in this chat will appear here.
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
}

function formatEpisodicIntent(intent = "") {
  return String(intent || "run").replace(/_/g, " ");
}

function formatAttachmentSize(bytes = 0) {
  const size = Number(bytes) || 0;
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function isImageAttachmentMime(mimeType = "") {
  return String(mimeType || "").startsWith("image/");
}

function inferAttachmentMimeType(name = "", mimeType = "") {
  if (mimeType) return mimeType;
  const lowered = String(name || "").toLowerCase();
  if (lowered.endsWith(".png")) return "image/png";
  if (lowered.endsWith(".jpg") || lowered.endsWith(".jpeg")) return "image/jpeg";
  if (lowered.endsWith(".webp")) return "image/webp";
  if (lowered.endsWith(".gif")) return "image/gif";
  if (lowered.endsWith(".svg")) return "image/svg+xml";
  return "application/octet-stream";
}

function createPromptAttachment(file) {
  const name = file.name || "attachment";
  const mimeType = inferAttachmentMimeType(name, file.type || "");
  const kind = isImageAttachmentMime(mimeType) ? "image" : "file";
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    file,
    name,
    mimeType,
    size: file.size,
    kind,
    contentBase64: "",
    previewUrl: kind === "image" ? URL.createObjectURL(file) : "",
  };
}

async function enrichAttachmentWithData(attachment) {
  if (!attachment || attachment.contentBase64 || attachment.kind !== "image" || !attachment.file) {
    return attachment;
  }
  try {
    return {
      ...attachment,
      contentBase64: await readFileAsBase64(attachment.file),
    };
  } catch {
    return attachment;
  }
}

function mergePromptAttachmentFiles(existing = [], incoming = []) {
  const nextAttachments = [...existing];
  let errorMessage = "";
  for (const file of incoming) {
    if (!file) continue;
    if (file.size > MAX_PROMPT_ATTACHMENT_BYTES) {
      errorMessage = `${file.name || "File"} is larger than 5 MB.`;
      continue;
    }
    if (nextAttachments.length >= MAX_PROMPT_ATTACHMENTS) {
      errorMessage = `You can attach up to ${MAX_PROMPT_ATTACHMENTS} files per message.`;
      break;
    }
    nextAttachments.push(createPromptAttachment(file));
  }
  return { nextAttachments, errorMessage };
}

function revokePromptAttachmentUrls(attachments = []) {
  for (const item of attachments) {
    if (item?.previewUrl) {
      URL.revokeObjectURL(item.previewUrl);
    }
  }
}

function buildMessageAttachmentViews(attachments = [], serialized = []) {
  return attachments.map((item, index) => {
    const serializedItem = serialized[index] || {};
    const mimeType = inferAttachmentMimeType(
      item.name || serializedItem.name,
      item.mimeType || serializedItem.mime_type || "",
    );
    const kind = item.kind || serializedItem.kind || (isImageAttachmentMime(mimeType) ? "image" : "file");
    const contentBase64 = item.contentBase64 || serializedItem.content_base64 || "";
    const previewUrl =
      kind === "image" && contentBase64 ? `data:${mimeType};base64,${contentBase64}` : "";
    return {
      id: item.id || `${index}-${item.name || serializedItem.name || "attachment"}`,
      name: item.name || serializedItem.name || "attachment",
      mime_type: mimeType,
      kind,
      size: item.size || 0,
      preview_url: previewUrl,
      content_base64: contentBase64,
    };
  });
}

function resolveAttachmentPreviewUrl(attachment = {}) {
  const mimeType = inferAttachmentMimeType(attachment.name, attachment.mime_type || attachment.mimeType || "");
  const contentBase64 = attachment.content_base64 || attachment.contentBase64 || "";
  if (contentBase64) {
    return `data:${mimeType};base64,${contentBase64}`;
  }
  const previewUrl = String(attachment.preview_url || attachment.previewUrl || "");
  if (previewUrl.startsWith("data:")) return previewUrl;
  return "";
}

async function prepareOutgoingAttachments(attachments = []) {
  const prepared = [];
  for (const item of attachments) {
    if (!item) continue;
    const mimeType = inferAttachmentMimeType(item.name, item.mimeType || item.mime_type || "");
    let kind = item.kind || (isImageAttachmentMime(mimeType) ? "image" : "file");
    let contentBase64 = item.contentBase64 || item.content_base64 || "";
    if (!contentBase64 && item.file) {
      try {
        contentBase64 = await readFileAsBase64(item.file);
      } catch (readError) {
        console.warn("Failed to read attachment:", item.name, readError);
      }
    }
    if (kind === "image" && !contentBase64) {
      kind = "file";
    }
    prepared.push({
      id: item.id || `${Date.now()}-${prepared.length}`,
      name: item.name || "attachment",
      mime_type: mimeType,
      kind,
      size: item.size || 0,
      preview_url: kind === "image" && contentBase64 ? `data:${mimeType};base64,${contentBase64}` : "",
      content_base64: contentBase64,
    });
  }
  return prepared;
}

function attachmentsForGenerationApi(prepared = []) {
  return prepared.map((item) => ({
    name: item.name,
    mime_type: item.mime_type,
    kind: item.kind,
    content_base64: item.content_base64,
  }));
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      const encoded = result.includes(",") ? result.split(",", 2)[1] : result;
      resolve(encoded);
    };
    reader.onerror = () => reject(new Error(`Could not read ${file.name || "attachment"}.`));
    reader.readAsDataURL(file);
  });
}

async function serializePromptAttachments(attachments = []) {
  const prepared = await prepareOutgoingAttachments(attachments);
  return attachmentsForGenerationApi(prepared);
}

function PromptAttachmentsPreview({ attachments = [], onRemove }) {
  if (!attachments.length) return null;
  return (
    <div className="mb-2 grid grid-cols-[repeat(auto-fill,minmax(7rem,1fr))] gap-2">
      {attachments.map((attachment) => (
        <div
          key={attachment.id}
          className="group relative overflow-hidden rounded-lg border border-line bg-slate-50"
          title={`${attachment.name} (${formatAttachmentSize(attachment.size)})`}
        >
          {attachment.kind === "image" && (attachment.previewUrl || attachment.contentBase64) ? (
            <img
              className="h-24 w-full object-contain bg-slate-900/5"
              src={
                attachment.contentBase64
                  ? `data:${attachment.mimeType};base64,${attachment.contentBase64}`
                  : attachment.previewUrl
              }
              alt={attachment.name}
            />
          ) : (
            <div className="flex h-24 flex-col items-center justify-center gap-2 px-2 text-center">
              <FileCode2 className="text-slate-500" size={22} />
              <span className="line-clamp-2 text-[11px] font-bold text-slate-600">{attachment.name}</span>
            </div>
          )}
          <div className="border-t border-line bg-white/95 px-2 py-1">
            <p className="truncate text-[11px] font-bold text-ink">{attachment.name}</p>
            <p className="text-[10px] font-semibold text-muted">{formatAttachmentSize(attachment.size)}</p>
          </div>
          <button
            className="absolute right-1 top-1 inline-flex size-6 items-center justify-center rounded-full bg-black/70 text-white opacity-0 transition group-hover:opacity-100"
            type="button"
            aria-label={`Remove ${attachment.name}`}
            onClick={() => onRemove?.(attachment.id)}
          >
            <X size={12} />
          </button>
        </div>
      ))}
    </div>
  );
}

function ChatMessageAttachments({ attachments = [] }) {
  if (!attachments.length) return null;
  return (
    <div className="mt-3 grid grid-cols-[repeat(auto-fill,minmax(6.5rem,1fr))] gap-2">
      {attachments.map((attachment) => {
        const previewUrl = resolveAttachmentPreviewUrl(attachment);
        const isImage = attachment.kind === "image" || Boolean(previewUrl);
        return (
        <div key={attachment.id || attachment.name} className="overflow-hidden rounded-lg border border-white/20 bg-white/10">
          {isImage && previewUrl ? (
            <a href={previewUrl} target="_blank" rel="noreferrer">
              <img
                className="max-h-48 w-full object-contain bg-black/20"
                src={previewUrl}
                alt={attachment.name}
                loading="lazy"
              />
            </a>
          ) : (
            <div className="flex h-20 flex-col items-center justify-center gap-1 px-2 text-center">
              <ImageIcon size={18} />
              <span className="line-clamp-2 text-[10px] font-bold">{attachment.name}</span>
            </div>
          )}
          <div className="border-t border-white/15 px-2 py-1">
            <p className="truncate text-[10px] font-bold">{attachment.name}</p>
          </div>
        </div>
        );
      })}
    </div>
  );
}

const WORKFLOW_PHASE_DEFINITIONS = [
  {
    id: "brief",
    label: "Brief",
    description: "Understand the user request, project context, constraints, and route.",
    patterns: ["request.", "routing.", "confirmation.", "generate_simple_code_file.input"],
  },
  {
    id: "plan",
    label: "Plan",
    description: "Choose update strategy, target files, agents, tasks, and validation scope.",
    patterns: ["plan.", "planner", "analyst", "dynamic_agent", "agent.decision", "update.summary"],
  },
  {
    id: "build",
    label: "Build",
    description: "Generate or patch files with scoped changes and live file updates.",
    patterns: [
      "run_code_agent",
      "run_scoped_update_agent",
      "generate_simple_code_file.output",
      "streaming.file_agent",
      "agent.worker",
      "file.written",
      "files.materialized",
      "patch.proposed",
      "patch.applied",
      "write_file",
    ],
  },
  {
    id: "verify",
    label: "Verify",
    description: "Run syntax, build, preview, and visual checks before saving.",
    patterns: ["validation.", "validate", "gate.", "visual_qa", "preview_qa", "preview.built"],
  },
  {
    id: "save",
    label: "Save",
    description: "Commit safe files, sync local folder, update preview, and store memory.",
    patterns: [
      "files.persisting",
      "files.persisted",
      "browser.write_back.completed",
      "agent.runtime.loop.completed",
      "generation.completed",
      "skill.project.saved",
    ],
  },
];

function buildWorkflowPhaseStates(liveProgress = [], isGenerating = false, isBuilding = false) {
  const events = (liveProgress || []).filter((item) => item?.step);
  const latestEvent = [...events].reverse().find((item) => isUserFacingProgressStep(item.step) || item.status === "failed") || events[events.length - 1] || null;
  const latestStep = latestEvent?.step || "";
  const latestPhaseId =
    WORKFLOW_PHASE_DEFINITIONS.find((phase) => phase.patterns.some((pattern) => latestStep.includes(pattern)))?.id ||
    (isBuilding ? "verify" : isGenerating ? "brief" : "");
  const latestPhaseIndex = WORKFLOW_PHASE_DEFINITIONS.findIndex((phase) => phase.id === latestPhaseId);

  const phaseStates = WORKFLOW_PHASE_DEFINITIONS.map((phase, index) => {
    const matchingEvents = events.filter((event) => phase.patterns.some((pattern) => String(event.step || "").includes(pattern)));
    const failedEvent = [...matchingEvents].reverse().find((event) => event.status === "failed" || String(event.step || "").includes("failed"));
    const latestMatchingEvent = matchingEvents[matchingEvents.length - 1] || null;
    const completedEvent = [...matchingEvents]
      .reverse()
      .find(
        (event) =>
          event.status === "completed" ||
          String(event.step || "").endsWith(".completed") ||
          ["files.persisted", "preview.built"].includes(String(event.step || "")),
      );
    const runningEvent = [...matchingEvents].reverse().find((event) => event.status === "running");
    let status = completedEvent ? "completed" : runningEvent ? "running" : "waiting";
    if (failedEvent) {
      status = "failed";
    } else if (phase.id === latestPhaseId && (isGenerating || isBuilding || runningEvent)) {
      status = "running";
    } else if (latestPhaseId !== "save" && phase.id !== "verify" && latestPhaseIndex >= 0 && index < latestPhaseIndex) {
      status = "completed";
    }
    return {
      ...phase,
      status,
      message: compactProgressText(latestMatchingEvent?.message || "") || phase.description,
    };
  });

  return phaseStates.map((phase, index) => {
    if (!index) return phase;
    const previousPhasesCompleted = phaseStates.slice(0, index).every((item) => item.status === "completed");
    if (previousPhasesCompleted || phase.status === "failed") return phase;
    return {
      ...phase,
      status: "waiting",
      message: phase.description,
    };
  });
}

function PhaseStatusIcon({ status }) {
  if (status === "failed") return <AlertTriangle size={14} className="text-rose-300" />;
  if (status === "completed") return <CheckCircle2 size={14} className="text-white" />;
  if (status === "running") return <Loader2 size={14} className="animate-spin text-white" />;
  return <span className="size-2 rounded-full bg-slate-600" />;
}

function workflowStatusText(status) {
  if (status === "failed") return "needs attention";
  if (status === "completed") return "completed";
  if (status === "running") return "running";
  return "waiting";
}

function WorkflowPhaseConversationCard({ liveProgress = [], isGenerating = false, isBuilding = false }) {
  const phases = buildWorkflowPhaseStates(liveProgress, isGenerating, isBuilding);
  const activePhase =
    phases.find((phase) => phase.status === "running") ||
    phases.find((phase) => phase.status === "failed") ||
    [...phases].reverse().find((phase) => phase.status === "completed");
  const statusLabel = activePhase ? workflowStatusText(activePhase.status) : "preparing";
  const statusMessage = activePhase?.message || "Preparing the request and project context.";
  return (
    <article className="flex min-w-0 justify-start">
      <div className="min-w-0 max-w-[86%] px-1 py-1 text-sm leading-relaxed text-slate-400">
        <div className="flex min-w-0 items-center gap-2">
          {isGenerating || isBuilding ? <ThinkingWave /> : null}
          <span className="font-semibold text-slate-200">
            {activePhase ? `${activePhase.label} ${statusLabel}` : "Preparing workflow"}
          </span>
        </div>
        <p className="wt-wrap-anywhere mt-1 text-xs text-slate-500">{statusMessage}</p>
      </div>
    </article>
  );
}

function ThinkingProgressLine({ label = "" }) {
  if (!label) return null;
  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[86%] px-1">
        <div className="mb-1 border-b border-line pb-2 text-sm font-bold text-slate-300">
          {label}
        </div>
      </div>
    </div>
  );
}

function ConversationPanel({
  activeProject,
  conversationState,
  chatSessionId = "",
  episodicMemories = [],
  isBuilding,
  isGenerating,
  isCancellingGeneration = false,
  isImportingDirectory,
  liveProgress,
  streamingAssistantText = "",
  messages,
  previewUrl,
  previewVersionId = "",
  prompt,
  promptAttachments = [],
  selectedModel,
  setSelectedModel,
  setPrompt,
  setPromptAttachments,
  onGenerate,
  onStopGeneration,
  onStartNewChatSession,
  onSubmitPrompt,
  onOpenFileLine,
  skillsRefreshToken = 0,
  onEpisodesUpdated,
}) {
  const fileInputRef = useRef(null);
  const promptInputRef = useRef(null);
  const promptShellRef = useRef(null);
  const addMenuButtonRef = useRef(null);
  const speechRecognitionRef = useRef(null);
  const chatScrollRef = useRef(null);
  const chatBottomRef = useRef(null);
  const skillsLoadedRef = useRef(false);
  const [isListening, setIsListening] = useState(false);
  const [isAddMenuOpen, setIsAddMenuOpen] = useState(false);
  const [isAttachmentDragOver, setIsAttachmentDragOver] = useState(false);
  const [availableSkills, setAvailableSkills] = useState([]);
  const [isLoadingSkills, setIsLoadingSkills] = useState(false);
  const [isSlashMenuDismissed, setIsSlashMenuDismissed] = useState(false);
  const showRunProgress = Boolean(activeProject && liveProgress.length);
  const trimmedPrompt = prompt.trim();
  const hasPromptContent = Boolean(trimmedPrompt || promptAttachments.length);
  const isSlashSkillPrompt = trimmedPrompt === "/" || /^\/[a-z0-9-]*$/i.test(trimmedPrompt);
  const shouldShowSlashSkills = isSlashSkillPrompt && !isSlashMenuDismissed;
  const skillSuggestions = skillPickerItems(availableSkills, trimmedPrompt);

  useEffect(() => {
    const input = promptInputRef.current;
    if (!input) return;
    input.style.height = `${CHAT_INPUT_MIN_HEIGHT}px`;
    const nextHeight = Math.min(input.scrollHeight, CHAT_INPUT_MAX_HEIGHT);
    input.style.height = `${Math.max(CHAT_INPUT_MIN_HEIGHT, nextHeight)}px`;
    input.style.overflowY = "hidden";
  }, [prompt]);

  useEffect(() => {
    if (!activeProject) return;
    chatBottomRef.current?.scrollIntoView({
      block: "end",
      behavior: isGenerating ? "smooth" : "auto",
    });
  }, [activeProject, messages.length, liveProgress.length, isGenerating, isBuilding, isImportingDirectory]);

  useEffect(() => {
    skillsLoadedRef.current = false;
    setAvailableSkills([]);
  }, [activeProject?.id, skillsRefreshToken]);

  useEffect(() => {
    if (shouldShowSlashSkills && !skillsLoadedRef.current && !isLoadingSkills) {
      loadSkillsForPicker();
    }
  }, [shouldShowSlashSkills, isLoadingSkills, activeProject?.id, skillsRefreshToken]);

  async function loadSkillsForPicker() {
    setIsLoadingSkills(true);
    try {
      await bootstrapUserSkills(activeProject?.local_path || "");
      const params = new URLSearchParams();
      if (activeProject?.local_path) params.set("workspace_root", activeProject.local_path);
      const systemName = getClientSystemName();
      if (systemName) params.set("system_name", systemName);
      const query = params.toString() ? `?${params.toString()}` : "";
      const payload = activeProject?.id
        ? await api(`/api/projects/${encodeURIComponent(activeProject.id)}/skills${query}`)
        : await api(`/api/skills${query}`);
      if (payload.system_name) {
        setClientSystemName(payload.system_name);
      }
      setAvailableSkills(payload.skills || []);
      skillsLoadedRef.current = true;
    } catch (skillError) {
      console.warn("Failed to load skills:", skillError);
      skillsLoadedRef.current = true;
    } finally {
      setIsLoadingSkills(false);
    }
  }

  async function refreshSkillsForPicker() {
    skillsLoadedRef.current = false;
    await loadSkillsForPicker();
  }

  function choosePromptFiles() {
    setIsAddMenuOpen(false);
    fileInputRef.current?.click();
  }

  async function toggleAddMenu() {
    const nextOpen = !isAddMenuOpen;
    setIsAddMenuOpen(nextOpen);
    if (nextOpen && !skillsLoadedRef.current) {
      await loadSkillsForPicker();
    }
  }

  function insertSkillInvocation(skillName) {
    const invocation = `/${skillName}`;
    setPrompt((current) => {
      const trimmed = current.trim();
      if (!trimmed || trimmed === "/" || /^\/[a-z0-9-]*$/i.test(trimmed)) return `${invocation} `;
      if (trimmed.includes(invocation)) return current;
      return current.replace(/^\/[a-z0-9-]*/i, invocation).trimEnd() + " ";
    });
    setIsAddMenuOpen(false);
    setIsSlashMenuDismissed(true);
    requestAnimationFrame(() => promptInputRef.current?.focus());
  }

  function insertCreateSkillPrompt() {
    setPrompt((current) => {
      const trimmed = current.trim();
      const suffix = trimmed && trimmed !== "/" ? ` ${trimmed.replace(/^\/[a-z0-9-]*\s*/i, "")}` : "";
      return `/create-skill${suffix} `;
    });
    setIsAddMenuOpen(false);
    setIsSlashMenuDismissed(true);
    requestAnimationFrame(() => promptInputRef.current?.focus());
  }

  function addPromptAttachmentFiles(fileList) {
    const incoming = Array.from(fileList || []);
    if (!incoming.length) return;
    const { nextAttachments, errorMessage } = mergePromptAttachmentFiles(promptAttachments, incoming);
    if (errorMessage) {
      window.alert(errorMessage);
    }
    if (nextAttachments !== promptAttachments) {
      setPromptAttachments(nextAttachments);
      const created = nextAttachments.slice(-incoming.length);
      void Promise.all(created.map((attachment) => enrichAttachmentWithData(attachment))).then((enriched) => {
        setPromptAttachments((current) =>
          current.map((item) => {
            const updated = enriched.find((entry) => entry.id === item.id);
            return updated || item;
          }),
        );
      });
    }
  }

  function removePromptAttachment(attachmentId) {
    setPromptAttachments((current) => {
      const target = current.find((item) => item.id === attachmentId);
      if (target?.previewUrl) {
        URL.revokeObjectURL(target.previewUrl);
      }
      return current.filter((item) => item.id !== attachmentId);
    });
  }

  function handlePromptFilesChange(event) {
    addPromptAttachmentFiles(event.target.files);
    event.target.value = "";
  }

  function handlePromptPaste(event) {
    const items = Array.from(event.clipboardData?.items || []);
    const pastedFiles = items
      .filter((item) => item.kind === "file")
      .map((item) => item.getAsFile())
      .filter(Boolean);
    if (!pastedFiles.length) return;
    event.preventDefault();
    addPromptAttachmentFiles(pastedFiles);
  }

  function handleAttachmentDragOver(event) {
    event.preventDefault();
    setIsAttachmentDragOver(true);
  }

  function handleAttachmentDragLeave(event) {
    if (event.currentTarget.contains(event.relatedTarget)) return;
    setIsAttachmentDragOver(false);
  }

  function handleAttachmentDrop(event) {
    event.preventDefault();
    setIsAttachmentDragOver(false);
    addPromptAttachmentFiles(event.dataTransfer?.files);
  }

  function handlePromptKeyDown(event) {
    if (event.key === "Escape" && (isAddMenuOpen || shouldShowSlashSkills)) {
      setIsAddMenuOpen(false);
      return;
    }
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent?.isComposing) {
      return;
    }
    event.preventDefault();
    if (isGenerating) {
      onStopGeneration?.();
      return;
    }
    if (!prompt.trim() && !promptAttachments.length) {
      return;
    }
    const form = event.currentTarget.form;
    if (form?.requestSubmit) {
      form.requestSubmit();
    } else {
      onGenerate(event);
    }
  }

  function toggleVoiceInput() {
    if (isListening) {
      speechRecognitionRef.current?.stop();
      setIsListening(false);
      return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = "en-US";
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map((result) => result[0]?.transcript || "")
        .join(" ")
        .trim();
      if (transcript) {
        setPrompt((current) => [current.trim(), transcript].filter(Boolean).join(" "));
      }
    };
    recognition.onend = () => setIsListening(false);
    speechRecognitionRef.current = recognition;
    setIsListening(true);
    recognition.start();
  }

  function handlePromptAction() {
    if (isGenerating) {
      onStopGeneration?.();
      return;
    }
    if (!hasPromptContent) {
      toggleVoiceInput();
      return;
    }
    if (isListening) {
      speechRecognitionRef.current?.stop();
      setIsListening(false);
    }
    promptInputRef.current?.form?.requestSubmit();
  }

  return (
    <section className="wt-chat-panel relative isolate z-10 flex min-h-0 min-w-0 flex-col bg-chat">
      <div ref={chatScrollRef} className="wt-chat-scroll relative z-0 min-h-0 flex-1 px-5 py-4">
        <div className="mx-auto grid w-full min-w-0 max-w-4xl gap-4 overflow-x-hidden">
          {!activeProject ? (
            <div className="wt-soft-card rounded-xl border-dashed px-4 py-3 text-sm font-medium text-muted">
              No project selected yet. Send a message to start a backend workspace, or use Create project to link a local folder.
            </div>
          ) : null}
          {activeProject && conversationState?.resume_hint ? (
            <div className="rounded-xl border border-worktual-200 bg-worktual-50 px-4 py-3 text-sm font-semibold leading-relaxed text-worktual-900">
              {conversationState.resume_hint}
              {conversationState.has_pending_confirmation
                ? " You still have a pending execution brief — confirm or cancel below."
                : conversationState.message_count > 0
                  ? " Your chat history and project files are restored from the server."
                  : ""}
            </div>
          ) : null}
          {activeProject ? (
            <SessionMemoryPanel
              projectId={activeProject.id}
              chatSessionId={chatSessionId}
              prompt={prompt}
              compact
              onEpisodesChange={onEpisodesUpdated}
            />
          ) : null}
          {messages.map((message, index) => (
            <ChatBubble
              key={message.id || `${message.role}-${index}-${message.content?.slice(0, 24)}`}
              message={message}
              disabled={isGenerating}
              onAction={onSubmitPrompt}
            />
          ))}
          {showRunProgress ? (
            <AgentProgressStream
              liveProgress={liveProgress}
              isGenerating={isGenerating}
              isBuilding={isBuilding}
              streamingAssistantText={streamingAssistantText}
              onOpenFileLine={onOpenFileLine}
            />
          ) : null}
          {isBuilding ? <StatusBubble label="Building preview" /> : null}
          {isImportingDirectory ? <StatusBubble label="Loading local directory" /> : null}
          <div ref={chatBottomRef} aria-hidden="true" />
        </div>
      </div>
      <form className="relative z-30 shrink-0 overflow-visible border-t border-line bg-chat px-4 py-3" onSubmit={onGenerate}>
        <div
          ref={promptShellRef}
          className={`wt-prompt-shell wt-soft-card relative mx-auto grid min-h-[50px] w-full min-w-0 max-w-4xl grid-cols-[40px_minmax(0,1fr)_auto] items-end gap-2 overflow-visible rounded-xl px-2 py-1 ${
            isAttachmentDragOver ? "border-worktual-500 ring-2 ring-worktual-200" : "border-line"
          }`}
          onDragOver={handleAttachmentDragOver}
          onDragEnter={handleAttachmentDragOver}
          onDragLeave={handleAttachmentDragLeave}
          onDrop={handleAttachmentDrop}
        >
          <input
            ref={fileInputRef}
            className="hidden"
            type="file"
            multiple
            accept={PROMPT_ATTACHMENT_ACCEPT}
            onChange={handlePromptFilesChange}
          />
          {promptAttachments.length ? (
            <div className="col-span-3 pt-2">
              <PromptAttachmentsPreview attachments={promptAttachments} onRemove={removePromptAttachment} />
            </div>
          ) : null}
          <label className="sr-only" htmlFor="builder-prompt">Website prompt</label>
          <textarea
            ref={promptInputRef}
            id="builder-prompt"
            className="wt-prompt-input col-start-2 row-start-2 block resize-none self-end border-0 bg-transparent py-1 text-sm leading-relaxed text-ink outline-none"
            placeholder="Ask for website changes, paste a screenshot, or describe a bug..."
            rows={1}
            value={prompt}
            onChange={(event) => {
              setPrompt(event.target.value);
              setIsSlashMenuDismissed(false);
            }}
            onPaste={handlePromptPaste}
            onKeyDown={handlePromptKeyDown}
          />
          {shouldShowSlashSkills ? (
            <SkillPickerMenu
              open={shouldShowSlashSkills}
              anchorRef={promptShellRef}
              isLoading={isLoadingSkills}
              skills={skillSuggestions}
              title="Choose a skill"
              onClose={() => setIsSlashMenuDismissed(true)}
              onCreateSkill={insertCreateSkillPrompt}
              onRefresh={refreshSkillsForPicker}
              onSelectSkill={insertSkillInvocation}
            />
          ) : null}
          <div className="contents">
            <div className="contents">
              <button
                ref={addMenuButtonRef}
                className="col-start-1 row-start-2 mb-0.5 inline-flex size-9 items-center justify-center self-end rounded-lg text-slate-600 transition hover:bg-slate-100 hover:text-ink"
                type="button"
                title="Add context or skills"
                aria-label="Add context or skills"
                onClick={toggleAddMenu}
              >
                <Plus size={17} />
              </button>
              <FloatingPanel
                open={isAddMenuOpen}
                anchorRef={addMenuButtonRef}
                onClose={() => setIsAddMenuOpen(false)}
              >
                <div className="grid gap-1 p-2">
                  <button
                    className="flex items-start gap-3 rounded-lg px-3 py-2 text-left transition hover:bg-slate-100"
                    type="button"
                    onClick={choosePromptFiles}
                  >
                    <Paperclip className="mt-0.5 shrink-0 text-slate-500" size={16} />
                    <span>
                        <span className="block text-sm font-black text-ink">Attach files</span>
                        <span className="block text-xs font-semibold text-muted">Images, logs, or code files. Paste screenshots or drag and drop here too.</span>
                    </span>
                  </button>
                  <button
                    className="flex items-start gap-3 rounded-lg px-3 py-2 text-left transition hover:bg-slate-100"
                    type="button"
                    onClick={insertCreateSkillPrompt}
                  >
                    <Sparkles className="mt-0.5 shrink-0 text-worktual-700" size={16} />
                    <span>
                      <span className="block text-sm font-black text-ink">Create skill</span>
                    </span>
                  </button>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto border-t border-line p-2">
                  <SkillPickerList
                    isLoading={isLoadingSkills}
                    skills={sortSkillsForPicker(availableSkills)}
                    onRefresh={refreshSkillsForPicker}
                    onSelectSkill={insertSkillInvocation}
                  />
                </div>
              </FloatingPanel>
            </div>
            <div className="col-start-3 row-start-2 mb-0.5 flex items-center gap-1.5 self-end">
              <select
                className="wt-model-select h-8 max-w-[5.5rem] rounded-none border-0 bg-transparent px-1 text-[10.5px] font-bold text-slate-300 outline-none transition hover:text-white focus:text-white"
                aria-label="Model"
                title="Choose model"
                value={selectedModel}
                onChange={(event) => setSelectedModel(event.target.value)}
              >
                {MODEL_OPTIONS.map((model) => (
                  <option key={model.value} value={model.value}>
                    {model.label}
                  </option>
                ))}
              </select>
              <button
                className={`inline-flex size-9 items-center justify-center rounded-full transition disabled:cursor-not-allowed disabled:opacity-50 ${
                  isGenerating
                    ? "bg-red-600 text-white hover:bg-red-700"
                    : hasPromptContent
                      ? "bg-midnight text-white hover:bg-teal"
                      : isListening
                        ? "bg-white text-black"
                        : "bg-black text-slate-300 hover:bg-white hover:text-black"
                }`}
                type="button"
                disabled={isCancellingGeneration}
                title={
                  isCancellingGeneration
                    ? "Stopping generation"
                    : isGenerating
                      ? "Stop generation"
                      : hasPromptContent
                        ? "Send prompt"
                        : isListening
                          ? "Stop voice input"
                          : "Voice input"
                }
                aria-label={
                  isCancellingGeneration
                    ? "Stopping generation"
                    : isGenerating
                      ? "Stop generation"
                      : hasPromptContent
                        ? "Send prompt"
                        : isListening
                          ? "Stop voice input"
                          : "Voice input"
                }
                onClick={handlePromptAction}
              >
                {isCancellingGeneration ? (
                  <Loader2 size={17} className="animate-spin" />
                ) : isGenerating ? (
                  <Square size={16} fill="currentColor" />
                ) : hasPromptContent ? (
                  <Send size={17} />
                ) : (
                  <Mic size={17} />
                )}
              </button>
            </div>
          </div>
        </div>
      </form>
    </section>
  );
}

function FloatingPanel({ open, anchorRef, onClose, children, matchAnchorWidth = false }) {
  const menuRef = useRef(null);
  const [position, setPosition] = useState(null);

  useEffect(() => {
    if (!open) {
      setPosition(null);
      return undefined;
    }
    function updatePosition() {
      const el = anchorRef?.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      setPosition({
        left: Math.max(8, rect.left),
        bottom: window.innerHeight - rect.top + 8,
        maxHeight: Math.max(180, rect.top - 12),
        width: matchAnchorWidth
          ? Math.min(rect.width, window.innerWidth - Math.max(8, rect.left) - 8)
          : Math.min(320, window.innerWidth - 16),
      });
    }
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [open, anchorRef, matchAnchorWidth]);

  useEffect(() => {
    if (!open) return undefined;
    function handlePointerDown(event) {
      if (anchorRef?.current?.contains(event.target)) return;
      if (menuRef.current?.contains(event.target)) return;
      onClose?.();
    }
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [open, onClose, anchorRef]);

  if (!open || !position) return null;

  return createPortal(
    <div
      ref={menuRef}
      className="fixed z-[200] flex min-h-0 flex-col overflow-hidden rounded-xl border border-line bg-white shadow-2xl"
      style={{
        left: position.left,
        bottom: position.bottom,
        maxHeight: position.maxHeight,
        width: position.width,
      }}
    >
      {children}
    </div>,
    document.body,
  );
}

function SkillPickerMenu({ isLoading, skills, title, onCreateSkill, onRefresh, onSelectSkill, anchorRef, open, onClose }) {
  const pickerTitle = skills.length ? `${title} (${skills.length})` : title;
  return (
    <FloatingPanel open={open} anchorRef={anchorRef} onClose={onClose} matchAnchorWidth>
      <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-2">
        <p className="text-xs font-black uppercase tracking-normal text-worktual-700">{pickerTitle}</p>
        <button className="text-xs font-black text-worktual-700 hover:text-worktual-900" type="button" onClick={onCreateSkill}>
          /create-skill
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <SkillPickerList isLoading={isLoading} skills={skills} onRefresh={onRefresh} onSelectSkill={onSelectSkill} />
      </div>
    </FloatingPanel>
  );
}

function SkillPickerList({ isLoading, skills, onRefresh, onSelectSkill }) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-3 py-3 text-sm font-bold text-muted">
        <Loader2 className="animate-spin" size={15} />
        Loading skills...
      </div>
    );
  }

  if (!skills.length) {
    return (
      <div className="grid gap-2 px-3 py-3">
        <p className="text-sm font-bold text-muted">No skills found yet.</p>
        <button className="justify-self-start text-xs font-black text-worktual-700 hover:text-worktual-900" type="button" onClick={onRefresh}>
          Refresh skills
        </button>
      </div>
    );
  }

  return (
    <div className={`${SKILL_PICKER_MAX_HEIGHT_CLASS} overflow-y-auto p-1`}>
      {skills.map((skill) => (
        <button
          key={`${skill.scope}-${skill.name}-${skill.path}`}
          className="block w-full rounded-lg px-3 py-2 text-left transition hover:bg-worktual-50"
          type="button"
          onClick={() => onSelectSkill(skill.name)}
        >
          <span className="block text-sm font-black text-ink">/{skill.name}</span>
        </button>
      ))}
    </div>
  );
}

function EmptyWorkspaceState() {
  return (
    <div className="flex h-full min-h-[420px] items-center justify-center px-5">
      <div className="mx-auto flex max-w-md flex-col items-center text-center">
          <p className="text-xs font-black uppercase tracking-normal text-worktual-700">Worktual workspace</p>
          <h2 className="mt-2 text-2xl font-black tracking-normal text-ink">Start a website session</h2>
          <p className="mt-3 max-w-sm text-sm font-bold leading-relaxed text-muted">
            Use the project-history button to choose local file access or a backend workspace.
          </p>
        </div>
    </div>
  );
}

function AgentProgressStream({ liveProgress = [], isGenerating = false, isBuilding = false, streamingAssistantText = "", onOpenFileLine }) {
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    if (!isGenerating) {
      setNowMs(Date.now());
      return undefined;
    }
    const interval = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [isGenerating]);

  const items = buildChatProgressItems(liveProgress, isGenerating);
  if (!items.length && !liveProgress.length) return null;
  const timing = buildProgressRunTiming(liveProgress, isGenerating, nowMs);
  const activeItemId = isGenerating ? latestActiveProgressItemId(items) : "";

  return (
    <div className="wt-run-timeline ml-2 grid gap-3 pl-3">
      {streamingAssistantText ? (
        <article className="flex min-w-0 justify-start">
          <div className="wt-soft-card min-w-0 w-full max-w-[86%] rounded-xl px-4 py-3 text-xs leading-relaxed text-slate-700">
            <div className="mb-2 flex items-center gap-2 text-xs font-black uppercase tracking-wide text-slate-400">
              <span>Assistant</span>
            </div>
            <p className="wt-wrap-anywhere whitespace-pre-wrap">{streamingAssistantText}</p>
          </div>
        </article>
      ) : null}
      <ThinkingProgressLine label={timing.label} />
      {items.map((item) => (
        <ProgressNarrativeItem key={item.id} item={item} isActive={item.id === activeItemId} onOpenFileLine={onOpenFileLine} />
      ))}
    </div>
  );
}

function ProgressNarrativeItem({ item, isActive = false, onOpenFileLine }) {
  const fileRefs = item.fileRefs?.length ? item.fileRefs : item.files.map((path) => ({ path, action: "file" }));
  return (
    <article className="wt-run-timeline-item flex min-w-0 justify-start">
      <div className={`min-w-0 w-full max-w-[86%] rounded-xl border px-3 py-2.5 text-sm leading-relaxed ${
        isActive ? "border-worktual-300/50 bg-worktual-50/80 text-slate-200" : "border-line bg-white/60 text-slate-700"
      }`}>
        <div className="flex items-start gap-2">
          <p className="wt-wrap-anywhere min-w-0 flex-1 whitespace-pre-wrap">{item.text}</p>
        </div>
        {item.summary ? (
          <div className="mt-2 inline-flex items-center gap-2 text-xs font-semibold text-slate-400">
            {item.summaryKind === "diff" ? <FileCode2 size={14} /> : <Search size={14} />}
            <span>{item.summary}</span>
          </div>
        ) : null}
        {fileRefs.length ? (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {fileRefs.slice(0, 8).map((ref) => (
              <button
                key={`${ref.path}-${ref.action}-${ref.startLine || 0}-${ref.endLine || 0}-${ref.added || 0}`}
                type="button"
                className="inline-flex max-w-full items-center gap-1 rounded-md bg-slate-100 px-2 py-1 text-[11px] font-bold text-slate-600 transition hover:bg-worktual-50 hover:text-worktual-700"
                title={progressFileRefTitle(ref)}
                onClick={() => onOpenFileLine?.(ref.path, ref.startLine || 1)}
              >
                <FileCode2 size={12} />
                <span className="max-w-56 truncate">{formatProgressFileRefLabel(ref)}</span>
              </button>
            ))}
            {item.hiddenFileCount > 0 ? (
              <span className="rounded-md bg-slate-100 px-2 py-1 text-[11px] font-bold text-slate-500">
                +{item.hiddenFileCount} more
              </span>
            ) : null}
          </div>
        ) : null}
        {item.planDetail ? <PlanPreview detail={item.planDetail} /> : null}
        {item.diffDetail ? <DiffPreview detail={item.diffDetail} /> : null}
        {item.gateFailureDetail ? <GateFailureCard detail={item.gateFailureDetail} onOpenFileLine={onOpenFileLine} /> : null}
      </div>
    </article>
  );
}

function ThinkingWave({ className = "" }) {
  return (
    <span className={`thinking-wave shrink-0 ${className}`} aria-label="Thinking" role="status">
      <span />
      <span />
      <span />
    </span>
  );
}

function buildProgressRunTiming(liveProgress, isGenerating, nowMs = Date.now()) {
  const timestamps = liveProgress
    .map((item) => parseTimestampMs(item?.created_at))
    .filter((value) => Number.isFinite(value));
  if (!timestamps.length) return { label: "" };
  const startedAt = Math.min(...timestamps);
  const latestAt = Math.max(...timestamps);
  const failed = liveProgress.some((item) => isFatalProgressFailure(item));
  const finished = !isGenerating && liveProgress.length > 0;
  const endedAt = isGenerating ? nowMs : latestAt;
  const durationLabel = formatElapsedDuration(Math.max(0, endedAt - startedAt));
  if (isGenerating) return { label: `Thinking for ${durationLabel}` };
  if (failed) return { label: `Stopped after ${durationLabel}` };
  if (finished) return { label: `Worked for ${durationLabel}` };
  return { label: "" };
}

function latestActiveProgressItemId(items) {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (items[index]?.status !== "failed") return items[index].id;
  }
  return "";
}

function buildChatProgressItems(liveProgress, isGenerating) {
  const runContext = buildProgressRunContext(liveProgress);
  const groupsByPhase = new Map();
  const orderedGroups = [];

  liveProgress.forEach((progressItem, index) => {
    if (shouldHideChatProgress(progressItem)) return;
    const phase = progressNarrativePhase(progressItem);
    if (!phase) return;

    let group = groupsByPhase.get(phase.key);
    if (!group) {
      group = createProgressNarrativeGroup(phase, index, runContext);
      groupsByPhase.set(phase.key, group);
      orderedGroups.push(group);
    }
    mergeProgressIntoNarrativeGroup(group, progressItem, index);
  });

  return orderedGroups
    .map((group) => finalizeProgressNarrativeGroup(group, isGenerating))
    .filter(Boolean)
    .slice(-CHAT_PROGRESS_ITEM_LIMIT);
}

function buildProgressRunContext(liveProgress) {
  const routeEvent = liveProgress.find((item) => item?.step === "routing.completed");
  const routeDetail = routeEvent?.detail || {};
  const intent = routeDetail.intent || routeDetail.next_action || "";
  return {
    intent,
    isUpdate: String(intent).includes("update"),
    isGeneration: String(intent).includes("generation") || String(intent).includes("generate"),
    isConversation: String(intent).includes("greeting") || String(intent).includes("conversation"),
  };
}

function isFatalProgressFailure(item) {
  const step = item?.step || "";
  if (step === "generation.failed") return true;
  if (item?.status !== "failed") return false;
  if (item?.detail?.recoverable) return false;
  if (step === "gate.failed") return false;
  if (step === "gate.build.failed") return false;
  if (step.startsWith("agent.specialist.")) return false;
  if (step === "files.persist.failed") return false;
  return true;
}

function progressNarrativePhase(item) {
  const step = item?.step || "";
  if (!step) return null;

  if (isFatalProgressFailure(item)) {
    return { key: "failure", label: "Failure" };
  }
  if (step === "gate.failed" || step === "gate.build.failed" || step === "gate.visual_qa.failed") {
    return { key: "gate-failure", label: "Validation Failed" };
  }
  if (step.startsWith("gate.build.") || step.startsWith("gate.repair.") || step.startsWith("gate.deterministic.") || step.startsWith("gate.visual_qa.")) {
    return { key: "verification", label: "Build Verification" };
  }
  if (["skills.matched", "skills.recommendation"].includes(step)) {
    return { key: "skill-selection", label: "Skill Selection" };
  }
  if (["skill.create.queued", "skill.model.authoring", "skill.model.authored"].includes(step)) {
    return { key: "skill-authoring", label: "Skill Authoring" };
  }
  if (["skill.home.saved", "skill.project.saving", "skill.project.saved"].includes(step)) {
    return { key: "skill-saving", label: "Skill Saving" };
  }
  if (["skill.local.write_back", "skill.local.write_back.completed", "skill.local.write_back.skipped", "skill.create.completed"].includes(step)) {
    return { key: "skill-complete", label: "Skill Ready" };
  }
  if (
    [
      "request.queued",
      "request.received",
      "project.loaded",
      "routing.started",
      "routing.completed",
      "agent.decision",
      "generate_simple_code_file.input",
      "generate_simple_code_file.output",
      "confirmation.brief.started",
      "confirmation.brief.completed",
      "confirmation.decision.started",
      "confirmation.decision.completed",
      "agent.runtime.loop.started",
    ].includes(step)
  ) {
    return { key: "intake", label: "Request Setup" };
  }
  if (
    step.startsWith("agent.loop.read_project_files") ||
    step.startsWith("agent.loop.load_project_memory") ||
    step.startsWith("agent.loop.run_update_analyst") ||
    step.startsWith("agent.loop.run_prompt_analyst")
  ) {
    return { key: "context", label: "Code Context" };
  }
  if (
    step === "plan.created" ||
    step === "update.summary" ||
    step.startsWith("agent.loop.run_dynamic_agent_planner") ||
    step.startsWith("agent.loop.run_dynamic_specialists") ||
    step.startsWith("agent.loop.run_planner")
  ) {
    return { key: "planning", label: "Plan" };
  }
  if (
    [
      "tool.read_file",
      "tool.write_file",
      "tool.str_replace",
      "tool.list_files",
      "tool.requested",
      "patch.proposed",
      "streaming.file_agent.started",
      "streaming.file_agent.completed",
      "agent.parallel.started",
      "agent.parallel.completed",
      "agent.parallel.plan",
      "agent.parallel.wave.started",
      "agent.parallel.wave.completed",
      "orchestrator.wave.checkpoint",
      "context.greenfield",
      "context.analysis",
      "gate.syntax.wave",
      "files.wave.persisted",
      "agent.worker.started",
      "agent.worker.completed",
      "agent.worker.failed",
    ].includes(step)
  ) {
    return { key: "tools", label: "File Operations" };
  }
  if (step === "plan.created" || step.startsWith("agent.specialist.") || step === "agent.parallel.plan" || step === "orchestrator.wave.checkpoint" || step === "context.greenfield" || step === "context.analysis") {
    return { key: "planning", label: "Agent Plan" };
  }
  if (
    step === "file.diff.ready" ||
    step === "file.written" ||
    step === "files.materializing" ||
    step === "files.materialized" ||
    step === "error.diagnosed" ||
    step.startsWith("agent.loop.run_code_agent") ||
    step.startsWith("agent.loop.run_scoped_update_agent") ||
    step.startsWith("agent.loop.run_repair_agent")
  ) {
    return { key: "editing", label: "Code Changes" };
  }
  if (
    step === "preview.built" ||
    step.startsWith("agent.loop.validate") ||
    step.startsWith("agent.loop.build") ||
    step.startsWith("agent.loop.run_preview_visual_qa") ||
    step.startsWith("agent.loop.run_visual_qa")
  ) {
    return { key: "verification", label: "Verification" };
  }
  if (
    step === "files.persisting" ||
    step === "files.persisted" ||
    step === "browser.write_back" ||
    step === "browser.write_back.completed" ||
    step === "browser.write_back.skipped" ||
    step === "generation.recovered" ||
    step.startsWith("agent.loop.write_project_files")
  ) {
    return { key: "commit", label: "Saved Changes" };
  }
  if (step === "agent.runtime.loop.completed") {
    return { key: "work", label: "Agent Work" };
  }
  if (step.startsWith("agent.loop.")) {
    return { key: "work", label: "Agent Work" };
  }
  return null;
}

function createProgressNarrativeGroup(phase, index, runContext) {
  return {
    id: `progress-summary-${phase.key}`,
    phase: phase.key,
    label: phase.label,
    order: index,
    runContext,
    status: "running",
    steps: new Set(),
    events: [],
    fileSet: new Set(),
    planDetail: null,
    diffDetail: null,
    gateFailureDetail: null,
    routeDetail: null,
    analysisDetail: null,
    decisionDetail: null,
    first_at: null,
    latest_at: null,
    latestMessage: "",
    failedMessage: "",
  };
}

function mergeProgressIntoNarrativeGroup(group, item, index) {
  const step = item?.step || "";
  group.steps.add(step);
  group.events.push({ ...item, index });
  group.status = isFatalProgressFailure(item) ? "failed" : item?.status || group.status;
  group.first_at = group.first_at || item?.created_at;
  group.latest_at = item?.created_at || group.latest_at;
  group.latestMessage = item?.message || group.latestMessage;
  if (group.status === "failed") group.failedMessage = item?.message || group.failedMessage;

  progressFilePaths(item).forEach((path) => group.fileSet.add(path));

  const fileRef = progressFileRefFromEvent(item);
  if (fileRef) {
    if (!group.fileRefList) group.fileRefList = [];
    group.fileRefList.push(fileRef);
  }
  if (step === "file.diff.ready") {
    collectDiffFileRefs(item.detail).forEach((ref) => {
      if (!group.fileRefList) group.fileRefList = [];
      group.fileRefList.push(ref);
    });
  }

  if (step === "routing.completed") group.routeDetail = item.detail || {};
  if (step === "agent.decision" || step.startsWith("generate_simple_code_file.")) {
    group.decisionDetail = item.detail || group.decisionDetail;
  }
  if (step === "update.summary") {
    group.analysisDetail = item.detail || group.analysisDetail;
  }
  if (step === "plan.created") group.planDetail = item.detail || null;
  if (step === "patch.proposed" || step === "file.diff.ready") {
    group.diffDetail = visibleDiffDetail(item.detail || null);
  }
  if (step === "gate.build.failed" || step === "gate.visual_qa.failed" || step === "gate.failed") {
    group.gateFailureDetail = buildGateFailureDetail(step, item.detail || {}, item.message || "");
    group.status = "failed";
    group.failedMessage = item.message || group.failedMessage;
  }
  if (step.startsWith("agent.loop.run_update_analyst") || step.startsWith("agent.loop.run_prompt_analyst")) {
    group.analysisDetail = item.detail || group.analysisDetail;
  }
}

function finalizeProgressNarrativeGroup(group, isGenerating) {
  const files = [...group.fileSet];
  const fileRefs = collectProgressFileRefs(group.fileRefList || [], files);
  const text = progressGroupNarrative(group, files, isGenerating);
  if (!text) return null;
  const summary = progressGroupSummary(group, files);
  return {
    id: group.id,
    step: group.phase,
    status: group.status,
    text,
    summary: summary?.label || "",
    summaryKind: summary?.kind || "search",
    files: files.slice(0, 10),
    fileRefs,
    hiddenFileCount: Math.max(Math.max(fileRefs.length, files.length) - 8, 0),
    planDetail: group.planDetail,
    diffDetail: group.diffDetail,
    gateFailureDetail: group.gateFailureDetail,
    created_at: group.latest_at || group.first_at,
  };
}

function compactProgressText(value = "", maxLength = 220) {
  const compacted = String(value || "").replace(/\s+/g, " ").trim();
  if (!compacted) return "";
  return compacted.length > maxLength ? `${compacted.slice(0, maxLength - 3)}...` : compacted;
}

function progressDecisionNarrative(detail = {}) {
  if (!detail || typeof detail !== "object") return "";
  const agent = detail.selected_agent || "";
  const action = detail.selected_action ? formatStepName(detail.selected_action) : "";
  const route = detail.intent ? formatStepName(detail.intent) : "";
  const workflow = detail.workflow ? formatStepName(detail.workflow) : "";
  const reason = compactProgressText(detail.decision_reason || detail.reason || "");
  const target = detail.path ? ` for ${detail.path}` : "";
  const selected = action || workflow || route || "this workflow";

  if (agent && reason) return `${agent} selected ${selected}${target}. Reason: ${reason}`;
  if (agent) return `${agent} selected ${selected}${target}.`;
  if (route && reason) return `Chief Orchestrator selected the ${route} route. Reason: ${reason}`;
  if (route) return `Chief Orchestrator selected the ${route} route.`;
  if (reason) return `Decision reason: ${reason}`;
  return "";
}

function progressGroupNarrative(group, files, isGenerating) {
  const context = group.runContext || {};
  if (group.phase === "failure") {
    return group.failedMessage || group.latestMessage || "The run failed before changes could be completed.";
  }
  if (group.phase === "skill-selection") {
    const latest = [...group.events].reverse()[0] || {};
    if (group.steps.has("skills.recommendation")) {
      const recommended = latest.detail?.recommended || [];
      const createSuggestion = latest.detail?.create_skill_suggestion || "";
      if (recommended.length) {
        return `The selected skill does not match this task. I’m recommending ${recommended
          .slice(0, 2)
          .map((skill) => `/${skill.name}`)
          .join(", ")} before continuing.`;
      }
      return `The selected skill does not match this task. No existing skill fits, so I’m recommending a new skill: ${createSuggestion || "/create-skill ..."}.`;
    }
    const skills = latest.detail?.skills || [];
    if (skills.length) return `Using ${skills.map((skill) => `/${skill.name}`).join(", ")} for this task.`;
    return latest.message || "Checking whether the selected skill matches the task.";
  }
  if (group.phase === "skill-authoring") {
    if (group.steps.has("skill.model.authored")) {
      const latest = [...group.events].reverse().find((event) => event.step === "skill.model.authored");
      const skillName = latest?.detail?.skill;
      const authoredByModel = latest?.detail?.model_authored;
      return `${authoredByModel ? "The selected model" : "The skill generator"} prepared${skillName ? ` /${skillName}` : " the skill"} with workflow instructions, analysis guidance, and web-search requirements.`;
    }
    if (group.steps.has("skill.model.authoring")) {
      const latest = [...group.events].reverse().find((event) => event.step === "skill.model.authoring");
      const model = latest?.detail?.model;
      return `The model${model ? ` (${model})` : ""} is writing the skill now: deciding the workflow, what information to gather, when to use web search, and how the final answer should be structured.`;
    }
    return "I’m preparing the skill creation request and choosing the model-backed skill authoring flow.";
  }
  if (group.phase === "skill-saving") {
    if (group.steps.has("skill.project.saved")) {
      const latest = [...group.events].reverse().find((event) => event.step === "skill.project.saved");
      return `The skill was saved in the user skills home and also added to this project at ${latest?.detail?.path || ".worktual/skills"}.`;
    }
    if (group.steps.has("skill.project.saving")) {
      const latest = [...group.events].reverse().find((event) => event.step === "skill.project.saving");
      return `The skill is saved in the user home. Next I’m adding it to the active project at ${latest?.detail?.path || ".worktual/skills/<name>/SKILL.md"}.`;
    }
    return "The model-authored skill is being saved to the user skills home first.";
  }
  if (group.phase === "skill-complete") {
    if (group.steps.has("skill.create.completed")) {
      const latest = [...group.events].reverse().find((event) => event.step === "skill.create.completed");
      const skillName = latest?.detail?.skill;
      return `The skill is ready${skillName ? ` as /${skillName}` : ""}. Next step: choose it from the skill picker or type ${skillName ? `/${skillName}` : "the slash command"} in chat.`;
    }
    if (group.steps.has("skill.local.write_back.completed")) {
      const latest = [...group.events].reverse().find((event) => event.step === "skill.local.write_back.completed");
      return `The project skill file was also written to the selected local/browser folder at ${latest?.detail?.path || ".worktual/skills"}.`;
    }
    if (group.steps.has("skill.local.write_back.skipped")) {
      return group.latestMessage || "The skill was saved in the backend project, but local folder write-back was skipped.";
    }
    return "I’m syncing the new project skill file to the selected local/browser folder when write access is available.";
  }
  if (group.phase === "tools") {
    const latest = [...group.events].reverse()[0] || {};
    if (group.steps.has("streaming.file_agent.completed")) {
      return group.latestMessage || "Finished applying file changes.";
    }
    if (latest.step === "tool.read_file") {
      const range = formatLineRangeSuffix(latest.detail || {});
      return latest.detail?.path
        ? `Read ${latest.detail.path}${range || ""}.`
        : latest.message || "Reading project file.";
    }
    if (latest.step === "tool.write_file") {
      const range = formatLineRangeSuffix(latest.detail || {});
      return latest.detail?.path
        ? `Wrote ${latest.detail.path}${range || ""}.`
        : latest.message || "Writing project file.";
    }
    if (latest.step === "tool.str_replace" || latest.step === "patch.proposed") {
      const detail = latest.detail || {};
      const range = formatLineRangeSuffix(detail);
      const delta = formatLineDeltaSuffix(detail);
      if (detail.path) return `Staged edit on ${detail.path}${range}${delta ? ` ${delta}` : ""} (not saved yet).`;
      return latest.message || "Applying edit to project file.";
    }
    if (latest.step === "tool.list_files") return latest.message || "Listing project files.";
    return latest.message || "Running file tools against the project.";
  }
  if (group.phase === "intake") {
    const decisionText = progressDecisionNarrative(group.decisionDetail || group.routeDetail);
    if (decisionText) return decisionText;
    if (context.isConversation) {
      return "I’m handling this as a conversation response, so no website files need to be generated or edited.";
    }
    if (context.isUpdate) {
      return "I’m routing this as a website update, loading the selected project, and preparing the guarded edit workflow before any files are changed.";
    }
    if (context.isGeneration) {
      return "I’m routing this as a website generation request and preparing the workspace context before planning the site.";
    }
    return "I’m preparing the request, project context, and route before starting the agent workflow.";
  }
  if (group.phase === "context") {
    const reason = compactProgressText(group.analysisDetail?.decision_reason || group.analysisDetail?.reason || "");
    if (reason && files.length) {
      return `I identified the relevant project context. Reason: ${reason} Focused files: ${files.slice(0, 3).join(", ")}${files.length > 3 ? `, and ${files.length - 3} more` : ""}.`;
    }
    if (context.isUpdate) {
      return "I’m reading the current project files and previous memory so the update can stay scoped to the existing website instead of regenerating unrelated code.";
    }
    return "I’m reading project files, memory, and the website brief so the implementation plan matches the current workspace.";
  }
  if (group.phase === "planning") {
    if (group.analysisDetail?.summary) {
      const fileText = files.length ? ` Focused files: ${files.slice(0, 3).join(", ")}${files.length > 3 ? `, and ${files.length - 3} more` : ""}.` : "";
      return `${group.analysisDetail.summary}${fileText}`;
    }
    const detail = group.planDetail || {};
    const planText = detail.update_strategy || detail.layout_strategy;
    if (planText) return planText;
    const taskCount = detail.workflow?.task_count || detail.workflow?.tasks?.length || detail.tasks?.length;
    if (taskCount) {
      return `I prepared a workflow plan with ${taskCount} ${taskCount === 1 ? "task" : "tasks"} and selected the agents needed for this run.`;
    }
    return "I’m turning the requirement into an execution plan and deciding which agents should participate.";
  }
  if (group.phase === "editing") {
    const changedCount = group.diffDetail?.file_count || files.length;
    const fileText = files.length ? ` Focused files: ${files.slice(0, 3).join(", ")}${files.length > 3 ? `, and ${files.length - 3} more` : ""}.` : "";
    if (group.steps.has("files.materialized") || group.steps.has("file.written")) {
      const latest = [...group.events].reverse().find((event) => event.step === "file.written" || event.step === "files.materialized");
      const writtenCount = latest?.detail?.written_count || changedCount || files.length;
      const totalCount = latest?.detail?.total_count || writtenCount;
      return `I’m writing generated files into the workspace as they are planned (${writtenCount}/${totalCount}).${fileText}`;
    }
    if (group.steps.has("file.diff.ready")) {
      return `I prepared reviewable code changes for ${changedCount || "the selected"} ${changedCount === 1 ? "file" : "files"}.${fileText}`;
    }
    if ([...group.steps].some((step) => step.includes("run_scoped_update_agent"))) {
      return `The scoped update agent is applying the requested change only to the approved project files, preserving the rest of the website.${fileText}`;
    }
    if ([...group.steps].some((step) => step.includes("run_repair_agent"))) {
      return "A repair pass is fixing a validation or preview issue before the backend tries the build again.";
    }
    return "The code agent is preparing the React/Vite file changes for this request.";
  }
  if (group.phase === "gate-failure") {
    return group.gateFailureDetail?.headline || group.failedMessage || group.latestMessage || "Validation did not pass before commit.";
  }
  if (group.phase === "verification") {
    const done = group.steps.has("preview.built");
    const filesReady = group.steps.has("files.materialized") || group.steps.has("file.written");
    if (done) {
      return "The staged preview build completed successfully after the planned files were written to the workspace.";
    }
    if (filesReady) {
      return "All planned files are in the workspace. I’m validating them and building the staged preview before final completion.";
    }
    return "I’m validating the changed source files and building a staged preview.";
  }
  if (group.phase === "commit") {
    const persisted = group.steps.has("files.persisted") || group.steps.has("agent.runtime.loop.completed") || group.steps.has("generation.recovered");
    if (group.steps.has("generation.recovered")) {
      return group.latestMessage || "Code changes were saved and the workspace was refreshed after the live stream disconnected.";
    }
    if (group.steps.has("browser.write_back.completed")) {
      const latest = [...group.events].reverse().find((event) => event.step === "browser.write_back.completed");
      const count = latest?.detail?.count;
      const workspace = latest?.detail?.workspace;
      return `The validated files were saved to the project and written to${workspace ? ` ${workspace}` : " the selected browser folder"}${count ? ` (${count} files)` : ""}.`;
    }
    if (group.steps.has("browser.write_back.skipped")) {
      return group.latestMessage || "The validated files were saved to the project, but browser folder write-back is not available for this workspace.";
    }
    return persisted
      ? "The validated changes were saved to the project and the run memory was updated."
      : "The backend is saving the validated files into the project after the guarded checks passed.";
  }
  if (group.phase === "work") {
    return group.latestMessage && !looksLikeInternalProgressMessage(group.latestMessage)
      ? group.latestMessage
      : "The agent workflow is continuing with the next approved backend action.";
  }
  if (isGenerating) return group.latestMessage || "The agent workflow is still running.";
  return "";
}

function progressGroupSummary(group, files) {
  if (group.phase === "skill-selection") {
    if (group.steps.has("skills.recommendation")) return { kind: "search", label: "Recommended a better skill" };
    return { kind: "search", label: "Applied selected skill" };
  }
  if (group.phase === "skill-authoring") {
    if (group.steps.has("skill.model.authored")) return { kind: "search", label: "Model authored the skill" };
    return { kind: "search", label: "Model is authoring the skill" };
  }
  if (group.phase === "skill-saving") {
    if (group.steps.has("skill.project.saved")) return { kind: "diff", label: "Saved user and project skill files" };
    return { kind: "diff", label: "Saving skill files" };
  }
  if (group.phase === "skill-complete") {
    if (group.steps.has("skill.local.write_back.completed")) return { kind: "diff", label: "Synced to local folder" };
    if (group.steps.has("skill.local.write_back.skipped")) return { kind: "diff", label: "Backend saved; local sync skipped" };
    if (group.steps.has("skill.create.completed")) return { kind: "search", label: "Skill ready to invoke" };
    return { kind: "diff", label: "Syncing skill file" };
  }
  if (group.phase === "context") {
    return { kind: "search", label: files.length ? `Explored ${files.length} files and loaded project memory` : "Loaded project context" };
  }
  if (group.phase === "planning") {
    const workflow = group.planDetail?.workflow || (group.planDetail?.kind === "workflow_plan" ? group.planDetail : null);
    const taskCount = workflow?.task_count || workflow?.tasks?.length || group.planDetail?.tasks?.length;
    return taskCount ? { kind: "search", label: `Planned ${taskCount} ${taskCount === 1 ? "task" : "tasks"}` } : { kind: "search", label: "Prepared execution plan" };
  }
  if (group.phase === "editing") {
    if (group.diffDetail) {
      return {
        kind: "diff",
        label: `Edited ${group.diffDetail.file_count || files.length || 0} files, +${group.diffDetail.added || 0} / -${group.diffDetail.removed || 0}`,
      };
    }
    return { kind: "diff", label: files.length ? `Editing ${files.length} approved files` : "Preparing code changes" };
  }
  if (group.phase === "gate-failure") {
    const kind = group.gateFailureDetail?.kind;
    if (kind === "build") return { kind: "search", label: "Build gate failed" };
    if (kind === "visual_qa") return { kind: "search", label: "Visual QA failed" };
    return { kind: "search", label: "Validation gate failed" };
  }
  if (group.phase === "verification") return { kind: "search", label: "Validated, built, and checked preview" };
  if (group.phase === "commit") {
    if (group.steps.has("browser.write_back.completed")) return { kind: "diff", label: "Saved project and local folder files" };
    if (group.steps.has("browser.write_back.skipped")) return { kind: "diff", label: "Saved project; local write-back skipped" };
    return { kind: "diff", label: "Saved verified project files" };
  }
  if (group.phase === "failure") return { kind: "search", label: "Run failed before commit" };
  if (group.phase === "intake") {
    const agent = group.decisionDetail?.selected_agent || "";
    const route = group.decisionDetail?.workflow || group.routeDetail?.intent || group.routeDetail?.next_action || "";
    if (agent && route) return { kind: "search", label: `Selected ${agent}: ${formatStepName(route)}` };
    if (agent) return { kind: "search", label: `Selected ${agent}` };
    return { kind: "search", label: "Routed request and prepared workspace" };
  }
  return files.length ? { kind: "search", label: `Explored ${files.length} files` } : null;
}

function shouldHideChatProgress(item) {
  const step = item?.step || "";
  if (!step || CHAT_PROGRESS_HIDDEN_STEPS.has(step)) return true;
  if (CHAT_PROGRESS_HIDDEN_PREFIXES.some((prefix) => step.startsWith(prefix))) return true;
  if (item?.status === "failed" || step === "generation.failed") return false;
  if (step.startsWith("agent.loop.persist_project_memory")) return true;
  if (step.startsWith("agent.loop.")) return false;
  if (CHAT_PROGRESS_VISIBLE_STEPS.has(step)) return false;
  if (step.includes(".input") || step.includes(".output") || step.includes(".raw_output")) return true;
  if (looksLikeInternalProgressMessage(item?.message || "")) return true;
  return true;
}

function looksLikeInternalProgressMessage(message) {
  const text = String(message || "").toLowerCase();
  if (!text) return false;
  return [
    "orchestration node",
    "google adk",
    "adk usage",
    "tool contract",
    "tool calling setup",
    "runtime projection",
    "normalizing final generation response",
    "agent runtime data persisted",
    "persisting agent messages",
  ].some((marker) => text.includes(marker));
}

function isUserFacingProgressStep(step) {
  if (!step) return false;
  if (CHAT_PROGRESS_VISIBLE_STEPS.has(step)) return true;
  if (step.startsWith("agent.loop.persist_project_memory")) return true;
  if (step.startsWith("agent.loop.")) return true;
  return false;
}

function toChatProgressItem(item, index, isGenerating) {
  const text = progressNarrativeText(item, isGenerating);
  if (!text) return null;
  const files = progressFilePaths(item);
  const fileRefs = collectProgressFileRefs([progressFileRefFromEvent(item)].filter(Boolean), files);
  const summary = progressActionSummary(item, files);
  return {
    id: item.id || `${item.step || "progress"}-${index}`,
    step: item.step || "",
    status: item.status || "running",
    text,
    summary: summary?.label || "",
    summaryKind: summary?.kind || "search",
    files: files.slice(0, 10),
    fileRefs,
    hiddenFileCount: Math.max(Math.max(fileRefs.length, files.length) - 8, 0),
    planDetail: item.step === "plan.created" ? item.detail : null,
    diffDetail: item.step === "file.diff.ready" ? item.detail : null,
    created_at: item.created_at,
  };
}

function progressNarrativeText(item, isGenerating) {
  const step = item.step || "";
  const message = item.message || "Backend progress update";
  const detail = item.detail || {};

  if (step === "streaming.file_agent.started") {
    return "Starting the fast streaming file agent with live tool calls.";
  }
  if (step === "streaming.file_agent.completed") {
    return message || "Streaming file agent finished.";
  }
  if (step === "tool.read_file") {
    const range = formatLineRangeSuffix(detail);
    return range ? `Read ${detail.path || "project file"}${range}.` : message || `Reading ${detail.path || "project file"}.`;
  }
  if (step === "tool.list_files") {
    return message || `Listing ${detail.path || "."}.`;
  }
  if (step === "tool.write_file") {
    const range = formatLineRangeSuffix(detail);
    return range ? `Wrote ${detail.path || "project file"}${range}.` : message || `Writing ${detail.path || "project file"}.`;
  }
  if (step === "tool.str_replace" || step === "patch.proposed") {
    const delta = formatLineDeltaSuffix(detail);
    const range = formatLineRangeSuffix(detail);
    if (detail.path && (range || delta)) {
      return `Edited ${detail.path}${range}${delta ? ` ${delta}` : ""}.`;
    }
    return message || `Applying edit to ${detail.path || "project file"}.`;
  }
  if (step === "request.queued") {
    return "I’m sending your request to the backend and starting the agent runtime.";
  }
  if (step === "request.received") {
    return "The backend received your request and is preparing the project context.";
  }
  if (step === "project.loaded") {
    return "I loaded the selected workspace and current project files.";
  }
  if (step === "routing.started") {
    return "I’m asking the Chief Orchestrator to choose the correct route for this request.";
  }
  if (step === "routing.completed") {
    const route = detail.intent || detail.next_action || "";
    const reason = compactProgressText(detail.decision_reason || detail.reason || "");
    return route
      ? `Chief Orchestrator selected the ${formatStepName(route)} route.${reason ? ` Reason: ${reason}` : " The backend is continuing with that path."}`
      : "Chief Orchestrator selected the execution route and the backend is continuing with that path.";
  }
  if (step === "agent.decision") {
    return progressDecisionNarrative(detail) || message;
  }
  if (step === "generate_simple_code_file.input") {
    return "I’m asking the Simple Code Writer Agent to generate the standalone code file now.";
  }
  if (step === "generate_simple_code_file.output") {
    return "The Simple Code Writer Agent returned standalone code files for validation and saving.";
  }
  if (step === "confirmation.brief.started") {
    return "I’m preparing a short execution brief so you can confirm the intended change before files are edited.";
  }
  if (step === "confirmation.brief.completed") {
    return "I prepared the execution brief and am waiting for your confirmation.";
  }
  if (step === "confirmation.decision.started") {
    return "I’m checking whether your reply confirms, changes, or cancels the execution brief.";
  }
  if (step === "confirmation.decision.completed") {
    return detail.decision
      ? `Your confirmation was classified as ${formatStepName(detail.decision)}.`
      : "Your confirmation response was classified and the backend is continuing.";
  }
  if (step === "agent.runtime.loop.started") {
    return "I’m starting the guarded agent workflow for this project.";
  }
  if (step === "agent.runtime.loop.completed") {
    return "The guarded agent workflow finished successfully.";
  }
  if (step === "plan.created") {
    if (detail.update_strategy) return detail.update_strategy;
    if (detail.layout_strategy) return detail.layout_strategy;
    if (detail.kind === "workflow_plan" || detail.workflow) {
      return "I prepared the dynamic-agent workflow plan and selected the specialists needed for this run.";
    }
    return "I prepared the execution plan for this request.";
  }
  if (step === "update.summary") {
    const agent = detail.selected_agent || (detail.execution_strategy === "deterministic_patch" ? "Targeted Update Agent" : "Scoped Update Agent");
    const strategy = detail.execution_strategy ? formatStepName(detail.execution_strategy) : "update workflow";
    const reason = compactProgressText(detail.decision_reason || "");
    const files = progressFilePaths(item);
    const fileText = files.length ? ` Focused files: ${files.slice(0, 3).join(", ")}${files.length > 3 ? `, and ${files.length - 3} more` : ""}.` : "";
    return `${agent} selected ${strategy}.${reason ? ` Reason: ${reason}` : ""}${fileText}`;
  }
  if (step === "file.diff.ready") {
    return "I prepared the code changes so you can review exactly what will be written.";
  }
  if (step === "error.diagnosed") {
    const files = progressFilePaths(item);
    return files.length
      ? `I diagnosed the runtime issue and identified likely source files: ${files.slice(0, 3).join(", ")}${files.length > 3 ? `, and ${files.length - 3} more` : ""}.`
      : message;
  }
  if (step === "files.persisting") {
    return `I’m saving ${detail.file_count || "the"} validated files into the project.`;
  }
  if (step === "files.persisted") {
    return `Saved ${detail.file_count || "the"} files to the project.`;
  }
  if (step === "browser.write_back") {
    return `I’m writing ${detail.file_count || "the"} validated files to the selected browser folder.`;
  }
  if (step === "browser.write_back.completed") {
    return detail.workspace
      ? `Wrote ${detail.count || "the"} files to ${detail.workspace}.`
      : "Wrote the generated files to the selected browser folder.";
  }
  if (step === "browser.write_back.skipped") {
    return message;
  }
  if (step === "local.sync") {
    return "I’m checking the linked local folder before updating the project store.";
  }
  if (step === "local.sync.completed") {
    return detail.path
      ? `Local files were written to ${detail.path}.`
      : "Local files were written to the linked folder.";
  }
  if (step === "local.sync.skipped") {
    return "No linked local folder is available for disk sync.";
  }
  if (step === "preview.built") {
    return "The preview build completed successfully.";
  }
  if (step === "gate.build.started") {
    return "Running a staged Vite build on your project to verify the generated code compiles.";
  }
  if (step === "gate.build.passed") {
    return detail.preview_url
      ? "Build verification passed — preview is ready."
      : "Build verification passed.";
  }
  if (step === "gate.build.failed") {
    return message || "Build verification failed after repair attempts.";
  }
  if (step === "gate.visual_qa.failed") {
    return message || "Visual QA did not pass on the staged preview.";
  }
  if (step === "gate.failed") {
    return message || "A validation gate did not pass.";
  }
  if (step === "gate.repair.started") {
    return detail.paths?.length
      ? `The repair agent is fixing ${detail.paths.join(", ")} from the build error.`
      : "The repair agent is fixing the build error before retrying the preview build.";
  }
  if (step === "gate.repair.no_changes") {
    return "Repair pass made no changes — build errors may remain.";
  }
  if (step === "gate.repair.completed") {
    return "Repair pass finished — retrying the build.";
  }
  if (step === "gate.deterministic.repair" || step === "gate.deterministic.normalized") {
    return message;
  }
  if (step === "generation.incomplete") {
    const missing = Array.isArray(detail?.missing_paths) ? detail.missing_paths : [];
    if (missing.length) {
      return `Generation incomplete — still need: ${missing.slice(0, 3).join(", ")}${missing.length > 3 ? "…" : ""}`;
    }
    return message || "Generation incomplete — continuing with remaining blueprint files.";
  }
  if (step === "generation.failed" || item.status === "failed") {
    return message;
  }
  if (step.startsWith("agent.loop.")) {
    return runtimeActionNarrative(step, message);
  }
  if (isGenerating && item.status === "running" && isUserFacingProgressStep(step)) {
    return message;
  }
  return "";
}

function runtimeActionNarrative(step, message) {
  const action = step.replace(/^agent\.loop\./, "").replaceAll("_", " ");
  if (step.includes("read_project_files")) return "I’m reading the current project files before deciding what to change.";
  if (step.includes("load_project_memory")) return "I’m loading previous project memory so the update stays consistent.";
  if (step.includes("run_update_analyst")) return "I’m analyzing whether this should be a scoped edit or a larger website change.";
  if (step.includes("run_prompt_analyst")) return "I’m extracting the website brief, domain, audience, features, and missing details.";
  if (step.includes("run_dynamic_agent_planner")) return "I’m selecting the specialist agents and building the workflow for this request.";
  if (step.includes("run_dynamic_specialists")) return "Specialist agents are producing focused planning notes and candidate recommendations.";
  if (step.includes("run_planner")) return "I’m turning the brief into a concrete website implementation plan.";
  if (step.includes("run_code_agent")) return "The code generator is preparing the React/Vite files.";
  if (step.includes("run_scoped_update_agent")) return "The scoped update agent is editing only the approved files for this request.";
  if (step.includes("validate")) return "I’m validating generated source files, paths, imports, and artifact structure.";
  if (step.includes("build")) return "I’m building the staged Vite preview before committing files.";
  if (step.includes("visual_qa") || step.includes("preview_qa")) return "I’m checking the preview for runtime and visual issues.";
  if (step.includes("repair")) return "The repair agent is fixing the validation or preview issue before retrying.";
  if (step.includes("write_project_files")) return "The validated files are being committed to the project.";
  return message || `Running ${action}.`;
}

function progressActionSummary(item, files) {
  const step = item.step || "";
  const detail = item.detail || {};
  if (step === "agent.decision") {
    const agent = detail.selected_agent || "Chief Orchestrator";
    const workflow = detail.workflow || detail.intent || detail.selected_action || "";
    return { kind: "search", label: workflow ? `Selected ${agent}: ${formatStepName(workflow)}` : `Selected ${agent}` };
  }
  if (step === "generate_simple_code_file.input" || step === "generate_simple_code_file.output") {
    return { kind: "diff", label: "Generating standalone code" };
  }
  if (step === "update.summary") {
    const strategy = detail.execution_strategy ? formatStepName(detail.execution_strategy) : "update scope";
    return { kind: "search", label: `Selected ${strategy}` };
  }
  if (step === "error.diagnosed") {
    return { kind: "search", label: files.length ? `Diagnosed issue across ${files.length} files` : "Diagnosed runtime issue" };
  }
  if (step === "file.diff.ready") {
    return {
      kind: "diff",
      label: `Edited ${detail.file_count || files.length || 0} files, +${detail.added || 0} / -${detail.removed || 0}`,
    };
  }
  if (step === "plan.created") {
    const workflow = detail.workflow || (detail.kind === "workflow_plan" ? detail : null);
    const taskCount = workflow?.task_count || workflow?.tasks?.length || detail.sections?.length || detail.files_to_change?.length;
    return taskCount ? { kind: "search", label: `Planned ${taskCount} ${taskCount === 1 ? "task" : "tasks"}` } : null;
  }
  if (step.includes("read_project_files")) {
    return { kind: "search", label: `Explored ${files.length || detail.file_count || "project"} files` };
  }
  if (step.includes("load_project_memory")) return { kind: "search", label: "Loaded project memory" };
  if (step.includes("run_update_analyst")) return { kind: "search", label: "Analyzed update scope" };
  if (step === "scope.resolving") return { kind: "search", label: "Resolving update scope" };
  if (step === "scope.resolved") {
    const targets = Array.isArray(detail.target_files) ? detail.target_files : [];
    const references = Array.isArray(detail.reference_files) ? detail.reference_files : [];
    const candidates = Array.isArray(detail.candidate_files) ? detail.candidate_files : [];
    const enrichmentSnippets = Array.isArray(detail.scope_enrichment_snippets) ? detail.scope_enrichment_snippets : [];
    const enrichmentProfile = String(detail.enrichment_profile || "").trim();
    const interactionSummary = String(detail.interaction_summary || "").trim();
    const snippetCount = enrichmentSnippets.length;
    const enrichmentSuffix = snippetCount
      ? ` — pre-loaded ${snippetCount} ${enrichmentProfile === "interaction_wiring" ? "interaction" : "code"} snippet${snippetCount === 1 ? "" : "s"}`
      : "";
    const rationale = String(detail.scope_rationale || "").trim();
    if (targets.length || references.length) {
      const targetLabel = targets.length ? targets.slice(0, 2).join(", ") : candidates.slice(0, 2).join(", ");
      const refLabel = references.length ? references.slice(0, 2).join(", ") : "";
      const label = refLabel ? `Target: ${targetLabel} | Reference: ${refLabel}` : `Scope: ${targetLabel}`;
      const summaryPrefix =
        enrichmentProfile === "interaction_wiring" && interactionSummary
          ? `${interactionSummary.slice(0, 80)} — `
          : "";
      return {
        kind: "search",
        label: rationale
          ? `${summaryPrefix}${label}${enrichmentSuffix} — ${rationale.slice(0, 100)}`
          : `${summaryPrefix}${label}${enrichmentSuffix}`,
      };
    }
    const fileLabel = candidates.length ? candidates.slice(0, 3).join(", ") : "target files";
    const summaryPrefix =
      enrichmentProfile === "interaction_wiring" && interactionSummary
        ? `${interactionSummary.slice(0, 80)} — `
        : "";
    return {
      kind: "search",
      label: rationale
        ? `${summaryPrefix}Scope: ${fileLabel}${enrichmentSuffix} — ${rationale.slice(0, 120)}`
        : `${summaryPrefix}Scope: ${fileLabel}${enrichmentSuffix}`,
    };
  }
  if (step === "commit.rejected") {
    const gate = String(detail.gate || detail.reason || "commit");
    const path = detail.path || (Array.isArray(detail.rejected) ? detail.rejected[0]?.path : "");
    return {
      kind: "diff",
      label: path ? `Save blocked (${gate}): ${path}` : `Save blocked (${gate})`,
    };
  }
  if (step === "tool.search_codebase") {
    const count = Number(detail.count ?? detail.matches?.length ?? 0);
    return { kind: "search", label: count ? `Searched codebase (${count} matches)` : "Searched codebase" };
  }
  if (step.includes("run_prompt_analyst")) return { kind: "search", label: "Analyzed website brief" };
  if (step.includes("run_dynamic_agent_planner")) {
    const count = detail.active_agent_count || detail.agent_count || detail.created_agent_ids?.length || detail.reused_agent_ids?.length;
    return { kind: "search", label: count ? `Selected ${count} agents` : "Selected specialist agents" };
  }
  if (step.includes("run_code_agent") || step.includes("run_scoped_update_agent")) {
    return { kind: "diff", label: files.length ? `Analyzing ${files.length} files` : "Preparing code changes" };
  }
  if (step.includes("validate")) return { kind: "search", label: "Validated source files" };
  if (step.includes("build")) return { kind: "search", label: "Built staged preview" };
  if (step.includes("visual_qa") || step.includes("preview_qa")) return { kind: "search", label: "Checked preview QA" };
  if (step.includes("repair")) return { kind: "diff", label: "Repairing generated files" };
  if (step === "files.persisting") return { kind: "diff", label: `Saving ${detail.file_count || "project"} files` };
  if (step === "files.persisted") return { kind: "diff", label: `Saved ${detail.file_count || "project"} files` };
  if (step === "commit.rejected") {
    const gate = String(detail.gate || "commit");
    return { kind: "diff", label: `Save blocked (${gate})` };
  }
  if (files.length) return { kind: "search", label: `Explored ${files.length} files` };
  return null;
}

function progressFilePaths(item) {
  const detail = item.detail || {};
  const values = [
    detail.path,
    detail.file?.path,
    ...(Array.isArray(detail.candidate_files) ? detail.candidate_files : []),
    ...(Array.isArray(detail.files_to_change) ? detail.files_to_change : []),
    ...(Array.isArray(detail.changed_file_paths) ? detail.changed_file_paths : []),
    ...(Array.isArray(detail.paths) ? detail.paths : []),
    ...(Array.isArray(detail.diffs) ? detail.diffs.map((diff) => diff?.path) : []),
  ];
  return [...new Set(values.map(normalizeProgressPath).filter(Boolean))].filter((path) => !isHiddenProjectFilePath(path));
}

function progressActionFromStep(step = "") {
  if (step === "tool.read_file") return "read";
  if (step === "tool.write_file" || step === "file.written") return "write";
  if (step === "tool.str_replace" || step === "patch.proposed") return "edit";
  if (step === "tool.list_files") return "list";
  if (step === "tool.search_codebase") return "search";
  return "file";
}

function progressFileRefFromEvent(item) {
  const detail = item?.detail || {};
  const path = normalizeProgressPath(detail.path || detail.file?.path);
  if (!path || isHiddenProjectFilePath(path)) return null;
  const startLine = Number(detail.start_line ?? detail.startLine);
  const endLine = Number(detail.end_line ?? detail.endLine);
  const added = detail.added == null ? null : Number(detail.added);
  const removed = detail.removed == null ? null : Number(detail.removed);
  const hasLineData =
    Number.isFinite(startLine) ||
    Number.isFinite(endLine) ||
    Number.isFinite(added) ||
    Number.isFinite(removed) ||
    detail.pattern;
  if (!hasLineData && !["tool.read_file", "tool.write_file", "tool.str_replace", "file.written", "patch.proposed"].includes(item?.step || "")) {
    return null;
  }
  return {
    path,
    action: detail.action || progressActionFromStep(item?.step || ""),
    startLine: Number.isFinite(startLine) ? startLine : null,
    endLine: Number.isFinite(endLine) ? endLine : null,
    added: Number.isFinite(added) ? added : null,
    removed: Number.isFinite(removed) ? removed : null,
    pattern: detail.pattern || "",
  };
}

function collectDiffFileRefs(detail) {
  if (!detail || !Array.isArray(detail.diffs)) return [];
  return detail.diffs
    .map((diff) => {
      const path = normalizeProgressPath(diff?.path);
      if (!path || isHiddenProjectFilePath(path)) return null;
      const match = String(diff?.diff || "").match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/m);
      const startLine = match ? Number(match[1]) : null;
      const span = match && match[2] ? Number(match[2]) : 1;
      const endLine = startLine ? startLine + Math.max(0, span - 1) : null;
      return {
        path,
        action: "edit",
        startLine,
        endLine,
        added: diff?.added == null ? null : Number(diff.added),
        removed: diff?.removed == null ? null : Number(diff.removed),
        pattern: "",
      };
    })
    .filter(Boolean);
}

function collectProgressFileRefs(rawRefs = [], fallbackPaths = []) {
  const refs = [];
  const seen = new Set();
  rawRefs.forEach((ref) => {
    if (!ref?.path) return;
    const key = `${ref.path}|${ref.action}|${ref.startLine || 0}|${ref.endLine || 0}|${ref.added || 0}|${ref.removed || 0}`;
    if (seen.has(key)) return;
    seen.add(key);
    refs.push(ref);
  });
  fallbackPaths.forEach((path) => {
    if (!path || seen.has(`${path}|file|0|0|0|0`)) return;
    refs.push({ path, action: "file", startLine: null, endLine: null, added: null, removed: null, pattern: "" });
  });
  return refs.slice(0, 12);
}

function formatLineRangeSuffix(detail = {}) {
  const startLine = Number(detail.start_line ?? detail.startLine);
  const endLine = Number(detail.end_line ?? detail.endLine);
  if (Number.isFinite(startLine) && Number.isFinite(endLine) && endLine > startLine) return ` L${startLine}-${endLine}`;
  if (Number.isFinite(startLine)) return ` L${startLine}`;
  return "";
}

function formatLineDeltaSuffix(detail = {}) {
  const added = detail.added == null ? null : Number(detail.added);
  const removed = detail.removed == null ? null : Number(detail.removed);
  if (!Number.isFinite(added) && !Number.isFinite(removed)) return "";
  const parts = [];
  if (Number.isFinite(added) && added > 0) parts.push(`+${added}`);
  if (Number.isFinite(removed) && removed > 0) parts.push(`-${removed}`);
  return parts.length ? parts.join(" ") : "";
}

function formatProgressFileRefLabel(ref) {
  const base = ref.path?.split("/").pop() || ref.path || "file";
  const range = formatLineRangeSuffix(ref);
  const delta = formatLineDeltaSuffix(ref);
  if (ref.action === "read") return `Read ${base}${range}`;
  if (ref.action === "write") return `Wrote ${base}${range}`;
  if (ref.action === "edit") return delta ? `Edited ${base} ${delta}` : `Edited ${base}${range}`;
  if (ref.action === "list" && ref.pattern) return `Grepped ${ref.pattern} in ${base}`;
  return range || delta ? `${base}${range}${delta ? ` ${delta}` : ""}` : base;
}

function progressFileRefTitle(ref) {
  const range = formatLineRangeSuffix(ref);
  const delta = formatLineDeltaSuffix(ref);
  return [ref.path, range.replace(/^\s*/, ""), delta].filter(Boolean).join(" · ");
}

function visibleDiffDetail(detail) {
  if (!detail || typeof detail !== "object") return null;
  const diffs = Array.isArray(detail.diffs) ? detail.diffs.filter((diff) => !isHiddenProjectFilePath(diff?.path || "")) : [];
  const added = diffs.reduce((total, diff) => total + Number(diff?.added || 0), 0);
  const removed = diffs.reduce((total, diff) => total + Number(diff?.removed || 0), 0);
  return {
    ...detail,
    file_count: diffs.length,
    visible_file_count: diffs.length,
    truncated_files: 0,
    added,
    removed,
    diffs,
  };
}

function normalizeProgressPath(value) {
  if (typeof value === "string") return value;
  if (value && typeof value === "object" && typeof value.path === "string") return value.path;
  return "";
}

function chatProgressDedupeKey(item) {
  return [
    item.step,
    item.text,
    item.summary,
    item.files.slice(0, 6).join(","),
    item.diffDetail?.file_count || "",
    item.diffDetail?.added || "",
    item.diffDetail?.removed || "",
    item.gateFailureDetail?.kind || "",
    item.gateFailureDetail?.code || "",
  ].join("|");
}

function PlanPreview({ detail }) {
  const workflow = detail.workflow || (detail.kind === "workflow_plan" ? detail : null);
  const tasks = workflow?.tasks || [];
  const assignments = workflow?.assignments || [];
  const sections = detail.sections || [];
  const filesToChange = detail.files_to_change || [];

  return (
    <div className="mt-4 rounded-lg border border-worktual-100 bg-white p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-2 text-xs font-black uppercase tracking-normal text-worktual-700">
          <Sparkles size={14} />
          Plan
        </span>
        {workflow?.task_count ? <span className="text-xs font-bold text-muted">{workflow.task_count} tasks</span> : null}
      </div>
      {detail.layout_strategy || detail.update_strategy ? (
        <p className="text-xs font-semibold leading-relaxed text-slate-700">
          {detail.update_strategy || detail.layout_strategy}
        </p>
      ) : null}
      {sections.length ? (
        <div className="mt-3 flex flex-wrap gap-1">
          {sections.slice(0, 8).map((section) => (
            <span key={section} className="rounded-md bg-slate-100 px-2 py-1 text-[11px] font-bold text-slate-700">
              {section}
            </span>
          ))}
        </div>
      ) : null}
      {filesToChange.length ? (
        <div className="mt-3 grid gap-1">
          {filesToChange.slice(0, 5).map((path) => (
            <div key={path} className="flex items-center gap-2 text-[11px] font-bold text-slate-700">
              <FileCode2 size={12} />
              <span className="truncate">{path}</span>
            </div>
          ))}
        </div>
      ) : null}
      {tasks.length ? (
        <div className="mt-3 grid gap-1">
          {tasks.slice(0, 6).map((task, index) => (
            <div key={task.id || `${task.name}-${index}`} className="grid grid-cols-[18px_minmax(0,1fr)] gap-2 text-xs">
              <span className="mt-0.5 flex size-4 items-center justify-center rounded-full bg-worktual-100 text-[10px] font-black text-worktual-700">
                {index + 1}
              </span>
              <div className="min-w-0">
                <div className="truncate font-black text-ink">{task.name || task.id}</div>
                <div className="truncate text-[11px] font-bold text-muted">
                  {[task.capability, assignmentLabel(assignments, task.id)].filter(Boolean).join(" / ")}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function buildGateFailureDetail(step, detail = {}, message = "") {
  const suggestedFromBackend = Array.isArray(detail.suggested_actions)
    ? detail.suggested_actions.filter((item) => typeof item === "string" && item.trim())
    : [];
  if (step === "gate.build.failed") {
    const filesCommitted = detail.files_committed !== false;
    const errorPaths = Array.isArray(detail.error_paths) ? detail.error_paths.filter(Boolean) : [];
    return {
      kind: "build",
      title: filesCommitted ? "Files saved — preview build failed" : "Build verification failed",
      headline:
        detail.user_message ||
        message ||
        (filesCommitted
          ? "Your code was saved locally. The preview build did not pass."
          : "The staged Vite build did not pass."),
      reason: detail.repair_reason || detail.reason || "",
      errorPaths,
      buildLogExcerpt: detail.build_log_excerpt || "",
      repairAttempts: detail.repair_attempts,
      category: detail.category || "preview_build",
      code: detail.code || "build_gate_failed",
      filesCommitted,
      suggestedActions: suggestedFromBackend.length
        ? suggestedFromBackend
        : filesCommitted
          ? [
              "Your updated files are already saved — open them in the file tree.",
              "Retry Preview when your network or build environment is stable.",
              "Ask me to fix only the files listed in the build log.",
            ]
          : [
              "Review the flagged files for syntax, import, or Vite entry issues.",
              "Ask me to fix the build error in the listed files.",
              "Retry after confirming package.json and src/main entry points.",
            ],
    };
  }
  if (step === "gate.visual_qa.failed") {
    const warnings = Array.isArray(detail.warnings) ? detail.warnings.filter(Boolean) : [];
    return {
      kind: "visual_qa",
      title: "Visual QA failed",
      headline: detail.user_message || message || "The staged preview did not pass visual QA checks.",
      reason: detail.error || warnings.join("; ") || detail.status || "",
      warnings,
      previewUrl: detail.preview_url || "",
      category: detail.category || "visual_qa",
      code: detail.code || "visual_qa_failed",
      suggestedActions: suggestedFromBackend.length
        ? suggestedFromBackend
        : [
            "Open the preview and describe what looks wrong.",
            "Ask me to fix layout, styling, or missing sections.",
          ],
    };
  }
  if (step === "gate.failed") {
    return {
      kind: "gate",
      title: "Validation gate failed",
      headline: detail.user_message || message || "A validation gate did not pass.",
      reason: detail.reason || detail.message || "",
      category: detail.category || "validation",
      code: detail.code || "gate_failed",
      suggestedActions: suggestedFromBackend.length
        ? suggestedFromBackend
        : ["Review the issue below and ask for a targeted fix."],
    };
  }
  return null;
}

function GateFailureCard({ detail, onOpenFileLine }) {
  if (!detail) return null;
  const errorPaths = Array.isArray(detail.errorPaths) ? detail.errorPaths : [];
  const warnings = Array.isArray(detail.warnings) ? detail.warnings : [];
  const suggestedActions = Array.isArray(detail.suggestedActions) ? detail.suggestedActions : [];
  return (
    <div className="mt-4 min-w-0 overflow-hidden rounded-lg border border-rose-200 bg-rose-50/70 p-3">
      <div className="mb-2 flex items-start gap-2">
        <AlertTriangle size={16} className="mt-0.5 shrink-0 text-rose-700" />
        <div className="min-w-0">
          <div className="text-xs font-black uppercase tracking-normal text-rose-800">{detail.title || "Validation failed"}</div>
          <p className="mt-1 text-sm font-semibold text-rose-950">{detail.headline}</p>
        </div>
      </div>
      {detail.reason ? (
        <p className="mt-2 text-xs leading-relaxed text-rose-900">{detail.reason}</p>
      ) : null}
      {errorPaths.length ? (
        <div className="mt-3">
          <div className="mb-1 text-[11px] font-black uppercase tracking-normal text-rose-800">Affected files</div>
          <div className="flex flex-wrap gap-1.5">
            {errorPaths.slice(0, 8).map((path) => (
              <button
                key={path}
                type="button"
                className="inline-flex max-w-full items-center gap-1 rounded-md bg-white px-2 py-1 text-[11px] font-bold text-rose-800 transition hover:bg-rose-100"
                onClick={() => onOpenFileLine?.(path, 1)}
              >
                <FileCode2 size={12} />
                <span className="truncate">{path}</span>
              </button>
            ))}
          </div>
        </div>
      ) : null}
      {warnings.length ? (
        <div className="mt-3">
          <div className="mb-1 text-[11px] font-black uppercase tracking-normal text-rose-800">Warnings</div>
          <ul className="grid gap-1 text-xs text-rose-900">
            {warnings.slice(0, 6).map((warning, index) => (
              <li key={`${warning}-${index}`} className="wt-wrap-anywhere">{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {detail.buildLogExcerpt ? (
        <details className="mt-3 overflow-hidden rounded-md border border-rose-200 bg-white">
          <summary className="cursor-pointer px-3 py-2 text-[11px] font-black uppercase tracking-normal text-rose-800">
            Build log excerpt
          </summary>
          <pre className="wt-log-pre max-h-40 overflow-auto border-t border-rose-100 p-2 text-[11px] leading-relaxed text-slate-700">
            {detail.buildLogExcerpt}
          </pre>
        </details>
      ) : null}
      {suggestedActions.length ? (
        <div className="mt-3 border-t border-rose-200 pt-3">
          <div className="mb-1 text-[11px] font-black uppercase tracking-normal text-rose-800">Suggested next steps</div>
          <ul className="grid gap-1 text-xs text-rose-900">
            {suggestedActions.slice(0, 4).map((action, index) => (
              <li key={`${action}-${index}`} className="wt-wrap-anywhere">• {action}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function DiffPreview({ detail }) {
  const diffs = detail.diffs || [];
  if (!diffs.length) return null;
  return (
    <div className="mt-4 min-w-0 max-w-full overflow-hidden rounded-lg border border-slate-200 bg-white p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-2 text-xs font-black uppercase tracking-normal text-slate-800">
          <FileCode2 size={14} />
          Code changes
        </span>
        <span className="text-xs font-bold text-muted">
          {detail.file_count} files +{detail.added || 0} / -{detail.removed || 0}
        </span>
      </div>
      <div className="grid min-w-0 gap-2">
        {diffs.slice(0, 4).map((fileDiff) => (
          <details key={fileDiff.path} className="min-w-0 overflow-hidden rounded-md border border-line bg-slate-50" open={diffs.length === 1}>
            <summary className="flex cursor-pointer items-center justify-between gap-2 px-2 py-2 text-xs font-black text-ink">
              <span className="min-w-0 truncate">{fileDiff.path}</span>
              <span className="shrink-0 text-[11px] font-bold text-muted">
                +{fileDiff.added || 0} / -{fileDiff.removed || 0}
              </span>
            </summary>
            <pre className="wt-code-surface wt-log-pre max-h-52 max-w-full border-t border-line p-2 text-[11px] leading-relaxed">
              {diffLines(fileDiff.diff).map((line, index) => (
                <div key={`${fileDiff.path}-${index}`} className={`${diffLineClass(line)} wt-wrap-anywhere whitespace-pre-wrap`}>
                  {line || " "}
                </div>
              ))}
            </pre>
          </details>
        ))}
      </div>
      {detail.truncated_files ? (
        <p className="mt-2 text-[11px] font-bold text-muted">{detail.truncated_files} more changed files hidden in this preview.</p>
      ) : null}
    </div>
  );
}

function PatchDiffPanel({ detail, pendingApproval = null, disabled = false, onApprove, onReject, onOpenFileLine }) {
  const diffs = detail?.diffs || [];
  if (!diffs.length) return null;
  const approvalPending = pendingApproval?.status === "pending";
  const stagedOnly = detail?.staged && !detail?.persisted;
  return (
    <div className="min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-white p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-2 text-xs font-black uppercase tracking-normal text-slate-800">
          <FileCode2 size={14} />
          {stagedOnly ? "Staged patch diff" : "Patch diff"}
        </span>
        <span className="text-xs font-bold text-muted">
          {detail.file_count || diffs.length} files +{detail.added || 0} / -{detail.removed || 0}
        </span>
      </div>
      {stagedOnly ? (
        <p className="mb-2 text-xs font-bold text-amber-700">These edits are staged in the agent loop and are not saved until commit succeeds.</p>
      ) : null}
      {approvalPending ? (
        <p className="mb-2 text-xs font-bold text-amber-700">Review these changes before they are applied to your project.</p>
      ) : null}
      <div className="grid min-w-0 gap-2">
        {diffs.slice(0, 6).map((fileDiff) => (
          <details key={fileDiff.path} className="min-w-0 overflow-hidden rounded-md border border-line bg-slate-50">
            <summary className="flex cursor-pointer items-center justify-between gap-2 px-2 py-2 text-xs font-black text-ink">
              <button
                type="button"
                className="min-w-0 truncate text-left hover:text-worktual-700"
                onClick={(event) => {
                  event.preventDefault();
                  onOpenFileLine?.(fileDiff.path, 1);
                }}
              >
                {fileDiff.path}
              </button>
              <span className="shrink-0 text-[11px] font-bold text-muted">
                +{fileDiff.added || 0} / -{fileDiff.removed || 0}
              </span>
            </summary>
            <pre className="wt-code-surface wt-log-pre max-h-40 max-w-full border-t border-line p-2 text-[11px] leading-relaxed">
              {diffLines(fileDiff.diff).map((line, index) => (
                <div key={`${fileDiff.path}-panel-${index}`} className={`${diffLineClass(line)} wt-wrap-anywhere whitespace-pre-wrap`}>
                  {line || " "}
                </div>
              ))}
            </pre>
          </details>
        ))}
      </div>
      {approvalPending ? (
        <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-3">
          <button
            className="rounded-md bg-ink px-3 py-2 text-xs font-black text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
            type="button"
            disabled={disabled}
            onClick={() => onApprove?.()}
          >
            Apply patch
          </button>
          <button
            className="rounded-md border border-line bg-white px-3 py-2 text-xs font-black text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
            type="button"
            disabled={disabled}
            onClick={() => onReject?.()}
          >
            Reject
          </button>
        </div>
      ) : null}
    </div>
  );
}

function assignmentLabel(assignments, taskId) {
  const assignment = assignments.find((item) => item.task_id === taskId);
  if (!assignment?.agent_id) return "";
  return assignment.created ? `${assignment.agent_id} created` : assignment.reused ? `${assignment.agent_id} reused` : assignment.agent_id;
}

function diffLines(diff = "") {
  return String(diff || "").split("\n").slice(0, 180);
}

function diffLineClass(line) {
  if (line.startsWith("+++") || line.startsWith("---")) return "text-slate-400";
  if (line.startsWith("+")) return "bg-emerald-950/70 text-emerald-200";
  if (line.startsWith("-")) return "bg-rose-950/70 text-rose-200";
  if (line.startsWith("@@")) return "text-sky-300";
  return "text-slate-300";
}

function CodeWorkspace({
  activeProject,
  browserWorkspace,
  editorValue,
  file,
  files,
  hasBrowserDirectoryHandle = false,
  hasUnsavedChanges,
  isBuilding,
  isCollapsed,
  isGenerating = false,
  isReconnectingBrowserFolder = false,
  isSaving,
  liveWrittenPaths = [],
  patchDiff = null,
  patchApproval = null,
  onApprovePatch,
  onRejectPatch,
  selectedPath,
  onChange,
  onCloseFile,
  onDownloadCode,
  isDownloadingProject = false,
  onPreview,
  onReconnectBrowserFolder,
  onSave,
  onSelectFile,
  onOpenDiffFile,
  onEditorMount,
  onTogglePanel,
}) {
  const [activeWorkspaceTab, setActiveWorkspaceTab] = useState("files");
  const displayFiles = files.filter((item) => !isHiddenProjectFilePath(item.path));
  const visibleFiles = displayFiles;
  const diffCount = patchDiff?.diffs?.length || 0;
  const canReconnectBrowserFolder =
    Boolean(browserWorkspace && browserWorkspace.kind === "directory" && !hasBrowserDirectoryHandle && !activeProject?.local_path);
  const isPreviewBusy = isBuilding || isGenerating;
  const selectedOriginalPath = originalFilePathLabel({
    project: activeProject,
    browserWorkspace,
    hasBrowserDirectoryHandle,
    filePath: file?.path || selectedPath,
  });
  const workspaceContextName =
    pathBaseName(activeProject?.local_path || "") ||
    browserWorkspace?.name ||
    activeProject?.name ||
    "workspace";

  useEffect(() => {
    if (file?.path) {
      setActiveWorkspaceTab("code");
      return;
    }
    if (diffCount) {
      setActiveWorkspaceTab("diff");
      return;
    }
    setActiveWorkspaceTab("files");
  }, [file?.path, diffCount]);

  function openFileInCodeTab(item) {
    onSelectFile(item);
    setActiveWorkspaceTab("code");
  }

  function closeFileToFilesTab() {
    onCloseFile();
    setActiveWorkspaceTab("files");
  }

  const workspaceTabs = [
    { id: "files", label: "Files", count: displayFiles.length, disabled: false, icon: FolderOpen },
    { id: "code", label: "Code", count: file ? 1 : 0, disabled: !file, icon: FileCode2 },
    { id: "diff", label: "Diff", count: diffCount, disabled: !diffCount, icon: Archive },
  ];

  if (isCollapsed) {
    return (
      <aside className="flex min-h-0 flex-col items-center border-l border-line bg-panel py-3 text-ink">
        <IconButton label="Open code panel" onClick={onTogglePanel}>
          <PanelLeftOpen size={16} />
        </IconButton>
        <span
          className="mt-3 text-[11px] font-semibold uppercase tracking-normal text-slate-500"
          style={{ writingMode: "vertical-rl" }}
        >
          Code
        </span>
      </aside>
    );
  }

  return (
    <aside className="wt-workspace-panel relative z-0 flex min-h-0 min-w-0 flex-col overflow-hidden border-l border-line bg-panel">
      <div className="wt-panel-header shrink-0 border-b border-line px-4 py-4 text-ink">
        <div className="flex min-h-8 items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <IconButton tiny label="Close code panel" onClick={onTogglePanel}>
              <PanelRightClose size={12} />
            </IconButton>
            <div className="min-w-0">
              <p className="truncate text-[10px] font-semibold text-slate-500">On {workspaceContextName}</p>
              <h2 className="mt-0.5 truncate text-[11px] font-semibold text-ink">{file?.path || (displayFiles.length ? `${displayFiles.length} project files` : "No files yet")}</h2>
            {selectedOriginalPath ? (
              <p className="mt-0.5 truncate text-[9.5px] font-medium text-slate-500" title={selectedOriginalPath}>
                Original path: {selectedOriginalPath}
              </p>
            ) : null}
            {canReconnectBrowserFolder ? (
              <button
                data-browser-folder-reconnect
                className="mt-2 inline-flex max-w-full items-center gap-1 rounded-md border border-amber-400/40 bg-amber-500/10 px-2 py-1 text-[9.5px] font-bold text-amber-300 transition hover:border-amber-300 hover:bg-amber-500/20 disabled:cursor-not-allowed disabled:opacity-60"
                type="button"
                onClick={onReconnectBrowserFolder}
                disabled={isReconnectingBrowserFolder}
              >
                {isReconnectingBrowserFolder ? <Loader2 className="animate-spin" size={12} /> : <FolderOpen size={12} />}
                Reconnect local folder
              </button>
            ) : null}
            </div>
          </div>
          <div className="flex shrink-0 items-center justify-end gap-1.5">
            {hasUnsavedChanges ? <span className="text-[9.5px] font-semibold text-slate-400">Unsaved</span> : null}
            <IconButton tiny label="Save file" onClick={onSave} disabled={!hasUnsavedChanges || isSaving || isGenerating}>
              {isSaving ? <Loader2 className="animate-spin" size={12} /> : <Save size={12} />}
            </IconButton>
            {onDownloadCode ? (
              <button
                className="wt-control-button inline-flex size-7 items-center justify-center rounded-md transition disabled:cursor-not-allowed disabled:opacity-60"
                type="button"
                onClick={onDownloadCode}
                disabled={isDownloadingProject || !files.length}
                title="Download all generated project files as a ZIP from the backend workspace"
                aria-label="Download code"
              >
                {isDownloadingProject ? <Loader2 className="animate-spin" size={11} /> : <Archive size={11} />}
              </button>
            ) : null}
            <button
              className="wt-primary-button inline-flex size-7 items-center justify-center rounded-md transition disabled:cursor-not-allowed disabled:opacity-60"
              type="button"
              onClick={onPreview}
              disabled={isPreviewBusy || !files.length}
              title={isGenerating ? "Generation is running" : "Preview"}
              aria-label="Preview"
            >
              {isPreviewBusy ? <Loader2 className="animate-spin" size={11} /> : <ExternalLink size={11} />}
            </button>
          </div>
        </div>
        <div className="mt-4 grid gap-1.5">
          {workspaceTabs.map((tab) => (
            <WorkspaceNavButton
              key={tab.id}
              tab={tab}
              active={activeWorkspaceTab === tab.id}
              onClick={() => setActiveWorkspaceTab(tab.id)}
            />
          ))}
        </div>
      </div>
      <div className="flex min-h-0 flex-1 flex-col">
        {activeWorkspaceTab === "files" ? (
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4">
          {displayFiles.length ? (
            <div className="grid gap-1.5">
              {visibleFiles.map((item) => {
                const isOpen = selectedPath === item.path;
                const isLiveWritten = liveWrittenPaths.includes(item.path);
                const originalPath = originalFilePathLabel({
                  project: activeProject,
                  browserWorkspace,
                  hasBrowserDirectoryHandle,
                  filePath: item.path,
                });
                return (
            <button
                    key={item.path}
                    className={`grid min-h-10 grid-cols-[16px_16px_minmax(0,1fr)] items-start gap-2 rounded-md px-2.5 py-2 text-left text-[10px] font-medium transition ${
                      isOpen
                        ? "bg-white/10 text-white"
                        : isLiveWritten
                          ? "bg-emerald-500/10 text-emerald-200"
                          : "text-slate-400 hover:bg-white/5 hover:text-slate-100"
                    }`}
              type="button"
                    title={originalPath || item.path}
                    aria-label={isOpen ? `Close ${item.path}` : `Open ${item.path}`}
                    aria-expanded={isOpen}
                    onClick={() => (isOpen ? closeFileToFilesTab() : openFileInCodeTab(item))}
            >
                    {isOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                    <FileCode2 className="mt-0.5" size={12} />
                    <span className="min-w-0">
                      <span className="block truncate">{item.path}</span>
                      {isOpen && originalPath ? (
                        <span className="mt-1 block truncate text-[9.5px] font-medium text-slate-500">
                          Original path: {originalPath}
                        </span>
                      ) : null}
                      {isOpen && canReconnectBrowserFolder ? (
                        <span className="mt-1 inline-flex items-center gap-1 text-[9.5px] font-bold text-amber-300">
                          <FolderOpen size={11} />
                          Reconnect required before local write-back
                        </span>
                      ) : null}
                    </span>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="flex min-h-[22rem] items-center justify-center rounded-xl border border-dashed border-line bg-black/15 p-6 text-center">
              <div className="max-w-xs">
                <FileCode2 className="mx-auto text-slate-500" size={28} />
                <p className="mt-3 text-sm font-black text-slate-300">
                  {isGenerating ? "Files are being prepared" : "No project files yet"}
                </p>
                <p className="mt-2 text-xs leading-relaxed text-muted">
                  {isGenerating ? "Generated files will appear here as each worker saves a valid artifact." : "Start a generation or link a local folder to populate this workspace."}
                </p>
              </div>
            </div>
          )}
        </div>
        ) : null}
        {activeWorkspaceTab === "diff" ? (
          <div className="min-h-0 flex-1 overflow-y-auto bg-panel p-4">
            {patchDiff?.diffs?.length ? (
            <PatchDiffPanel
              detail={patchDiff}
              pendingApproval={patchApproval}
              disabled={isGenerating}
              onApprove={onApprovePatch}
              onReject={onRejectPatch}
              onOpenFileLine={onOpenDiffFile}
            />
            ) : (
              <div className="flex min-h-[22rem] items-center justify-center rounded-xl border border-dashed border-line bg-black/15 p-6 text-center text-sm font-bold text-muted">
                No patch diff for this run yet.
              </div>
            )}
          </div>
        ) : null}
      {activeWorkspaceTab === "code" ? (
      <div className="min-h-0 flex-1 overflow-hidden">
        {file ? (
          <div className="h-full min-h-0 overflow-hidden">
          <Editor
            height="100%"
            language={languageForPath(file.path)}
            path={file.path}
            beforeMount={defineWorktualEditorTheme}
            theme="worktual-dark"
            value={editorValue}
            onMount={onEditorMount}
            options={{
              minimap: { enabled: false },
              fontFamily: '"SFMono-Regular", "Cascadia Code", "JetBrains Mono", Menlo, Monaco, Consolas, monospace',
              fontSize: 9.5,
              lineHeight: 22,
              wordWrap: "on",
              scrollBeyondLastLine: false,
              automaticLayout: true,
              overviewRulerBorder: false,
              renderLineHighlight: "line",
            }}
            onChange={(value) => onChange(value || "")}
          />
          </div>
        ) : (
          <div className="flex h-full items-center justify-center p-6 text-center text-sm font-bold text-muted">
            <div className="rounded-xl border border-dashed border-line bg-black/15 px-6 py-8">
              <FileCode2 className="mx-auto mb-3 text-slate-500" size={28} />
              Select a file to edit.
            </div>
          </div>
        )}
      </div>
      ) : null}
      </div>
    </aside>
  );
}

function WorkspaceNavButton({ active, onClick, tab }) {
  const Icon = tab.icon || FileCode2;
  return (
    <button
      type="button"
      className={`group flex min-h-8 items-center gap-2 rounded-md px-2 text-left text-[10px] font-semibold transition disabled:cursor-not-allowed disabled:opacity-35 ${
        active ? "bg-white/10 text-white" : "text-slate-500 hover:bg-white/5 hover:text-slate-200"
      }`}
      disabled={tab.disabled}
      onClick={onClick}
    >
      <Icon className="shrink-0" size={13} />
      <span className="min-w-0 flex-1 truncate">{tab.label}</span>
      {tab.count ? (
        <span className="rounded-full bg-black/40 px-1.5 py-0.5 text-[9px] font-black text-slate-300">
          {tab.count}
        </span>
      ) : null}
    </button>
  );
}

function ChatBubble({ message, disabled = false, onAction }) {
  const isUser = message.role === "user";
  const confirmationPending = !isUser && message.confirmation?.status === "pending";
  return (
    <article className={`flex min-w-0 ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`min-w-0 max-w-[82%] overflow-hidden px-1 py-0.5 text-sm leading-relaxed ${
        isUser ? "text-right text-slate-100" : "text-left text-slate-300"
      }`}>
        <div className="wt-wrap-anywhere whitespace-pre-wrap">{message.content}</div>
        <ChatMessageAttachments attachments={message.attachments} />
        {confirmationPending ? (
          <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-3">
            <button
              className="rounded-md bg-ink px-3 py-2 text-xs font-black text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              type="button"
              disabled={disabled}
              onClick={() => onAction?.("Confirm and proceed with this execution brief.", { type: "confirm_confirmation" })}
            >
              Confirm and proceed
            </button>
            <button
              className="rounded-md border border-line bg-white px-3 py-2 text-xs font-black text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
              type="button"
              disabled={disabled}
              onClick={() => onAction?.("Cancel the pending execution brief.", { type: "cancel_confirmation" })}
            >
              Cancel
            </button>
          </div>
        ) : null}
      </div>
    </article>
  );
}

function StatusBubble({ detail, label }) {
  return (
    <div className="inline-flex w-fit items-start gap-2 rounded-xl border border-worktual-100 bg-worktual-50 p-3 text-sm font-bold text-worktual-700">
      <Loader2 className="animate-spin" size={16} />
      <span>
        <span className="block">{label}</span>
        {detail ? <span className="mt-1 block text-xs font-black text-worktual-600">{formatStepName(detail)}</span> : null}
      </span>
    </div>
  );
}

function ProgressIcon({ status }) {
  if (status === "completed") return <CheckCircle2 className="mt-0.5 text-worktual-700" size={16} />;
  if (status === "failed") return <AlertTriangle className="mt-0.5 text-slate-950" size={16} />;
  return <Loader2 className="mt-0.5 animate-spin text-worktual-700" size={16} />;
}

function IconButton({ children, compact = false, disabled, label, onClick, tiny = false }) {
  return (
    <button
      className={`inline-flex items-center justify-center rounded-lg border border-line bg-white text-ink transition hover:border-worktual-300 hover:text-worktual-700 disabled:cursor-not-allowed disabled:opacity-50 ${
        tiny ? "size-7" : compact ? "size-8" : "size-9"
      }`}
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
    >
      {children}
    </button>
  );
}

async function buildBrowserProjectSourceFromHandle(directoryHandle) {
  const snapshot = await readBrowserProjectDirectory(directoryHandle);
  return {
    kind: "directory",
    name: directoryHandle.name,
    directoryHandle,
    files: snapshot.files,
    diagnostics: snapshot.diagnostics,
  };
}

async function requestBrowserProjectSource() {
  if (supportsWritableBrowserDirectoryPicker()) {
    const directoryHandle = await pickBrowserDirectoryHandle();
    return buildBrowserProjectSourceFromHandle(directoryHandle);
  }
  return requestUploadedProjectDirectory();
}

function supportsWritableBrowserDirectoryPicker() {
  if (!window.showDirectoryPicker) return false;
  if (window.isSecureContext) return true;
  return isLoopbackHost(window.location.hostname);
}

function localFolderAccessHint() {
  if (window.isSecureContext || isLoopbackHost(window.location.hostname)) {
    return "";
  }
  return `You opened Worktual at ${window.location.host} over HTTP. Writable folder access requires HTTPS or localhost — uploads will be read-only on this network URL. Use backend workspace, or open via https:// on this server.`;
}

async function pickBrowserDirectoryHandle() {
  const directoryHandle = await window.showDirectoryPicker({ mode: "readwrite" });
  await requestBrowserDirectoryPermission(directoryHandle);
  return directoryHandle;
}

async function requestBrowserDirectoryPermission(directoryHandle) {
  const options = { mode: "readwrite" };
  const currentPermission = directoryHandle.queryPermission
    ? await directoryHandle.queryPermission(options)
    : "prompt";
  if (currentPermission === "granted") return;
  const nextPermission = directoryHandle.requestPermission
    ? await directoryHandle.requestPermission(options)
    : "denied";
  if (nextPermission === "granted") return;
  throw new Error("Folder write permission was not granted.");
}

async function ensureBrowserDirectoryPermission(directoryHandle) {
  await requestBrowserDirectoryPermission(directoryHandle);
}

function requestUploadedProjectDirectory() {
  return new Promise((resolve, reject) => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.webkitdirectory = true;
    input.setAttribute("webkitdirectory", "");
    input.setAttribute("directory", "");
    input.setAttribute("mozdirectory", "");
    input.style.display = "none";

    input.addEventListener(
      "change",
      async () => {
        try {
          const snapshot = await readUploadedProjectDirectory(input.files || []);
          resolve(snapshot);
        } catch (error) {
          reject(error);
        } finally {
          input.remove();
        }
      },
      { once: true },
    );
    input.addEventListener(
      "cancel",
      () => {
        input.remove();
        reject(new DOMException("Folder selection cancelled.", "AbortError"));
      },
      { once: true },
    );

    document.body.appendChild(input);
    input.click();
  });
}

async function readBrowserProjectDirectory(directoryHandle) {
  const diagnostics = {
    scannedFiles: 0,
    rootFileNames: [],
    skippedFiles: [],
  };
  const files = await readBrowserProjectFiles(directoryHandle, "", diagnostics);
  return { files, diagnostics };
}

async function readUploadedProjectDirectory(fileList) {
  const uploadedFiles = Array.from(fileList || []);
  if (!uploadedFiles.length) {
    throw new DOMException("Folder selection cancelled.", "AbortError");
  }
  const folderName = uploadedProjectFolderName(uploadedFiles);
  const diagnostics = {
    scannedFiles: 0,
    rootFileNames: [],
    skippedFiles: [],
  };
  const files = [];
  for (const uploadedFile of uploadedFiles) {
    const uploadedPath = uploadedFile.webkitRelativePath || uploadedFile.name;
    const relativePath = normalizeUploadedProjectPath(uploadedPath, folderName);
    diagnostics.scannedFiles += 1;
    if (!relativePath.includes("/")) {
      diagnostics.rootFileNames.push(relativePath);
    }
    if (pathHasIgnoredBrowserDirectory(relativePath)) {
      diagnostics.skippedFiles.push({ path: relativePath, reason: "ignored directory" });
      continue;
    }
    if (!isSupportedBrowserProjectFile(relativePath)) {
      diagnostics.skippedFiles.push({ path: relativePath, reason: "ignored file" });
      continue;
    }
    if (uploadedFile.size > MAX_BROWSER_FILE_BYTES) {
      throw new Error(`Local file is too large to import: ${relativePath}`);
    }
    files.push({ path: relativePath, content: await readBrowserFileContent(uploadedFile, relativePath) });
  }
  return {
    kind: "upload",
    name: folderName || "Uploaded folder",
    directoryHandle: null,
    files,
    diagnostics,
  };
}

async function readBrowserProjectFiles(directoryHandle, basePath = "", diagnostics = null) {
  const files = [];
  for await (const [name, handle] of directoryHandle.entries()) {
    if (handle.kind === "directory") {
      if (browserDirectoryShouldSkip(name)) {
        diagnostics?.skippedFiles.push({ path: joinBrowserPath(basePath, name), reason: "ignored directory" });
        continue;
      }
      files.push(...await readBrowserProjectFiles(handle, joinBrowserPath(basePath, name), diagnostics));
      continue;
    }
    if (handle.kind !== "file") continue;
    const relativePath = normalizeBrowserProjectPath(joinBrowserPath(basePath, name));
    if (diagnostics) {
      diagnostics.scannedFiles += 1;
    }
    if (diagnostics && !basePath) {
      diagnostics.rootFileNames.push(relativePath);
    }
    if (!isSupportedBrowserProjectFile(relativePath)) {
      diagnostics?.skippedFiles.push({ path: relativePath, reason: "ignored file" });
      continue;
    }
    const file = await handle.getFile();
    if (file.size > MAX_BROWSER_FILE_BYTES) {
      throw new Error(`Local file is too large to import: ${relativePath}`);
    }
    files.push({ path: relativePath, content: await readBrowserFileContent(file, relativePath) });
  }
  return files;
}

function browserImportSummary(directoryName, files, diagnostics = null, options = {}) {
  const canWriteBack = options.canWriteBack !== false;
  if (!files.length) {
    const scannedSummary = diagnostics?.scannedFiles
      ? ` Scanned ${diagnostics.scannedFiles} file(s); skipped ${diagnostics.skippedFiles.length} ignored entries.`
      : "";
    const syncSummary = canWriteBack
      ? " Generated files and saved edits will be written there."
      : " This folder import is read-only because writable browser folder access is unavailable in this context; generated files and saved edits will stay in the backend workspace.";
    return `Connected empty system folder: ${directoryName}.${scannedSummary} No project files were imported yet.${syncSummary}`;
  }
  const rootFiles = importedRootFilePaths(files);
  const rootSummary = rootFiles.length
    ? ` Root files: ${formatPathList(rootFiles)}.`
    : " No root project files were imported.";
  const skippedCount = diagnostics?.skippedFiles?.length || 0;
  const skippedSummary = skippedCount ? ` Skipped ${skippedCount} ignored entries.` : "";
  const syncSummary = canWriteBack
    ? " Generated files and saved edits will be written there."
    : " This folder import is read-only because writable browser folder access is unavailable in this context; generated files and saved edits will stay in the backend workspace.";
  return `Connected system folder: ${directoryName}. Imported ${files.length} files.${rootSummary}${skippedSummary}${syncSummary}`;
}

function browserProjectImportBlockingError() {
  return "";
}

function browserProjectRootWarning() {
  return "";
}

function assertBackendKeptImportedRootFiles(requestedFiles, importedFiles) {
  const requestedRootFiles = importedRootFilePaths(requestedFiles);
  if (!requestedRootFiles.length) return;
  const importedPaths = new Set((importedFiles || []).map((file) => file.path));
  const missingRootFiles = requestedRootFiles.filter((path) => !importedPaths.has(path));
  if (!missingRootFiles.length) return;
  throw new Error(`Backend import dropped root project file(s): ${missingRootFiles.join(", ")}. Restart the backend so the updated project-file allow-list is active.`);
}

function importedRootFilePaths(files) {
  return (files || [])
    .map((file) => (file.path ? normalizeBrowserProjectPath(file.path) : ""))
    .filter(Boolean)
    .filter((path) => SUPPORTED_ROOT_FILES.has(path));
}

function missingRequiredBrowserRootFiles(files) {
  const paths = new Set((files || []).map((file) => file.path));
  return REQUIRED_BROWSER_PROJECT_ROOT_FILES.filter((path) => !paths.has(path));
}

function hasStaticBrowserProjectEntry(files) {
  return (files || []).some((file) => file.path === STATIC_BROWSER_PROJECT_ENTRY_FILE);
}

function hasRequiredBrowserSourceFiles(files) {
  return (files || []).some((file) => file.path?.startsWith(REQUIRED_BROWSER_PROJECT_SOURCE_PREFIX));
}

function hasViteBrowserSourceFiles(files) {
  const paths = new Set((files || []).map((file) => file.path));
  return ["src/main.jsx", "src/main.tsx", "src/App.jsx", "src/App.tsx", "src/index.css"].some((path) => paths.has(path));
}

function formatPathList(paths) {
  const visiblePaths = paths.slice(0, IMPORT_SUMMARY_PATH_LIMIT);
  const suffix = paths.length > visiblePaths.length ? `, +${paths.length - visiblePaths.length} more` : "";
  return `${visiblePaths.join(", ")}${suffix}`;
}

function readBrowserFileContent(file, relativePath) {
  if (!isBinaryBrowserProjectFile(relativePath)) {
    return file.text();
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error(`Failed to read binary asset: ${relativePath}`));
    reader.readAsDataURL(file);
  });
}

async function writeBrowserProjectFiles(directoryHandle, files) {
  let count = 0;
  for (const file of files) {
    const relativePath = normalizeBrowserProjectPath(file.path);
    if (!isSupportedBrowserProjectFile(relativePath)) continue;
    const parts = relativePath.split("/");
    const fileName = parts.pop();
    let currentDirectory = directoryHandle;
    for (const part of parts) {
      currentDirectory = await currentDirectory.getDirectoryHandle(part, { create: true });
    }
    const fileHandle = await currentDirectory.getFileHandle(fileName, { create: true });
    const writable = await fileHandle.createWritable();
    await writable.write(await browserWritableFileContent(relativePath, file.content ?? file.code ?? ""));
    await writable.close();
    count += 1;
  }
  return count;
}

async function browserWritableFileContent(relativePath, content) {
  if (isBinaryBrowserProjectFile(relativePath) && typeof content === "string" && content.startsWith("data:")) {
    return await fetch(content).then((response) => response.blob());
  }
  return content;
}

function joinBrowserPath(basePath, name) {
  return [basePath, name].filter(Boolean).join("/");
}

function uploadedProjectFolderName(files) {
  const firstPath = files.find((file) => file.webkitRelativePath)?.webkitRelativePath || "";
  return firstPath.split("/").filter(Boolean)[0] || "";
}

function normalizeUploadedProjectPath(path = "", rootName = "") {
  let normalized = String(path).replaceAll("\\", "/").replace(/^\/+/, "");
  if (rootName && normalized === rootName) {
    normalized = "";
  } else if (rootName && normalized.startsWith(`${rootName}/`)) {
    normalized = normalized.slice(rootName.length + 1);
  }
  return normalizeBrowserProjectPath(normalized);
}

function normalizeBrowserProjectPath(path = "") {
  const normalized = String(path).replaceAll("\\", "/").replace(/^\/+/, "");
  const parts = normalized.split("/").filter(Boolean);
  if (!parts.length || parts.some((part) => part === "." || part === "..")) {
    throw new Error(`Unsafe local file path: ${path}`);
  }
  return parts.join("/");
}

function browserDirectoryShouldSkip(name) {
  if (ALLOWED_BROWSER_DOT_DIRECTORIES.has(name)) return false;
  return IGNORED_BROWSER_DIRECTORIES.has(name) || name.startsWith(".");
}

function pathHasIgnoredBrowserDirectory(path = "") {
  return String(path)
    .split("/")
    .slice(0, -1)
    .some((part) => {
      if (ALLOWED_BROWSER_DOT_DIRECTORIES.has(part)) return false;
      return IGNORED_BROWSER_DIRECTORIES.has(part) || part.startsWith(".");
    });
}

function isSupportedBrowserProjectFile(path) {
  const fileName = String(path).split("/").pop() || "";
  return Boolean(path) && !pathHasIgnoredBrowserDirectory(path) && !IGNORED_BROWSER_FILE_NAMES.has(fileName);
}

function isBinaryBrowserProjectFile(path) {
  return BINARY_PUBLIC_ASSET_EXTENSIONS.has(browserPathExtension(path));
}

function browserPathExtension(path = "") {
  const fileName = String(path).split("/").pop() || "";
  const dotIndex = fileName.lastIndexOf(".");
  return dotIndex >= 0 ? fileName.slice(dotIndex).toLowerCase() : "";
}

async function bootstrapUserSkills(workspaceRoot = "") {
  try {
    const systemName = getClientSystemName();
    const params = new URLSearchParams();
    if (workspaceRoot) params.set("workspace_root", workspaceRoot);
    if (systemName) params.set("system_name", systemName);
    const query = params.toString() ? `?${params.toString()}` : "";
    return await api(`/api/skills/bootstrap${query}`, { method: "POST" });
  } catch (bootstrapError) {
    console.warn("Skills bootstrap failed:", bootstrapError);
    return null;
  }
}

async function createSkillFromPrompt(prompt, project = null, model = "") {
  const systemName = getClientSystemName();
  return await api("/api/skills/create", {
    method: "POST",
    body: {
      prompt,
      project_id: project?.id || "",
      workspace_root: project?.local_path || "",
      system_name: systemName && systemName !== "default" ? systemName : "",
      model,
    },
  });
}

function skillProgressEvent(step, message, status = "running", detail = {}) {
  return {
    id: `${step}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    step,
    message,
    status,
    detail,
    created_at: new Date().toISOString(),
  };
}

async function persistCreatedSkillProjectFile(projectId, projectFile, onProgress = null, existingProjectFile = null) {
  if (!projectId || !projectFile?.path) return null;
  let savedFile = existingProjectFile;
  if (!savedFile) {
    const payload = await api(`/api/projects/${projectId}/files/${encodePath(projectFile.path)}`, {
      method: "PUT",
      body: { content: projectFile.content || "" },
    });
    savedFile = payload.file;
  }
  onProgress?.(
    skillProgressEvent("skill.project.saved", `Saved ${savedFile.path} in the backend project.`, "completed", {
      path: savedFile.path,
    })
  );
  try {
    onProgress?.(
      skillProgressEvent("skill.local.write_back", `Writing ${savedFile.path} to the selected local/browser folder.`, "running", {
        path: savedFile.path,
      })
    );
    await writeProjectFilesToBrowserWorkspace(projectId, [savedFile]);
    onProgress?.(
      skillProgressEvent("skill.local.write_back.completed", `Wrote ${savedFile.path} to the selected local/browser folder.`, "completed", {
        path: savedFile.path,
      })
    );
  } catch (writeError) {
    console.warn("Created skill saved in backend, but local .worktual write failed:", writeError);
    onProgress?.(
      skillProgressEvent("skill.local.write_back.skipped", `Saved in backend, but local folder write-back was skipped: ${writeError.message}`, "completed", {
        path: savedFile.path,
      })
    );
  }
  return savedFile;
}

function isCreateSkillPrompt(value = "") {
  return /^\/create-skill(?:\s|$)/i.test(String(value || "").trim());
}

function isCancelPendingExecutionPrompt(value = "") {
  return /^cancel(?:\s+the)?\s+pending\s+execution\s+brief\.?$/i.test(String(value || "").trim());
}

function isHiddenProjectFilePath(path = "") {
  return String(path || "")
    .split("/")
    .some((segment) => segment.startsWith("."));
}

async function bootstrapProjectSkills(projectId, { directoryHandle = null, workspaceRoot = "", installHomeSkills = false } = {}) {
  const systemName = ensureClientSystemName();
  const params = new URLSearchParams();
  if (workspaceRoot) params.set("workspace_root", workspaceRoot);
  if (systemName) params.set("system_name", systemName);
  const query = params.toString() ? `?${params.toString()}` : "";

  let payload = null;
  try {
    payload = await api(`/api/skills/bootstrap${query}`, { method: "POST" });
  } catch (bootstrapError) {
    console.warn("Skills bootstrap payload failed:", bootstrapError);
    return null;
  }

  const files = payload.materialize_files || [];

  if (directoryHandle && files.length) {
    try {
      await ensureBrowserDirectoryPermission(directoryHandle);
      payload.local_write_count = await writeBrowserProjectFiles(directoryHandle, files);
    } catch (writeError) {
      console.warn("Failed to write skills to browser workspace:", writeError);
      payload.local_write_error = writeError.message;
    }
  }

  if (projectId) {
    try {
      const projectPayload = await api(`/api/projects/${encodeURIComponent(projectId)}/skills/bootstrap${query}`, {
        method: "POST",
      });
      payload.imported_count = projectPayload.imported_count;
      payload.imported_paths = projectPayload.imported_paths;
      payload.skills = projectPayload.skills;
      payload.count = projectPayload.count;
      if (!payload.local_write_count && projectPayload.local_write_count) {
        payload.local_write_count = projectPayload.local_write_count;
      }
    } catch (syncError) {
      console.warn("Project skills backend sync failed:", syncError);
      payload.backend_sync_error = syncError.message;
    }
  }

  if (payload.system_name) {
    setClientSystemName(payload.system_name);
  }

  if (installHomeSkills) {
    payload.user_home_sync = await installSkillsToUserHome(payload);
    if (payload.user_home_sync?.status === "failed" && projectId) {
      await recordLocalEnvironmentError(projectId, {
        operation: "install_home_skills",
        message: payload.user_home_sync.reason || "Home skills installation failed.",
        workspaceName: payload.user_home_sync.folder,
        workspaceKind: "local_helper",
        helperUrl: LOCAL_SKILLS_HELPER_URL,
        recommendedAction: "Local folder skills were installed first. Start the Worktual local skills helper if you also want ~/.worktual-skills synced on this machine.",
        details: payload.user_home_sync,
      });
    }
  }

  if (!payload.imported_count && !payload.local_write_count && payload.backend_sync_error) {
    return null;
  }
  return payload;
}

async function installSkillsToUserHome(payload) {
  const files = payload?.user_home_files || [];
  if (!files.length) return null;
  try {
    const result = await fetchLocalSkillsHelper("/install-skills", {
      method: "POST",
      body: {
        system_name: payload?.system_name || getClientSystemName(),
        files,
      },
    });
    return {
      status: "completed",
      count: result.count || 0,
      folder: result.skills_dir || "~/.worktual-skills",
      home: result.home || "",
    };
  } catch (error) {
    return {
      status: "failed",
      reason: `${error.message}. Start the Worktual local skills helper on this machine and try again: ${localSkillsHelperCommand()}`,
    };
  }
}

async function fetchLocalSkillsHelper(path, options = {}) {
  const response = await fetch(`${LOCAL_SKILLS_HELPER_URL}${path}`, {
    method: options.method || "GET",
    headers: { "Content-Type": "application/json" },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const payload = await readPayload(response);
  if (!response.ok || (payload?.ok === false && !options.allowOkFalse)) {
    throw new Error(payload?.error || `Local helper request failed with status ${response.status}`);
  }
  return payload;
}

async function recordLocalEnvironmentError(projectId, errorInfo = {}) {
  if (!projectId) return null;
  try {
    return await api(`/api/projects/${encodeURIComponent(projectId)}/local-environment-error`, {
      method: "POST",
      body: {
        source: "worktual_browser",
        message: String(errorInfo.message || "Local environment operation failed."),
        operation: errorInfo.operation || "local_environment",
        workspace_name: errorInfo.workspaceName || "",
        workspace_kind: errorInfo.workspaceKind || "",
        system_name: getClientSystemName(),
        helper_url: errorInfo.helperUrl || LOCAL_SKILLS_HELPER_URL,
        recommended_action:
          errorInfo.recommendedAction ||
          "Route to local environment error handling and use terminal helper actions for dependency installation, tests, and build validation.",
        details: errorInfo.details || {},
      },
    });
  } catch (reportError) {
    console.warn("Failed to report local environment error:", reportError);
    return null;
  }
}

function skillsInstallMessage(payload) {
  const systemName = payload?.system_name || getClientSystemName();
  const parts = [];
  if (payload?.local_write_count) {
    parts.push(
      `Wrote ${payload.local_write_count} agent skill file(s) for system "${systemName}" into your selected local folder under .worktual/skills.`,
    );
  }
  if (payload?.imported_count) {
    parts.push(`Synced ${payload.imported_count} skill file(s) to the backend project store.`);
  }
  if (!payload?.local_write_count && !payload?.imported_count) {
    parts.push(`Prepared agent skills for system "${systemName}".`);
  }
  if (payload?.backend_sync_error) {
    parts.push(`Backend skill sync was skipped: ${payload.backend_sync_error}`);
  }
  const homeSync = payload?.user_home_sync;
  if (homeSync?.status === "completed") {
    parts.push(`Also created ${homeSync.folder} with ${homeSync.count} skill file(s).`);
  } else if (homeSync?.reason) {
    parts.push(`Home ~/.worktual-skills sync was skipped: ${homeSync.reason}`);
  }
  return parts.join(" ");
}

function localSkillsHelperCommand() {
  const helperUrl = `${window.location.origin}/api/local-helper/skills-helper.py`;
  return `curl -kfsSL "${helperUrl}" -o /tmp/worktual-skills-helper.py && python3 /tmp/worktual-skills-helper.py`;
}

async function downloadLocalBootstrapScript(projectPath = "") {
  const response = await fetch(`${window.location.origin}/api/local-helper/bootstrap.sh`);
  if (!response.ok) {
    throw new Error("Failed to download the local setup script.");
  }
  const text = await response.text();
  const blob = new Blob([text], { type: "application/x-sh" });
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = "worktual-local-setup.sh";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
  const quotedPath = projectPath ? ` "${projectPath.replace(/"/g, '\\"')}"` : "";
  const runCommand = `bash ~/Downloads/worktual-local-setup.sh${quotedPath}`;
  try {
    await navigator.clipboard.writeText(runCommand);
  } catch {
    // Clipboard may be blocked on non-HTTPS pages.
  }
  return runCommand;
}

function localHelperWorkspacePathStorageKey(projectId) {
  return `${LOCAL_HELPER_WORKSPACE_PATH_STORAGE_KEY}.${projectId}`;
}

function isDependencyFailureLog(buildLog = "") {
  const normalized = String(buildLog || "").toLowerCase();
  return [
    "run npm install first",
    "dependencies not installed",
    "dependency preflight failed",
    "cannot find package",
    "could not resolve",
    "module not found",
    "err_module_not_found",
    "missing dependency",
  ].some((marker) => normalized.includes(marker));
}

function terminalActionSummary(result = {}) {
  const command = Array.isArray(result.command) ? result.command.join(" ") : result.action || "terminal action";
  const lines = [
    `${result.ok ? "Passed" : "Failed"}: ${result.action || command}`,
    result.workspace ? `Workspace: ${result.workspace}` : "",
    Number.isInteger(result.exit_code) ? `Exit code: ${result.exit_code}` : result.timed_out ? "Timed out" : "",
    result.stdout ? `stdout:\n${result.stdout}` : "",
    result.stderr ? `stderr:\n${result.stderr}` : "",
  ];
  return lines.filter(Boolean).join("\n");
}

function appendBuildLogSection(buildLog, title, content) {
  return [buildLog, `# ${title}`, content].filter((part) => String(part || "").trim()).join("\n\n");
}

function normalizeSystemName(value = "") {
  const cleaned = String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, "");
  return cleaned || "default";
}

function getClientSystemName() {
  return normalizeSystemName(window.localStorage.getItem(CLIENT_SYSTEM_NAME_KEY) || "");
}

function setClientSystemName(value) {
  const normalized = normalizeSystemName(value);
  if (normalized && normalized !== "default") {
    window.localStorage.setItem(CLIENT_SYSTEM_NAME_KEY, normalized);
  }
  return normalized;
}

function ensureClientSystemName() {
  const existing = getClientSystemName();
  if (existing && existing !== "default") return existing;
  const hinted = window.prompt(
    "Enter your system username (example: vectone, kathir, rahul). Skills are stored per system.",
    existing || "",
  );
  if (!hinted) return existing || "default";
  return setClientSystemName(hinted);
}

function authTokenStorage() {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function clearLegacyAuthToken() {
  try {
    window.localStorage.removeItem(AUTH_TOKEN_KEY);
  } catch {
    // Ignore storage failures during migration.
  }
}

function getAuthToken() {
  const storage = authTokenStorage();
  if (!storage) return "";
  try {
    return storage.getItem(AUTH_TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

function setAuthToken(token) {
  if (!token) return;
  const storage = authTokenStorage();
  if (!storage) return;
  try {
    storage.setItem(AUTH_TOKEN_KEY, token);
    clearLegacyAuthToken();
  } catch {
    // Browser storage can be unavailable in private/restricted contexts.
  }
}

function clearAuthToken() {
  const storage = authTokenStorage();
  try {
    storage?.removeItem(AUTH_TOKEN_KEY);
    clearLegacyAuthToken();
  } catch {
    // Ignore storage failures during logout.
  }
}

function apiAuthHeader(options = {}) {
  if (options.skipAuth) return {};
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function isAuthError(error) {
  const message = String(error?.message || "");
  return /401|authentication required|invalid or expired session|sign in again/i.test(message);
}

function apiSystemNameHeader() {
  const systemName = getClientSystemName();
  return systemName && systemName !== "default" ? { "X-Worktual-System-Name": systemName } : {};
}

function apiChatSessionHeader(projectId) {
  const sessionId = getStoredChatSessionId(projectId);
  return sessionId ? { "X-Worktual-Chat-Session-Id": sessionId } : {};
}

function getStoredUserId() {
  try {
    return window.localStorage.getItem(CLIENT_USER_ID_KEY) || "";
  } catch {
    return "";
  }
}

function loadUserScopedMap(storageKey) {
  try {
    const raw = window.localStorage.getItem(storageKey);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function saveUserScopedMap(storageKey, map) {
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(map));
  } catch {
    // Browser storage can be unavailable in private/restricted contexts.
  }
}

function getLastActiveProjectId(userId = getStoredUserId()) {
  if (!userId) return "";
  const map = loadUserScopedMap(LAST_ACTIVE_PROJECT_BY_USER_KEY);
  return typeof map[userId] === "string" ? map[userId] : "";
}

function setLastActiveProjectId(userId, projectId) {
  if (!userId || !projectId) return;
  const map = loadUserScopedMap(LAST_ACTIVE_PROJECT_BY_USER_KEY);
  map[userId] = projectId;
  saveUserScopedMap(LAST_ACTIVE_PROJECT_BY_USER_KEY, map);
}

function resolveResumeProject(projects = [], userId = getStoredUserId()) {
  if (!projects.length) return null;
  const lastProjectId = getLastActiveProjectId(userId);
  if (lastProjectId) {
    const match = projects.find((project) => project.id === lastProjectId);
    if (match) return match;
  }
  return projects[0];
}

function loadStoredChatSessions(userId = getStoredUserId()) {
  if (!userId) return {};
  const byUser = loadUserScopedMap(CHAT_SESSION_BY_USER_KEY);
  if (byUser[userId] && typeof byUser[userId] === "object" && !Array.isArray(byUser[userId])) {
    return byUser[userId];
  }
  const legacy = loadLegacyChatSessions();
  if (Object.keys(legacy).length) {
    byUser[userId] = legacy;
    saveUserScopedMap(CHAT_SESSION_BY_USER_KEY, byUser);
    return legacy;
  }
  return {};
}

function loadLegacyChatSessions() {
  try {
    const raw = window.localStorage.getItem(CHAT_SESSION_BY_PROJECT_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function getStoredChatSessionId(projectId, userId = getStoredUserId()) {
  if (!projectId) return "";
  const sessions = loadStoredChatSessions(userId);
  return typeof sessions[projectId] === "string" ? sessions[projectId] : "";
}

function setStoredChatSessionId(projectId, sessionId, userId = getStoredUserId()) {
  if (!projectId || !sessionId || !userId) return;
  const byUser = loadUserScopedMap(CHAT_SESSION_BY_USER_KEY);
  const sessions = byUser[userId] && typeof byUser[userId] === "object" ? byUser[userId] : {};
  sessions[projectId] = sessionId;
  byUser[userId] = sessions;
  saveUserScopedMap(CHAT_SESSION_BY_USER_KEY, byUser);
}

function clearStoredChatSessionId(projectId, userId = getStoredUserId()) {
  if (!projectId || !userId) return;
  const byUser = loadUserScopedMap(CHAT_SESSION_BY_USER_KEY);
  const sessions = byUser[userId] && typeof byUser[userId] === "object" ? { ...byUser[userId] } : {};
  delete sessions[projectId];
  byUser[userId] = sessions;
  saveUserScopedMap(CHAT_SESSION_BY_USER_KEY, byUser);
}

function shortId(value = "") {
  const text = String(value || "");
  if (text.length <= 10) return text;
  return `${text.slice(0, 8)}…`;
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method || "GET",
    headers: {
      "Content-Type": "application/json",
      ...apiAuthHeader(options),
      ...apiSystemNameHeader(),
      ...(options.headers || {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const payload = await readPayload(response);
  if (!response.ok) {
    throw new Error(formatApiError(payload, response.status));
  }
  return payload;
}

async function streamGeneration(projectId, prompt, model, onProgress, options = {}) {
  if (shouldUseV1RunsStream()) {
    return streamV1Generation(projectId, prompt, model, onProgress, options);
  }
  const confirmationAction = options?.confirmationAction;
  const patchAction = options?.patchAction;
  const attachments = options?.attachments;
  const signal = options?.signal;
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/generate-stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...apiAuthHeader(),
        ...apiSystemNameHeader(),
        ...apiChatSessionHeader(projectId),
      },
      body: JSON.stringify({
        prompt,
        ...(confirmationAction ? { confirmation_action: confirmationAction } : {}),
        ...(patchAction ? { patch_action: patchAction } : {}),
        ...(model && model !== "server-default" ? { model } : {}),
        ...(attachments?.length ? { attachments } : {}),
      }),
      signal,
    });
  } catch (fetchError) {
    if (signal?.aborted || fetchError?.name === "AbortError") {
      throw createGenerationCancelledError();
    }
    throw fetchError;
  }
  if (!response.ok) {
    const payload = await readPayload(response);
    throw new Error(formatApiError(payload, response.status));
  }
  if (!response.body) throw new Error("Backend did not return a generation stream.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalPayload = null;

  try {
    while (true) {
      if (signal?.aborted) {
        await reader.cancel().catch(() => {});
        throw createGenerationCancelledError();
      }
      const { value, done } = await readGenerationStreamChunk(reader, signal);
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        finalPayload = handleGenerationStreamLine(line, onProgress, finalPayload);
      }
    }

    buffer += decoder.decode();
    if (buffer.trim()) {
      finalPayload = handleGenerationStreamLine(buffer, onProgress, finalPayload);
    }
  } catch (streamError) {
    await reader.cancel().catch(() => {});
    if (signal?.aborted || streamError?.name === "AbortError" || streamError?.cancelled) {
      throw createGenerationCancelledError();
    }
    throw streamError;
  }

  if (signal?.aborted) {
    throw createGenerationCancelledError();
  }
  if (!finalPayload) throw createGenerationStreamMissingFinalPayloadError();
  return finalPayload;
}

function readGenerationStreamChunk(reader, signal) {
  if (!GENERATION_STREAM_STALL_TIMEOUT_MS) return reader.read();
  return new Promise((resolve, reject) => {
    let settled = false;
    let timeoutId = null;
    const cleanup = () => {
      if (timeoutId) clearTimeout(timeoutId);
      signal?.removeEventListener?.("abort", handleAbort);
    };
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      cleanup();
      callback(value);
    };
    const handleAbort = () => finish(reject, createGenerationCancelledError());
    timeoutId = setTimeout(() => {
      finish(reject, createGenerationStreamStalledError());
    }, GENERATION_STREAM_STALL_TIMEOUT_MS);
    signal?.addEventListener?.("abort", handleAbort, { once: true });
    reader.read().then(
      (value) => finish(resolve, value),
      (error) => finish(reject, error),
    );
  });
}

function createGenerationCancelledError() {
  const error = new Error("Generation stopped.");
  error.cancelled = true;
  error.generationError = {
    status: "cancelled",
    category: "cancellation",
    code: "generation_cancelled",
  };
  return error;
}

function createGenerationStreamStalledError() {
  const error = new Error("Generation stream stopped sending progress before the final response.");
  error.streamStalled = true;
  error.recoverableGenerationStream = true;
  return error;
}

function createGenerationStreamMissingFinalPayloadError() {
  const error = new Error("Generation stream ended before the backend returned files.");
  error.streamMissingFinalPayload = true;
  error.recoverableGenerationStream = true;
  return error;
}

function isRecoverableGenerationStreamDisconnect(error) {
  return Boolean(error?.recoverableGenerationStream || error?.streamStalled || error?.streamMissingFinalPayload);
}

function isSavedGenerationProgressStep(step, status = "") {
  if (status && status !== "completed") return false;
  return new Set([
    "files.persisted",
    "browser.write_back.completed",
    "generation.completed",
    "agent.runtime.persisted",
  ]).has(step);
}

function shouldUseV1RunsStream() {
  return Boolean(USE_V1_RUNS_STREAM || platformStreamConfigRef.useV1RunsStream);
}

function normalizeV1StreamEvent(event) {
  if (!event || typeof event !== "object") return null;
  if (event.type === "run.cancelled") {
    return {
      type: "error",
      user_message: event.message || "Generation stopped.",
      error: event.message || "Generation stopped.",
      category: "cancellation",
      code: "generation_cancelled",
      status: "cancelled",
      detail: event.detail || {},
    };
  }
  if (event.type === "run.completed") {
    const payload =
      event.payload && (event.payload.files || event.payload.generation)
        ? event.payload
        : event.payload?.result || event.detail?.result || event.payload;
    return { type: "complete", payload: payload || {} };
  }
  if (event.type === "run.failed") {
    const detail = event.detail || {};
    const category = detail.category || event.category;
    const code = detail.code || event.code;
    if (category === "cancellation" || code === "generation_cancelled") {
      return {
        type: "error",
        user_message: event.message || "Generation stopped.",
        error: event.message || "Generation stopped.",
        category: "cancellation",
        code: "generation_cancelled",
        status: "cancelled",
        detail,
      };
    }
    return {
      type: "error",
      user_message: event.message || "Generation failed.",
      error: event.message || "Generation failed.",
      category,
      code,
      status: detail.status || event.status,
      detail,
    };
  }
  const legacyStep = event.detail?.step || event.type;
  return {
    type: "progress",
    step: legacyStep,
    message: event.message || "",
    status: event.status || "running",
    detail: event.detail || {},
    created_at: event.created_at || new Date().toISOString(),
  };
}

async function streamV1Generation(projectId, prompt, model, onProgress, options = {}) {
  const confirmationAction = options?.confirmationAction;
  const patchAction = options?.patchAction;
  const attachments = options?.attachments;
  const signal = options?.signal;
  const runIdRef = options?.runIdRef;
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/runs/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...apiAuthHeader(),
        ...apiSystemNameHeader(),
        ...apiChatSessionHeader(projectId),
      },
      body: JSON.stringify({
        workspace_id: projectId,
        prompt,
        client: "web",
        session_id: getStoredChatSessionId(projectId) || null,
        ...(confirmationAction ? { confirmation_action: confirmationAction } : {}),
        ...(patchAction ? { patch_action: patchAction } : {}),
        ...(model && model !== "server-default" ? { model } : {}),
        ...(attachments?.length ? { attachments } : {}),
      }),
      signal,
    });
  } catch (fetchError) {
    if (signal?.aborted || fetchError?.name === "AbortError") {
      throw createGenerationCancelledError();
    }
    throw fetchError;
  }
  if (!response.ok) {
    const payload = await readPayload(response);
    throw new Error(formatApiError(payload, response.status));
  }
  if (!response.body) throw new Error("Backend did not return a v1 generation stream.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalPayload = null;

  try {
    while (true) {
      if (signal?.aborted) {
        await reader.cancel().catch(() => {});
        throw createGenerationCancelledError();
      }
      const { value, done } = await readGenerationStreamChunk(reader, signal);
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        finalPayload = handleV1GenerationStreamLine(line, onProgress, finalPayload, runIdRef);
      }
    }

    buffer += decoder.decode();
    if (buffer.trim()) {
      finalPayload = handleV1GenerationStreamLine(buffer, onProgress, finalPayload, runIdRef);
    }
  } catch (streamError) {
    await reader.cancel().catch(() => {});
    if (signal?.aborted || streamError?.name === "AbortError" || streamError?.cancelled) {
      throw createGenerationCancelledError();
    }
    throw streamError;
  }

  if (signal?.aborted) {
    throw createGenerationCancelledError();
  }
  if (!finalPayload) throw createGenerationStreamMissingFinalPayloadError();
  return finalPayload;
}

function handleV1GenerationStreamLine(line, onProgress, finalPayload, runIdRef) {
  const trimmed = line.trim();
  if (!trimmed) return finalPayload;
  let event;
  try {
    event = JSON.parse(trimmed);
  } catch (parseError) {
    throw new Error(`V1 generation stream returned malformed JSON: ${parseError.message}`);
  }
  if (runIdRef && event?.type === "run.created" && event.run_id) {
    runIdRef.current = event.run_id;
  }
  const legacyMessage = normalizeV1StreamEvent(event);
  if (!legacyMessage) return finalPayload;
  return handleGenerationStreamLine(JSON.stringify(legacyMessage), onProgress, finalPayload);
}

function handleGenerationStreamLine(line, onProgress, finalPayload) {
  const trimmed = line.trim();
  if (!trimmed) return finalPayload;
  let message;
  try {
    message = JSON.parse(trimmed);
  } catch (parseError) {
    throw new Error(`Generation stream returned malformed JSON: ${parseError.message}`);
  }
  if (message.type === "progress") {
    onProgress?.(message);
    return finalPayload;
  }
  if (message.type === "complete") return message.payload;
  if (message.type === "error") {
    if (message.category === "cancellation" || message.code === "generation_cancelled") {
      throw createGenerationCancelledError();
    }
    const error = new Error(formatGenerationStreamError(message));
    error.generationError = {
      status: message.status,
      category: message.category,
      code: message.code,
      detail: message.detail || {},
    };
    throw error;
  }
  return finalPayload;
}

function formatGenerationStreamError(message) {
  const baseMessage = message.user_message || message.error || message.message || "Generation failed.";
  const detail = message.detail || {};
  const code = message.code || detail.code || "";
  const reason = detail.repair_reason || detail.reason || "";
  const suffixParts = [];
  if (code && !baseMessage.includes(code)) suffixParts.push(code);
  if (reason && !baseMessage.includes(reason)) suffixParts.push(reason);
  return suffixParts.length ? `${baseMessage} (${suffixParts.join(": ")})` : baseMessage;
}

function mergeLiveProgress(current, progressEvent) {
  const next = normalizeLiveProgress(progressEvent, current.length);
  const resolvedCurrent = resolveCompletedLiveProgress(current, next);
  if (next.step === "backend.waiting") {
    return [...resolvedCurrent.filter((item) => item.step !== "backend.waiting"), next].slice(-LIVE_PROGRESS_HISTORY_LIMIT);
  }
  return [...resolvedCurrent, next].slice(-LIVE_PROGRESS_HISTORY_LIMIT);
}

function normalizeLiveProgress(progressEvent, index) {
  return {
    id: `${progressEvent.step || "progress"}-${progressEvent.created_at || Date.now()}-${index}`,
    step: progressEvent.step || "backend.progress",
    message: progressEvent.message || "Backend progress update",
    status: progressEvent.status || "running",
    detail: progressEvent.detail || {},
    created_at: progressEvent.created_at || new Date().toISOString(),
  };
}

function resolveCompletedLiveProgress(current, next) {
  if (!["completed", "failed"].includes(next.status)) return current;
  if (next.step === "generation.failed") {
    return current.map((item) => (item.status === "running" ? { ...item, status: "failed" } : item));
  }
  return current.map((item) =>
    item.status === "running" && isProgressStepResolvedBy(item.step, next.step)
      ? { ...item, status: next.status }
      : item,
  );
}

function isProgressStepResolvedBy(runningStep, nextStep) {
  const aliases = {
    "request.received": ["request.queued"],
    "routing.completed": ["routing.started"],
    "orchestrator.completed": ["orchestrator.starting"],
    "conversation.response.completed": ["conversation.response"],
    "conversation.completed": ["conversation.response", "conversation.response.completed"],
    "generate_website_artifact.output": ["generate_website_artifact.input"],
    "artifact.validated": ["artifact.validation"],
    "files.persisted": ["files.persisting"],
    "local.sync.completed": ["local.sync"],
    "local.sync.skipped": ["local.sync"],
    "local.sync.failed": ["local.sync"],
    "browser.write_back.completed": ["browser.write_back"],
    "browser.write_back.skipped": ["browser.write_back"],
    "browser.write_back.failed": ["browser.write_back"],
    "skill.model.authored": ["skill.create.queued", "skill.model.authoring"],
    "skill.home.saved": ["skill.create.queued", "skill.model.authoring"],
    "skill.project.saved": ["skill.project.saving"],
    "skill.local.write_back.completed": ["skill.local.write_back"],
    "skill.local.write_back.skipped": ["skill.local.write_back"],
    "skill.create.completed": ["skill.create.queued", "skill.model.authoring", "skill.project.saving", "skill.local.write_back"],
    "generation.completed": ["generation.recording"],
    "agent.runtime.persisted": ["agent.runtime.persisting"],
  };
  if (aliases[nextStep]?.includes(runningStep)) return true;
  return progressStepBase(runningStep) === progressStepBase(nextStep);
}

function progressStepBase(step) {
  return step.replace(/\.(started|completed|failed|input|output)$/, "");
}

function completeRunningLiveProgress(current) {
  return current.map((item) => (item.status === "running" ? { ...item, status: "completed" } : item));
}

async function readPayload(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

function formatApiError(payload, status) {
  const detail = payload?.detail || payload?.error || payload?.message;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (detail && typeof detail === "object") {
    const structuredMessage = detail.user_message || detail.error || detail.message;
    if (typeof structuredMessage === "string" && structuredMessage.trim()) return structuredMessage;
  }
  if (Array.isArray(detail)) return detail.map((item) => item.msg || String(item)).join("; ");
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return `Backend request failed with status ${status}.`;
}

function absoluteApiUrl(path) {
  const base = API_BASE_URL || window.location.origin;
  return new URL(path, base).toString();
}

function cacheBustedApiUrl(path) {
  return `${absoluteApiUrl(path)}?t=${Date.now()}`;
}

function formatPreviewBuildError(version, { includeLog = false } = {}) {
  const log = String(version?.build_log || "").trim();
  const srcMatch = log.match(/(?:src|index)\/[^\s:()]+\.(?:jsx?|tsx?|css)/i);
  const rollupMatch = log.match(/\[vite(?:\s+esbuild)?\].*$/im) || log.match(/error during build:[^\n]*/i);
  const concise = rollupMatch?.[0] || (srcMatch ? `Issue near ${srcMatch[0]}` : "");
  if (!log) {
    return "Preview build failed. Open project history events or retry after saving your files.";
  }
  const lines = log.split("\n").map((line) => line.trim()).filter(Boolean);
  const projectLines = lines.filter(
    (line) =>
      /src\//i.test(line)
      || /Could not resolve/i.test(line)
      || /is not exported/i.test(line)
      || /Unexpected token/i.test(line)
      || /error during build/i.test(line),
  );
  const snippet = (projectLines.length ? projectLines : lines).slice(-12).join("\n");
  const headline = concise || "Preview build failed.";
  if (includeLog) {
    return `${headline}\n\n${snippet}`;
  }
  return `${headline}\n\n${snippet}`;
}

function previewVersionFromGenerationPayload(payload) {
  const runtimePreview = payload?.generation?.multi_agent_system?.agentic_runtime?.preview;
  if (runtimePreview?.preview_url) return runtimePreview;
  const runtimeFinalPreview = payload?.generation?.multi_agent_system?.agentic_runtime?.final_output?.preview;
  if (runtimeFinalPreview?.preview_url) return runtimeFinalPreview;
  return null;
}

function generatedWriteBackFilesFromPayload(payload) {
  const intent = payload?.generation?.multi_agent_system?.intent;
  if (!["simple_code", "website_generation", "website_update"].includes(intent)) return [];
  const artifactFiles = payload?.generation?.orchestration_flow?.generated_website?.files;
  if (Array.isArray(artifactFiles)) return artifactFiles.filter((file) => !isHiddenProjectFilePath(file?.path || ""));
  return (payload?.files || []).filter((file) => !isHiddenProjectFilePath(file?.path || ""));
}

function encodePath(path) {
  return path.split("/").map(encodeURIComponent).join("/");
}

function languageForPath(path = "") {
  if (path.endsWith(".json")) return "json";
  if (path.endsWith(".css")) return "css";
  if (path.endsWith(".html")) return "html";
  if (path.endsWith(".ts") || path.endsWith(".tsx")) return "typescript";
  return "javascript";
}

function defineWorktualEditorTheme(monaco) {
  monaco.editor.defineTheme("worktual-dark", {
    base: "vs-dark",
    inherit: true,
    rules: [
      { token: "", foreground: "ffffff", background: "000000" },
      { token: "comment", foreground: "8fa3ad", fontStyle: "italic" },
      { token: "keyword", foreground: "9ec5d4" },
      { token: "string", foreground: "5c7c89" },
      { token: "number", foreground: "7eb8d4" },
      { token: "type", foreground: "c5d0d6" },
      { token: "delimiter", foreground: "8fa3ad" },
    ],
    colors: {
      "editor.background": "#000000",
      "editor.foreground": "#ffffff",
      "editorGutter.background": "#000000",
      "editorLineNumber.foreground": "#5C7C89",
      "editorLineNumber.activeForeground": "#9EC5D4",
      "editor.lineHighlightBackground": "#0a0a0a",
      "editor.selectionBackground": "#1f495966",
      "editor.inactiveSelectionBackground": "#121212",
      "editorCursor.foreground": "#9EC5D4",
      "editorIndentGuide.background1": "#262626",
      "editorIndentGuide.activeBackground1": "#5C7C89",
      "editorWidget.background": "#121212",
      "editorWidget.border": "#262626",
      "scrollbarSlider.background": "#5c7c8944",
      "scrollbarSlider.hoverBackground": "#5c7c8966",
      "scrollbarSlider.activeBackground": "#9ec5d488",
    },
  });
}

function parseTimestampMs(value) {
  if (!value) return Number.NaN;
  const date = new Date(value);
  return date.getTime();
}

function formatElapsedDuration(milliseconds) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function formatStepName(value = "") {
  return value
    .split(".")
    .filter(Boolean)
    .map((part) => part.replaceAll("_", " "))
    .join(" / ");
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function defaultMessages() {
  return [{ role: "assistant", content: DEFAULT_ASSISTANT_MESSAGE }];
}

function deserializeStoredChatMessage(message = {}) {
  const metadata = message.metadata && typeof message.metadata === "object" ? message.metadata : {};
  const attachments = Array.isArray(message.attachments)
    ? message.attachments
    : Array.isArray(metadata.attachments)
      ? metadata.attachments
      : [];
  return {
    id: message.id || "",
    user_id: message.user_id || "",
    chat_session_id: message.chat_session_id || "",
    role: message.role === "model" ? "assistant" : message.role || "assistant",
    content: message.content || "",
    attachments,
    confirmation: message.confirmation || metadata.confirmation || null,
    created_at: message.created_at || null,
  };
}

function sortSkillsForPicker(skills = []) {
  return [...(skills || [])].sort((left, right) => String(left?.name || "").localeCompare(String(right?.name || "")));
}

function skillPickerItems(skills = [], slashText = "") {
  const query = String(slashText || "").replace(/^\//, "").trim().toLowerCase();
  const createSkill = {
    name: "create-skill",
    description: "Create or update a Worktual agent skill from this chat.",
    scope: "user",
    path: "builtin:create-skill",
  };
  const byName = new Map([[createSkill.name, createSkill]]);
  for (const skill of skills || []) {
    if (skill?.name && !byName.has(skill.name)) {
      byName.set(skill.name, skill);
    }
  }
  return sortSkillsForPicker(
    [...byName.values()].filter((skill) => {
      if (!query) return true;
      return (
        String(skill.name || "").toLowerCase().includes(query) ||
        String(skill.description || "").toLowerCase().includes(query)
      );
    }),
  );
}

function loadStoredBrowserWorkspaces() {
  try {
    const raw = window.localStorage.getItem(BROWSER_WORKSPACES_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function storeBrowserWorkspaces(workspaces) {
  try {
    window.localStorage.setItem(BROWSER_WORKSPACES_STORAGE_KEY, JSON.stringify(workspaces || {}));
  } catch {
    // Browser storage can be unavailable in private/restricted contexts.
  }
}

function openBrowserWorkspaceHandleDb() {
  if (!("indexedDB" in window)) return Promise.resolve(null);
  return new Promise((resolve, reject) => {
    const request = window.indexedDB.open(BROWSER_WORKSPACE_HANDLE_DB, 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(BROWSER_WORKSPACE_HANDLE_STORE)) {
        db.createObjectStore(BROWSER_WORKSPACE_HANDLE_STORE);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("Unable to open browser workspace handle storage."));
  });
}

async function saveStoredBrowserDirectoryHandle(projectId, directoryHandle) {
  try {
    if (!projectId || !directoryHandle) return;
    if (window.navigator?.storage?.persist) {
      window.navigator.storage.persist().catch(() => false);
    }
    const db = await openBrowserWorkspaceHandleDb();
    if (!db) return;
    await idbRequest((store) => store.put(directoryHandle, projectId), db, "readwrite");
    db.close();
  } catch {
    // Persisting File System Access handles is best-effort only.
  }
}

async function loadStoredBrowserDirectoryHandle(projectId) {
  try {
    if (!projectId) return null;
    const db = await openBrowserWorkspaceHandleDb();
    if (!db) return null;
    const handle = await idbRequest((store) => store.get(projectId), db, "readonly");
    db.close();
    return handle || null;
  } catch {
    return null;
  }
}

async function deleteStoredBrowserDirectoryHandle(projectId) {
  try {
    if (!projectId) return;
    const db = await openBrowserWorkspaceHandleDb();
    if (!db) return;
    await idbRequest((store) => store.delete(projectId), db, "readwrite");
    db.close();
  } catch {
    // Best-effort cleanup only.
  }
}

function idbRequest(operation, db, mode) {
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(BROWSER_WORKSPACE_HANDLE_STORE, mode);
    const request = operation(transaction.objectStore(BROWSER_WORKSPACE_HANDLE_STORE));
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("Browser workspace handle storage failed."));
    transaction.onerror = () => reject(transaction.error || new Error("Browser workspace handle transaction failed."));
  });
}

function shouldAutoNameProject(project) {
  if (!project?.name) return true;
  return project.name === DEFAULT_PROJECT_NAME || /^Website Project \d+$/i.test(project.name);
}

function projectTitleFromPrompt(prompt = "") {
  const cleaned = prompt
    .replace(/&/g, " and ")
    .replace(/[^a-zA-Z0-9\s-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const withoutLead = cleaned
    .replace(
      /^(please\s+)?(?:i\s+(?:want|need)\s+(?:you\s+)?to\s+)?(?:create|build|generate|make|develop|design|write|update|fix|change)\s+(?:me\s+|a\s+|an\s+|the\s+)?(?:website|site|web app|webpage|landing page|code|program|application)?\s*(?:for|about|to)?\s*/i,
      "",
    )
    .replace(/\b(with|using|including|that|which|having)\b.*$/i, "")
    .trim();
  const source = withoutLead || cleaned || DEFAULT_PROJECT_NAME;
  const words = source
    .split(" ")
    .filter((word) => ![
      "a",
      "an",
      "the",
      "for",
      "website",
      "site",
      "webpage",
      "landing",
      "page",
      "proper",
      "ui",
      "code",
      "program",
      "functionalities",
    ].includes(word.toLowerCase()))
    .slice(0, 3);
  if (words.length === 1) words.push("Project");
  const title = words
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ")
    .trim();
  return title || DEFAULT_PROJECT_NAME;
}

function projectSidebarTitle(project = {}) {
  return projectTitleFromPrompt(project.name || DEFAULT_PROJECT_NAME);
}

function projectsForSession(projects = [], session) {
  if (!session?.id) return projects;
  return projects.filter((project) => !project.owner_user_id || project.owner_user_id === session.id);
}

function originalFilePathLabel({ project, browserWorkspace, hasBrowserDirectoryHandle = false, filePath = "" }) {
  if (!filePath) return "";
  if (project?.local_path) return joinLocalPath(project.local_path, filePath);
  if (browserWorkspace?.name) {
    const access = browserWorkspace.kind === "directory" && hasBrowserDirectoryHandle ? "writable" : "not currently writable";
    return `${browserWorkspace.name}/${filePath} (${access} browser folder)`;
  }
  return "";
}

function joinLocalPath(root = "", relativePath = "") {
  const cleanedRoot = String(root || "").replace(/[\\/]+$/, "");
  const cleanedRelative = String(relativePath || "").replace(/^[\\/]+/, "");
  if (!cleanedRoot) return cleanedRelative;
  return `${cleanedRoot}/${cleanedRelative}`;
}

function localWriteBackMessage(sync, files = []) {
  const paths = files
    .map((file) => file?.path)
    .filter(Boolean)
    .slice(0, 6)
    .map((path) => `${sync.name}/${path}`);
  const extra = Math.max((files?.length || 0) - paths.length, 0);
  const pathText = paths.length ? `\n\nLocal files:\n${paths.map((path) => `- ${path}`).join("\n")}${extra ? `\n- +${extra} more` : ""}` : "";
  return `Wrote ${sync.count} files to selected system folder: ${sync.name}${pathText}`;
}

function pathBaseName(path = "") {
  return path.split(/[\\/]/).filter(Boolean).at(-1) || "";
}

createRoot(document.getElementById("root")).render(<App />);
