from pathlib import Path


def test_confirmation_actions_are_passed_into_conversation_panel():
  source = Path("src/main.jsx").read_text(encoding="utf-8")

  assert "onSubmitPrompt={handleChatAction}" in source
  assert "async function handleChatAction" in source
  assert "onSubmitPrompt," in source
  assert "onAction={onSubmitPrompt}" in source
  assert "onAction={submitWebsitePrompt}" not in source


def test_chat_progress_auto_scroll_and_groups_user_facing_setup_summary():
  source = Path("src/main.jsx").read_text(encoding="utf-8")

  assert "chatBottomRef" in source
  assert "scrollIntoView" in source
  assert 'return { key: "intake", label: "Request Setup" };' in source
  assert 'return { key: "context", label: "Code Context" };' in source
  assert 'group.phase === "intake"' in source
  assert 'group.phase === "context"' in source
  assert "Routed request and prepared workspace" in source
  assert '"agent.decision"' in source
  assert '"generate_simple_code_file.input"' in source
  assert '"generate_simple_code_file.output"' in source
  assert '"update.summary"' in source
  assert "progressDecisionNarrative" in source
  assert "decision_reason" in source
  assert "Chief Orchestrator selected" in source


def test_browser_directory_import_keeps_common_root_project_files_and_safe_tree():
  source = Path("src/main.jsx").read_text(encoding="utf-8")

  assert '"index.html"' in source
  assert '"script.js"' in source
  assert '"style.css"' in source
  assert '"package.json"' in source
  assert '"package-lock.json"' in source
  assert '"vite.config.cjs"' in source
  assert '"tailwind.config.cjs"' in source
  assert '"postcss.config.cjs"' in source
  assert '"tsconfig.json"' in source
  assert '"jsconfig.json"' in source
  assert '"components.json"' in source
  assert '"vercel.json"' in source
  assert "IGNORED_BROWSER_FILE_NAMES" in source
  assert "!pathHasIgnoredBrowserDirectory(path)" in source
  assert "!IGNORED_BROWSER_FILE_NAMES.has(fileName)" in source


def test_local_workspace_creation_closes_modal_before_event_refresh():
  source = Path("src/main.jsx").read_text(encoding="utf-8")
  function_body = source.split("async function chooseLocalWorkspaceForNewProject()", 1)[1].split("function closeNewProjectModal()", 1)[0]

  assert "setIsNewProjectModalOpen(false);" in function_body
  assert "await openProject(project" not in function_body
  assert function_body.index("setIsNewProjectModalOpen(false);") < function_body.index("await refreshEvents(project.id);")


def test_browser_directory_import_reports_missing_root_files():
  source = Path("src/main.jsx").read_text(encoding="utf-8")

  assert "requestBrowserProjectSource()" in source
  assert "browserImportSummary(projectSource.name, initialFiles, projectSource.diagnostics" in source
  assert "REQUIRED_BROWSER_PROJECT_ROOT_FILES" in source
  assert "STATIC_BROWSER_PROJECT_ENTRY_FILE" in source
  assert "REQUIRED_BROWSER_PROJECT_SOURCE_PREFIX" in source
  assert "Connected empty system folder" in source
  assert "No project files were imported yet" in source
  assert "hasStaticBrowserProjectEntry(files)" in source
  assert "hasRequiredBrowserSourceFiles(files)" in source
  assert "No root project files were imported." in source
  assert "Backend import dropped root project file(s)" in source
  assert "BINARY_PUBLIC_ASSET_EXTENSIONS" in source
  assert "readBrowserFileContent(uploadedFile, relativePath)" in source
  assert "readBrowserFileContent(file, relativePath)" in source
  assert "browserWritableFileContent(relativePath" in source
  assert 'body: { files: initialFiles }' in source
  assert "ensureBackendProjectForChat" in source


def test_ip_hosted_import_uses_folder_upload_fallback():
  source = Path("src/main.jsx").read_text(encoding="utf-8")

  assert "supportsWritableBrowserDirectoryPicker()" in source
  assert "if (!window.showDirectoryPicker) return false;" in source
  assert "window.isSecureContext" in source
  assert "isLoopbackHost(window.location.hostname)" in source
  assert "return requestUploadedProjectDirectory();" in source
  assert 'input.webkitdirectory = true;' in source
  assert 'input.setAttribute("webkitdirectory", "");' in source
  assert 'input.setAttribute("directory", "");' in source
  assert 'input.setAttribute("mozdirectory", "");' in source
  assert "readUploadedProjectDirectory(input.files || [])" in source
  assert "normalizeUploadedProjectPath(uploadedPath, folderName)" in source
  assert "This folder import is read-only because writable browser folder access is unavailable" in source
  assert "FolderAccessModal" in source
  assert "beginFolderAccessFlow" in source
  assert "Pick a local folder with guided access approval." in source
  assert "Updated backend and preview only. This folder upload is read-only" in source


def test_generation_records_browser_write_back_progress_after_backend_commit():
  source = Path("src/main.jsx").read_text(encoding="utf-8")

  assert "const persistedFiles = payload.files || [];" in source
  assert "const generatedFiles = generatedWriteBackFilesFromPayload(payload);" in source
  assert "applySyncedFiles(persistedFiles, generatedFiles[0]?.path)" in source
  assert "const unsyncedFiles = generatedFiles.filter" in source
  assert "syncGeneratedFilesToBrowserWorkspace(projectId, unsyncedFiles)" in source
  assert "function generatedWriteBackFilesFromPayload(payload)" in source
  assert "payload?.generation?.orchestration_flow?.generated_website?.files" in source
  assert "if (Array.isArray(artifactFiles)) return artifactFiles.filter" in source
  assert "Array.isArray(artifactFiles) && artifactFiles.length" not in source
  assert '"browser.write_back"' in source
  assert '"browser.write_back.completed"' in source
  assert '"browser.write_back.skipped"' in source
  assert "Browser folder write access" in source
  assert "without using a backend static path" in source


def test_settings_and_admin_show_redacted_input_output_token_breakdown():
  source = Path("src/main.jsx").read_text(encoding="utf-8")

  assert "function TokenUsageBreakdown" in source
  assert "Month input" in source
  assert "Month output" in source
  assert "Month thinking" in source
  assert "Month credits" in source
  assert "Month cost" in source
  assert "function CreditUsageCard" in source
  assert "function CreditUsageInline" in source
  assert "1 credit =" in source
  assert "User accounts & AI credits" in source
  assert "monthly_ai_credits" in source
  assert "View details" in source
  assert "Hide details" in source
  assert "Save credits" in source
  assert "Monthly token diagnostics:" in source
  assert "Monthly AI credits are the subscription limit." in source
  assert "request.thought_tokens" in source
  assert "request.estimated_cost_usd" in source
  assert "request.estimated_credits" in source
  assert "request.execution_stages" in source
  assert "function formatUsdCost" in source
  assert "function formatCredits" in source
  assert "formatTokenCountExact(request.input_tokens || 0)" in source
  assert "formatTokenCountExact(request.output_tokens || 0)" in source
  assert "formatTokenCountExact(request.thought_tokens || 0)" in source
  assert "formatTokenCountExact(request.total_tokens || 0)" in source
  assert 'failureDetail.code === "ai_credit_limit_exceeded"' in source
  assert "You have completed your user limit." in source
  assert "Raw user prompts are not shown here." in source
  assert 'TOKEN_USAGE_EXPANDED_REQUEST_LIMIT = 100' in source
  assert '"Show all"' in source
  assert '"Show less"' in source
  assert "max-h-[min(28rem,50vh)] overflow-y-auto" in source
  assert "recent_request_limit=${normalizedLimit}" in source
  assert "<TokenUsageBreakdown usage={usage} onLoadAllRequests={onLoadAllRequests} />" in source
  assert "<TokenUsageBreakdown usage={usage} compact />" in source


def test_generation_stream_disconnect_after_save_recovers_ui_state():
  source = Path("src/main.jsx").read_text(encoding="utf-8")

  assert "GENERATION_STREAM_STALL_TIMEOUT_MS" in source
  assert "readGenerationStreamChunk(reader, signal)" in source
  assert "createGenerationStreamStalledError" in source
  assert "isRecoverableGenerationStreamDisconnect(nextError) && streamHadSavedProgress" in source
  assert '"generation.recovered"' in source
  assert 'group.steps.has("generation.recovered")' in source
  assert "Code changes were saved, but the live update stream disconnected before the final response" in source
  assert "setIsGenerating(false);" in source


def test_hidden_worktual_files_are_filtered_from_ui_progress_and_writeback():
  source = Path("src/main.jsx").read_text(encoding="utf-8")

  assert "function isHiddenProjectFilePath" in source
  assert "function visibleDiffDetail" in source
  assert "group.diffDetail = visibleDiffDetail" in source
  assert "filter((path) => !isHiddenProjectFilePath(path))" in source
  assert "artifactFiles.filter((file) => !isHiddenProjectFilePath" in source


def test_create_skill_sends_project_id_and_uses_backend_saved_project_file():
  source = Path("src/main.jsx").read_text(encoding="utf-8")

  assert "project_id: project?.id || \"\"" in source
  assert "payload.saved_project_file || null" in source
  assert "existingProjectFile = null" in source


def test_model_picker_includes_gemini_35_flash():
  source = Path("src/main.jsx").read_text(encoding="utf-8")

  assert '{ value: "gemini-3.5-flash", label: "Flash" }' in source
  assert "gemini-2.5-flash" not in source


def test_backend_browser_import_reports_imported_paths():
  source = Path("backend/main.py").read_text(encoding="utf-8")

  assert "normalize_project_file_path(file_item.path)" in source
  assert '"local.browser_workspace_ready"' in source
  assert '"direction": "browser_import_ready"' in source
  assert "validate_complete_project_import(" in source
  assert "require_complete=False" in source
  assert 'event_type="local.browser_imported"' in source
  assert '"paths": imported_paths[:100]' in source
  assert '"root_files": root_files' in source
  assert '"paths": imported_paths' in source


def test_new_project_modal_uses_browser_import_without_server_path_input():
  source = Path("src/main.jsx").read_text(encoding="utf-8")
  modal_source = source.split("function NewProjectModal", 1)[1].split("function FolderAccessModal", 1)[0]

  assert "onCreateLocalPath" not in source
  assert "server-local-path" not in source
  assert "Server local path" not in source
  assert "Link a folder under the backend allowed roots for real disk sync." not in source
  assert "Import local project" in source
  assert "Backend workspace" in source
  assert "bg-[#0f0f0f] font-sans" in modal_source
  assert "text-[10px] font-semibold uppercase tracking-wide text-slate-500" in modal_source
  assert "text-base font-semibold text-white" in modal_source
  assert "text-sm font-semibold text-slate-100" in modal_source
  assert "text-xs font-medium leading-relaxed text-slate-400" in modal_source
  assert "text-xl font-black text-ink" not in modal_source
  assert "text-base font-black text-ink" not in modal_source
  assert "min-h-44 rounded-xl border border-line bg-white p-4" not in modal_source


def test_new_project_modal_exposes_local_helper_health_check():
  source = Path("src/main.jsx").read_text(encoding="utf-8")
  styles = Path("src/styles.css").read_text(encoding="utf-8")
  folder_modal = source.split("function FolderAccessModal", 1)[1].split("function buildMemoryEpisodesUrl", 1)[0]

  assert "Check Local Helper" in source
  assert 'fetchLocalSkillsHelper("/health")' in source
  assert "localSkillsHelperCommand()" in source
  assert "setLocalHelperCheck({" in source
  assert "helperCheck" in source
  assert 'operation: "check_local_helper"' in source
  assert "customer/user terminal" in source
  assert "wt-hidden-scrollbar max-h-[calc(100vh-4rem)]" in folder_modal
  assert "bg-[#0f0f0f] font-sans" in folder_modal
  assert "text-base font-semibold text-white" in folder_modal
  assert "text-xs font-medium leading-relaxed text-slate-400" in folder_modal
  assert "bg-white px-3 py-2 text-xs font-semibold text-black" in folder_modal
  assert "bg-worktual-700 px-4 py-2 text-sm font-black text-white" not in folder_modal
  assert ".wt-hidden-scrollbar" in styles
  assert "-ms-overflow-style: none;" in styles
  assert "This customer machine can reach the local helper" in source


def test_gate_failure_cards_are_rendered_in_chat_progress():
  source = Path("src/main.jsx").read_text(encoding="utf-8")

  assert "function GateFailureCard" in source
  assert "function buildGateFailureDetail" in source
  assert 'return { key: "gate-failure", label: "Validation Failed" };' in source
  assert "group.gateFailureDetail" in source
  assert "gate.visual_qa.failed" in source
  assert "Build verification failed" in source
  assert "Visual QA failed" in source


def test_user_settings_modal_exposes_memory_preferences_tab():
  source = Path("src/main.jsx").read_text(encoding="utf-8")
  modal_source = source.split("function UserSettingsModal", 1)[1].split("function MemoryPreferencesPanel", 1)[0]

  assert "Memory preferences" in source
  assert "Session memory" in source
  assert "Close settings" in source
  assert "bg-[#202020] text-white ring-1 ring-white/15" in modal_source
  assert "bg-worktual-700 text-white" not in modal_source
  assert "max-h-[calc(100vh-3rem)]" in source
  assert "min-h-0 flex-1 overflow-y-auto" in source
  assert "function MemoryPreferencesPanel" in source
  assert "function SessionMemoryPanel" in source
  assert "/api/users/me/memory/preferences" in source
  assert "/api/users/me/memory/episodes" in source
  assert "injected_into_agent_context" in source


def test_user_settings_profile_tab_uses_modal_local_saving_state():
  source = Path("src/main.jsx").read_text(encoding="utf-8")
  modal_source = source.split("function UserSettingsModal", 1)[1].split("function MemoryPreferencesPanel", 1)[0]

  assert "const [isSavingProfile, setIsSavingProfile] = useState(false);" in modal_source
  assert "const [profileSaveError, setProfileSaveError] = useState(\"\");" in modal_source
  assert "setProfileSaveError(error?.message || \"Could not save profile changes.\");" in modal_source
  assert "disabled={isSavingProfile || passwordMismatch}" in modal_source
  assert "disabled={isLoading}" not in modal_source
  assert "disabled={isLoading || passwordMismatch}" not in modal_source


def test_frontend_dependency_failure_runs_customer_local_install_and_retry():
  source = Path("src/main.jsx").read_text(encoding="utf-8")

  assert "isDependencyFailureLog" in source
  assert 'fetchLocalSkillsHelper("/run-action"' in source
  assert 'action: "frontend_install_and_build"' in source
  assert "allowOkFalse: true" in source
  assert "repairLocalDependenciesForPreview" in source
  assert "localHelperWorkspacePathStorageKey" in source
  assert 'operation: "local_dependency_repair"' in source


def test_browser_directory_connection_restores_after_refresh_without_reselecting_folder():
  source = Path("src/main.jsx").read_text(encoding="utf-8")

  assert "pendingBrowserDirectoryHandlesRef" in source
  assert "restoreStoredBrowserDirectoryConnection(activeProject)" in source
  assert 'directoryHandle.queryPermission({ mode: "readwrite" })' in source
  assert '.requestPermission({ mode: "readwrite" })' in source
  assert 'window.addEventListener("pointerdown", requestPermissionFromUserGesture, true)' in source
  assert "activateBrowserDirectoryHandle" in source
  assert "loadStoredBrowserDirectoryHandle(project.id)" in source
  assert "window.navigator.storage.persist()" in source


def test_realtime_workflow_save_waits_for_verify_and_uses_neutral_completion_style():
  source = Path("src/main.jsx").read_text(encoding="utf-8")
  workflow_source = source.split("const WORKFLOW_PHASE_DEFINITIONS", 1)[1].split("function PromptComposer", 1)[0]
  workflow_component = source.split("function WorkflowPhaseConversationCard", 1)[1].split("function ConversationPanel", 1)[0]

  assert '"files.persisted"' in workflow_source
  assert '"browser.write_back.completed"' in workflow_source
  assert 'patterns: ["persist", "sync", "write_back"' not in workflow_source
  assert "previousPhasesCompleted" in workflow_source
  assert 'latestPhaseId !== "save"' in workflow_source
  assert 'phase.id !== "verify"' in workflow_source
  assert "workflowStatusText" in workflow_source
  assert "Realtime workflow" not in workflow_component
  assert "Workflow status" not in workflow_component
  assert "phases.map((phase)" not in workflow_component
  assert "wt-soft-card w-full max-w-[86%] rounded-xl" not in workflow_component
  assert "grid grid-cols-[18px_minmax(0,1fr)]" not in workflow_component
  assert '? "border-emerald-400/20 bg-emerald-500/10"' not in workflow_source


def test_generation_progress_timeline_uses_compact_left_gap():
  source = Path("src/main.jsx").read_text(encoding="utf-8")
  progress_source = source.split("function AgentProgressStream", 1)[1].split("function ProgressNarrativeItem", 1)[0]

  assert "wt-run-timeline ml-2 grid gap-3 pl-3" in progress_source
  assert "wt-run-timeline ml-4 grid gap-3 pl-4" not in progress_source
  assert "ThinkingProgressLine label={timing.label}" in progress_source
  assert "<WorkflowPhaseConversationCard" not in progress_source
  assert "<ThinkingWave" not in progress_source
  assert "Thinking for ${durationLabel}" in source
  assert "Working for ${durationLabel}" not in source


def test_workspace_theme_uses_neutral_black_white_editor_palette():
  theme = Path("src/theme.css").read_text(encoding="utf-8")
  styles = Path("src/styles.css").read_text(encoding="utf-8")

  assert "--wt-black: #050505;" in theme
  assert "--wt-panel: #090909;" in theme
  assert "--wt-text: #f5f5f5;" in theme
  assert "--wt-accent-bright: #ffffff;" in theme
  assert ".bg-worktual-700," in styles
  assert "background-color: #171717 !important;" in styles
  assert ".bg-white.text-black" in styles
  assert "color: #050505 !important;" in styles
  assert ".wt-action-primary" in styles
  assert ".wt-action-secondary" in styles
  assert "radial-gradient" not in styles
  assert "#7c3aed" not in styles
  assert "#4f46e5" not in styles
  assert ".bg-white\\/30" in styles


def test_workspace_uses_inter_and_separates_username_from_password():
  source = Path("src/main.jsx").read_text(encoding="utf-8")
  styles = Path("src/styles.css").read_text(encoding="utf-8")
  admin_source = source.split("function AdminUsersPanel", 1)[1].split("function AdminUserLimitCard", 1)[0]

  assert Path("public/assets/inter-latin-variable.woff2").is_file()
  assert 'url("/assets/inter-latin-variable.woff2") format("woff2")' in styles
  assert "font-family: Inter, ui-sans-serif" in styles
  assert 'name="new-account-username"' in admin_source
  assert 'name="new-account-password"' in admin_source
  assert 'autoComplete="new-password"' in admin_source
  assert 'setError("Username cannot be the same as the password.");' in admin_source
  assert 'bg-[#161616]' in admin_source
  assert "text-xs font-semibold text-slate-200" in admin_source
  assert "bg-worktual-700 px-4 py-2 text-sm font-black text-white" not in admin_source


def test_company_logo_replaces_header_bot_and_workspace_star():
  source = Path("src/main.jsx").read_text(encoding="utf-8")
  styles = Path("src/styles.css").read_text(encoding="utf-8")
  header_source = source.split("function Header", 1)[1].split("function AuthScreen", 1)[0]
  workspace_header = source.split('<section className="wt-chat-panel', 1)[1].split("<ChatHistory", 1)[0]

  assert Path("public/assets/worktual-logo.png").is_file()
  assert "min-height: 45px;" in styles
  assert 'src="/assets/worktual-logo.png"' in header_source
  assert 'alt="Worktual"' in header_source
  assert "size-8 shrink-0" in header_source
  assert "Worktual Open Head" in header_source
  assert "truncate text-lg font-black leading-tight text-ink" in header_source
  assert "Agent Command Center" not in header_source
  assert "Builder workspace" not in header_source
  assert "<Bot" not in header_source
  assert "<Sparkles size={17} />" not in workspace_header


def test_readable_typography_and_plain_chat_messages_hide_sender_labels():
  source = Path("src/main.jsx").read_text(encoding="utf-8")
  styles = Path("src/styles.css").read_text(encoding="utf-8")
  tailwind = Path("tailwind.config.js").read_text(encoding="utf-8")
  chat_bubble = source.split("function ChatBubble", 1)[1].split("function InlineStatus", 1)[0]

  assert 'xs: ["10px"' in tailwind
  assert 'sm: ["12px"' in tailwind
  assert 'base: ["14px"' in tailwind
  assert "font-size: 10px;" in styles
  assert "font-size: 11px;" in styles
  assert "fontSize: 9.5" in source
  assert '"You"' not in chat_bubble
  assert '"Vibe AI"' not in chat_bubble
  assert "px-1 py-0.5 text-sm leading-relaxed" in chat_bubble
  assert "wt-soft-card text-slate-700" not in chat_bubble
  assert "border border-cyan-300/20 bg-ink" not in chat_bubble
  assert "rounded-2xl p-3" not in chat_bubble
  assert "rounded-xl px-4 py-3 text-xs leading-relaxed" in source


def test_prompt_composer_uses_one_contextual_action_and_compact_model_labels():
  source = Path("src/main.jsx").read_text(encoding="utf-8")
  options_source = source.split("const MODEL_OPTIONS", 1)[1].split("];", 1)[0]
  conversation_source = source.split("function ConversationPanel", 1)[1].split("function FloatingPanel", 1)[0]

  assert 'label: "Default"' in options_source
  assert 'label: "Flash"' in options_source
  assert 'label: "Pro"' in options_source
  assert "const hasPromptContent = Boolean(trimmedPrompt || promptAttachments.length);" in conversation_source
  assert "function handlePromptAction()" in conversation_source
  assert "onClick={handlePromptAction}" in conversation_source
  assert ": hasPromptContent ? (" in conversation_source
  assert "<Send size={17} />" in conversation_source
  assert "<Mic size={17} />" in conversation_source
  assert conversation_source.index('aria-label="Model"') < conversation_source.index("onClick={handlePromptAction}")
  assert "wt-model-select h-8" in conversation_source
  assert "grid min-h-[50px]" in conversation_source
  assert "items-end" in conversation_source
  assert "row-start-2 mb-0.5" in conversation_source
  assert "border-0 bg-transparent" in conversation_source
  assert "wt-control-button h-9" not in conversation_source


def test_compact_single_row_prompt_and_project_only_sidebar():
  source = Path("src/main.jsx").read_text(encoding="utf-8")
  styles = Path("src/styles.css").read_text(encoding="utf-8")
  project_history = source.split("function ProjectHistory", 1)[1].split("function NewProjectModal", 1)[0]
  project_titles = source.split("function projectTitleFromPrompt", 1)[1].split("function projectsForSession", 1)[0]

  assert "const CHAT_INPUT_MIN_HEIGHT = 24;" in source
  assert "const CHAT_INPUT_MAX_HEIGHT = 132;" in source
  assert 'input.style.overflowY = "hidden";' in source
  assert "grid-cols-[40px_minmax(0,1fr)_auto]" in source
  assert "scrollbar-width: none;" in styles
  assert ".wt-prompt-input::-webkit-scrollbar" in styles
  assert ".wt-chat-scroll::-webkit-scrollbar" in styles
  assert "#root *::-webkit-scrollbar" in styles
  assert "-ms-overflow-style: none;" in styles
  assert "Minimize project panel" in project_history
  assert "Workspace</span>" not in project_history
  assert "<span className=\"truncate\">Create</span>" in project_history
  assert "<span className=\"truncate\">Search</span>" in project_history
  assert "text-[10.5px] font-semibold" in project_history
  assert "#{index + 1}" not in project_history
  assert "formatDate(project.updated_at)" not in project_history
  assert "projectWorkspaceLabel" not in project_history
  assert "{projectSidebarTitle(project)}" in project_history
  assert "function projectSidebarTitle(project = {})" in source
  assert ".slice(0, 3)" in project_titles


def test_workspace_header_username_and_code_actions_are_minimal():
  source = Path("src/main.jsx").read_text(encoding="utf-8")
  header_source = source.split("function Header", 1)[1].split("function AuthScreen", 1)[0]
  conversation_source = source.split("function ConversationPanel", 1)[1].split("function FloatingPanel", 1)[0]
  code_header = source.split("function CodeWorkspace", 1)[1].split("function WorkspaceNavButton", 1)[0]

  assert "Active workspace" not in conversation_source
  assert "Chat, plan, patch, validate" not in conversation_source
  assert "Last preview" not in conversation_source
  assert "const displayLabel" not in header_source
  assert "UserCircle" not in header_source
  assert 'label="Account settings"' in header_source
  assert 'title={session?.email || ""}' not in header_source
  assert 'aria-label="Download code"' in code_header
  assert 'aria-label="Preview"' in code_header
  assert "{isDownloadingProject ? \"Downloading...\" : \"Download\"}" not in code_header
  assert "{isGenerating ? \"Updating\" : \"Preview\"}" not in code_header
  assert "size-7 items-center justify-center rounded-md" in code_header
  assert "<Save size={12} />" in code_header
  assert "<Archive size={11} />" in code_header
  assert "<ExternalLink size={11} />" in code_header
  assert "tiny label=\"Save file\"" in code_header
  assert "size-9 items-center justify-center rounded-md" not in code_header


def test_right_workspace_panel_uses_cursor_like_compact_navigation():
  source = Path("src/main.jsx").read_text(encoding="utf-8")
  code_workspace = source.split("function CodeWorkspace", 1)[1].split("function WorkspaceNavButton", 1)[0]
  workspace_nav = source.split("function WorkspaceNavButton", 1)[1].split("function ChatBubble", 1)[0]

  assert "workspaceContextName" in code_workspace
  assert "On {workspaceContextName}" in code_workspace
  assert "Builder workspace" not in code_workspace
  assert 'text-[11px] font-semibold text-ink' in code_workspace
  assert 'text-[9.5px] font-medium text-slate-500' in code_workspace
  assert "<WorkspaceNavButton" in code_workspace
  assert "wt-workspace-tab" not in code_workspace
  assert "bg-panel p-4" in code_workspace
  assert "grid min-h-10 grid-cols-[16px_16px_minmax(0,1fr)]" in code_workspace
  assert "text-[10px] font-medium" in code_workspace
  assert "function WorkspaceNavButton" in source
  assert "group flex min-h-8 items-center gap-2 rounded-md" in workspace_nav
