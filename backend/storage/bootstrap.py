from __future__ import annotations


BOOTSTRAP_STATEMENTS = [
      """
      create table if not exists users (
        id text primary key,
        email text not null unique,
        role text not null check (role in ('admin','owner','editor','viewer')),
        display_name text not null default '',
        password_hash text,
        created_at timestamptz not null default now()
      )
      """,
      "alter table users add column if not exists display_name text not null default ''",
      "alter table users add column if not exists password_hash text",
      "alter table users add column if not exists is_active boolean not null default true",
      "alter table users add column if not exists created_by_admin_id text references users(id) on delete set null",
      """
      create table if not exists user_usage_limits (
        user_id text primary key references users(id) on delete cascade,
        daily_token_limit integer not null default 500000,
        weekly_token_limit integer not null default 3000000,
        monthly_token_limit integer not null default 12000000,
        daily_tokens_used integer not null default 0,
        weekly_tokens_used integer not null default 0,
        monthly_tokens_used integer not null default 0,
        daily_period_start timestamptz not null default date_trunc('day', now()),
        weekly_period_start timestamptz not null default date_trunc('week', now()),
        monthly_period_start timestamptz not null default date_trunc('month', now()),
        updated_at timestamptz not null default now()
      )
      """,
      """
      create table if not exists projects (
        id text primary key,
        owner_user_id text not null references users(id),
        name text not null,
        description text not null default '',
        created_at timestamptz not null default now(),
        updated_at timestamptz not null default now()
      )
      """,
      "alter table projects add column if not exists local_path text",
      """
      create table if not exists user_token_usage_events (
        id text primary key,
        user_id text not null references users(id) on delete cascade,
        project_id text references projects(id) on delete set null,
        request_id text not null default '',
        generation_run_id text not null default '',
        agent_run_id text not null default '',
        provider text not null default 'gemini',
        model text not null default '',
        call_label text not null default '',
        input_tokens integer not null default 0,
        output_tokens integer not null default 0,
        total_tokens integer not null default 0,
	        thought_tokens integer not null default 0,
	        cached_tokens integer not null default 0,
	        cached_input_tokens integer not null default 0,
	        prompt_chars integer not null default 0,
	        output_chars integer not null default 0,
	        estimated_cost_usd numeric(12,6) not null default 0,
	        estimated_credits numeric(12,4) not null default 0,
	        pricing_version text not null default '',
	        route text not null default '',
	        execution_stage text not null default '',
	        model_role text not null default '',
	        thinking_level text not null default '',
	        context_chars integer not null default 0,
	        duration_ms double precision,
	        metadata_json jsonb not null default '{}'::jsonb,
	        created_at timestamptz not null default now()
	      )
	      """,
	      "alter table user_token_usage_events add column if not exists cached_input_tokens integer not null default 0",
	      "alter table user_token_usage_events add column if not exists estimated_cost_usd numeric(12,6) not null default 0",
	      "alter table user_token_usage_events add column if not exists estimated_credits numeric(12,4) not null default 0",
	      "alter table user_token_usage_events add column if not exists pricing_version text not null default ''",
	      "alter table user_token_usage_events add column if not exists route text not null default ''",
	      "alter table user_token_usage_events add column if not exists execution_stage text not null default ''",
	      "alter table user_token_usage_events add column if not exists model_role text not null default ''",
	      "alter table user_token_usage_events add column if not exists thinking_level text not null default ''",
	      "alter table user_token_usage_events add column if not exists context_chars integer not null default 0",
      "create index if not exists idx_user_token_usage_events_user_created on user_token_usage_events (user_id, created_at desc)",
      "create index if not exists idx_user_token_usage_events_request on user_token_usage_events (request_id)",
      """
      create table if not exists user_ai_credit_accounts (
        user_id text primary key references users(id) on delete cascade,
        included_monthly_credits numeric(12,4) not null default 1000,
        used_credits numeric(12,4) not null default 0,
        reserved_credits numeric(12,4) not null default 0,
        overage_enabled boolean not null default false,
        overage_usd_cap numeric(12,2) not null default 0,
        pricing_version text not null default '',
        current_period_start timestamptz not null default date_trunc('month', now()),
        current_period_end timestamptz not null default date_trunc('month', now()) + interval '1 month',
        updated_at timestamptz not null default now()
      )
      """,
      "alter table user_ai_credit_accounts add column if not exists included_monthly_credits numeric(12,4) not null default 1000",
      "alter table user_ai_credit_accounts alter column included_monthly_credits set default 1000",
      "alter table user_ai_credit_accounts add column if not exists used_credits numeric(12,4) not null default 0",
      "alter table user_ai_credit_accounts add column if not exists reserved_credits numeric(12,4) not null default 0",
      "alter table user_ai_credit_accounts add column if not exists overage_enabled boolean not null default false",
      "alter table user_ai_credit_accounts add column if not exists overage_usd_cap numeric(12,2) not null default 0",
      "alter table user_ai_credit_accounts add column if not exists pricing_version text not null default ''",
      "alter table user_ai_credit_accounts add column if not exists current_period_start timestamptz not null default date_trunc('month', now())",
      "alter table user_ai_credit_accounts add column if not exists current_period_end timestamptz not null default date_trunc('month', now()) + interval '1 month'",
      "alter table user_ai_credit_accounts add column if not exists updated_at timestamptz not null default now()",
      """
      create table if not exists ai_credit_reservations (
        id text primary key,
        user_id text not null references users(id) on delete cascade,
        project_id text references projects(id) on delete set null,
        request_id text not null default '',
        route text not null default '',
        status text not null default 'reserved',
        estimated_credits numeric(12,4) not null default 0,
        actual_credits numeric(12,4) not null default 0,
        pricing_version text not null default '',
        metadata_json jsonb not null default '{}'::jsonb,
        created_at timestamptz not null default now(),
        updated_at timestamptz not null default now(),
        completed_at timestamptz
      )
      """,
      "create index if not exists idx_ai_credit_reservations_user_created on ai_credit_reservations (user_id, created_at desc)",
      "create index if not exists idx_ai_credit_reservations_request on ai_credit_reservations (request_id)",
      """
      create table if not exists project_files (
        project_id text not null references projects(id) on delete cascade,
        path text not null,
        content text not null,
        updated_at timestamptz not null default now(),
        primary key (project_id, path)
      )
      """,
      """
      create table if not exists project_versions (
        id text primary key,
        project_id text not null references projects(id) on delete cascade,
        status text not null,
        preview_url text,
        build_log text not null default '',
        created_at timestamptz not null default now()
      )
      """,
      """
      create table if not exists project_version_files (
        version_id text not null references project_versions(id) on delete cascade,
        path text not null,
        content text not null,
        primary key (version_id, path)
      )
      """,
      """
      create table if not exists generation_runs (
        id text primary key,
        project_id text not null references projects(id) on delete cascade,
        user_id text not null references users(id),
        prompt text not null,
        provider text not null,
        status text not null,
        response_json jsonb,
        error text,
        created_at timestamptz not null default now()
      )
      """,
      """
      create table if not exists project_chat_messages (
        id text primary key,
        project_id text not null references projects(id) on delete cascade,
        user_id text not null references users(id),
        role text not null check (role in ('user','model')),
        content text not null default '',
        metadata_json jsonb not null default '{}'::jsonb,
        created_at timestamptz not null default now()
      )
      """,
      "alter table project_chat_messages add column if not exists chat_session_id text",
      """
      create table if not exists project_chat_sessions (
        id text primary key,
        project_id text not null references projects(id) on delete cascade,
        user_id text not null references users(id),
        title text not null default '',
        status text not null default 'active' check (status in ('active', 'closed')),
        created_at timestamptz not null default now(),
        updated_at timestamptz not null default now()
      )
      """,
      """
      do $$
      begin
        if not exists (
          select 1 from pg_constraint where conname = 'project_chat_messages_chat_session_id_fkey'
        ) then
          alter table project_chat_messages
            add constraint project_chat_messages_chat_session_id_fkey
            foreign key (chat_session_id) references project_chat_sessions(id) on delete cascade;
        end if;
      end $$;
      """,
      """
      create table if not exists agent_runs (
        id text primary key,
        project_id text not null references projects(id) on delete cascade,
        generation_run_id text references generation_runs(id) on delete set null,
        user_id text not null references users(id),
        runtime text not null,
        provider text not null,
        model text,
        status text not null,
        input_json jsonb not null default '{}'::jsonb,
        output_json jsonb,
        error text,
        started_at timestamptz not null default now(),
        completed_at timestamptz
      )
      """,
      """
      create table if not exists automation_test_runs (
        id text primary key,
        project_id text not null references projects(id) on delete cascade,
        user_id text not null references users(id),
        chat_session_id text references project_chat_sessions(id) on delete set null,
        generation_run_id text references generation_runs(id) on delete set null,
        agent_run_id text references agent_runs(id) on delete set null,
        project_version_id text references project_versions(id) on delete set null,
        operation text not null check (operation in ('generation', 'update')),
        scope text not null check (scope in ('full', 'targeted')),
        status text not null,
        changed_paths_json jsonb not null default '[]'::jsonb,
        affected_routes_json jsonb not null default '[]'::jsonb,
        test_scope_json jsonb not null default '{}'::jsonb,
        results_json jsonb not null default '{}'::jsonb,
        summary text not null default '',
        started_at timestamptz not null default now(),
        completed_at timestamptz
      )
      """,
      """
      create table if not exists screenshot_artifacts (
        id text primary key,
        test_run_id text not null references automation_test_runs(id) on delete cascade,
        project_id text not null references projects(id) on delete cascade,
        user_id text not null references users(id),
        chat_session_id text references project_chat_sessions(id) on delete set null,
        project_version_id text references project_versions(id) on delete set null,
        source_artifact_id text references screenshot_artifacts(id) on delete set null,
        phase text not null check (phase in ('before', 'after', 'diff', 'baseline')),
        route text not null default '/',
        viewport_name text not null,
        width integer not null,
        height integer not null,
        storage_path text not null,
        mime_type text not null default 'image/png',
        sha256 text not null,
        size_bytes bigint not null default 0,
        is_baseline boolean not null default false,
        metadata_json jsonb not null default '{}'::jsonb,
        created_at timestamptz not null default now()
      )
      """,
      """
      create table if not exists visual_comparisons (
        id text primary key,
        test_run_id text not null references automation_test_runs(id) on delete cascade,
        project_id text not null references projects(id) on delete cascade,
        before_artifact_id text references screenshot_artifacts(id) on delete set null,
        after_artifact_id text not null references screenshot_artifacts(id) on delete cascade,
        diff_artifact_id text references screenshot_artifacts(id) on delete set null,
        route text not null default '/',
        viewport_name text not null,
        status text not null,
        changed boolean not null default false,
        difference_ratio double precision,
        threshold double precision,
        changed_regions_json jsonb not null default '[]'::jsonb,
        layout_issues_json jsonb not null default '[]'::jsonb,
        metadata_json jsonb not null default '{}'::jsonb,
        created_at timestamptz not null default now()
      )
      """,
      """
      create table if not exists agent_messages (
        id text primary key,
        agent_run_id text not null references agent_runs(id) on delete cascade,
        project_id text not null references projects(id) on delete cascade,
        user_id text not null references users(id),
        from_agent text not null,
        to_agent text,
        role text not null,
        content text not null default '',
        payload_json jsonb not null default '{}'::jsonb,
        status text not null default 'completed',
        created_at timestamptz not null default now()
      )
      """,
      """
      create table if not exists tool_calls (
        id text primary key,
        agent_run_id text not null references agent_runs(id) on delete cascade,
        project_id text not null references projects(id) on delete cascade,
        user_id text not null references users(id),
        call_id text not null,
        tool_name text not null,
        status text not null,
        arguments_json jsonb not null default '{}'::jsonb,
        result_json jsonb,
        error text,
        started_at timestamptz not null default now(),
        completed_at timestamptz
      )
      """,
      """
      create table if not exists memory_items (
        id text primary key,
        project_id text references projects(id) on delete cascade,
        user_id text not null references users(id),
        namespace text not null,
        key text not null,
        kind text not null,
        content text not null,
        metadata_json jsonb not null default '{}'::jsonb,
        created_at timestamptz not null default now(),
        updated_at timestamptz not null default now(),
        unique (project_id, user_id, namespace, key)
      )
      """,
      """
      create table if not exists dynamic_agent_definitions (
        id text primary key,
        owner_user_id text not null references users(id) on delete cascade,
        agent_key text not null,
        version integer not null default 1,
        lifecycle text not null,
        definition_json jsonb not null default '{}'::jsonb,
        metrics_json jsonb not null default '{}'::jsonb,
        created_at timestamptz not null default now(),
        updated_at timestamptz not null default now(),
        unique (owner_user_id, agent_key)
      )
      """,
      """
      create table if not exists generation_checkpoints (
        id text primary key,
        agent_run_id text not null references agent_runs(id) on delete cascade,
        project_id text not null references projects(id) on delete cascade,
        user_id text not null references users(id),
        thread_id text not null,
        step_name text not null,
        state_json jsonb not null default '{}'::jsonb,
        created_at timestamptz not null default now()
      )
      """,
      """
      create table if not exists events (
        id text primary key,
        project_id text references projects(id) on delete cascade,
        user_id text references users(id),
        type text not null,
        payload_json jsonb not null default '{}'::jsonb,
        created_at timestamptz not null default now()
      )
      """,
      "create index if not exists idx_events_project_created on events(project_id, created_at desc)",
      "create index if not exists idx_chat_sessions_project_user on project_chat_sessions(project_id, user_id, updated_at desc)",
      "create index if not exists idx_chat_messages_session_created on project_chat_messages(chat_session_id, created_at)",
      "create index if not exists idx_files_project_path on project_files(project_id, path)",
      "create index if not exists idx_agent_runs_project_started on agent_runs(project_id, started_at desc)",
      "create index if not exists idx_project_chat_project_created on project_chat_messages(project_id, user_id, created_at)",
      "create index if not exists idx_agent_messages_run_created on agent_messages(agent_run_id, created_at)",
      "create index if not exists idx_tool_calls_run_started on tool_calls(agent_run_id, started_at)",
      "create index if not exists idx_automation_test_runs_project_session on automation_test_runs(project_id, chat_session_id, started_at desc)",
      "create index if not exists idx_screenshot_artifacts_project_session on screenshot_artifacts(project_id, chat_session_id, created_at desc)",
      "create index if not exists idx_screenshot_artifacts_baseline on screenshot_artifacts(project_id, route, viewport_name, created_at desc) where is_baseline = true",
      "create index if not exists idx_visual_comparisons_test_run on visual_comparisons(test_run_id, created_at)",
      "create index if not exists idx_memory_items_project_namespace on memory_items(project_id, user_id, namespace)",
      "create index if not exists idx_dynamic_agents_owner_lifecycle on dynamic_agent_definitions(owner_user_id, lifecycle, updated_at desc)",
      "create index if not exists idx_generation_checkpoints_thread on generation_checkpoints(thread_id, created_at desc)",
      """
      create table if not exists memory_user_profiles (
        id text primary key,
        user_id text not null references users(id) on delete cascade,
        project_id text not null default '',
        profile_json jsonb not null default '{}'::jsonb,
        framework text not null default '',
        domain text not null default '',
        created_at timestamptz not null default now(),
        updated_at timestamptz not null default now(),
        unique (user_id, project_id)
      )
      """,
      """
      create table if not exists memory_user_preferences (
        id text primary key,
        user_id text not null references users(id) on delete cascade,
        category text not null,
        preference text not null,
        polarity text not null default 'positive',
        confidence numeric(4,3) not null default 0.800,
        durability text not null default 'long_term',
        reason text not null default '',
        metadata_json jsonb not null default '{}'::jsonb,
        created_at timestamptz not null default now(),
        updated_at timestamptz not null default now(),
        unique (user_id, category, preference)
      )
      """,
      """
      create table if not exists memory_episodes (
        id text primary key,
        user_id text not null references users(id) on delete cascade,
        project_id text not null references projects(id) on delete cascade,
        chat_session_id text references project_chat_sessions(id) on delete set null,
        generation_run_id text references generation_runs(id) on delete set null,
        scope text not null default 'personal' check (scope in ('personal', 'shared')),
        memory_type text not null default 'update_checkpoint',
        title text not null default '',
        searchable_summary text not null default '',
        situation text not null default '',
        stack_tags text not null default '',
        module_tags text not null default '',
        improved_behavior text not null default '',
        avoid text not null default '',
        outcome text not null default 'completed',
        changed_paths_json jsonb not null default '[]'::jsonb,
        metadata_json jsonb not null default '{}'::jsonb,
        created_at timestamptz not null default now(),
        updated_at timestamptz not null default now()
      )
      """,
      """
      create table if not exists memory_session_snapshots (
        id text primary key,
        project_id text not null references projects(id) on delete cascade,
        user_id text not null references users(id) on delete cascade,
        chat_session_id text not null references project_chat_sessions(id) on delete cascade,
        generation_run_id text references generation_runs(id) on delete set null,
        snapshot_kind text not null default 'update_checkpoint',
        content text not null default '',
        changed_paths_json jsonb not null default '[]'::jsonb,
        file_manifest_json jsonb not null default '{}'::jsonb,
        preview_status text,
        error_category text,
        metadata_json jsonb not null default '{}'::jsonb,
        created_at timestamptz not null default now()
      )
      """,
      """
      create table if not exists memory_chat_session_state (
        chat_session_id text primary key references project_chat_sessions(id) on delete cascade,
        project_id text not null references projects(id) on delete cascade,
        user_id text not null references users(id) on delete cascade,
        rolling_summary text not null default '',
        last_changed_paths_json jsonb not null default '[]'::jsonb,
        last_preview_status text,
        last_error_category text,
        file_count integer not null default 0,
        update_count integer not null default 0,
        last_generation_run_id text references generation_runs(id) on delete set null,
        metadata_json jsonb not null default '{}'::jsonb,
        created_at timestamptz not null default now(),
        updated_at timestamptz not null default now()
      )
      """,
      """
      create table if not exists memory_learning_events (
        id text primary key,
        user_id text not null references users(id) on delete cascade,
        project_id text references projects(id) on delete cascade,
        chat_session_id text references project_chat_sessions(id) on delete set null,
        run_id text not null default '',
        request_text_hash text not null default '',
        normalized_intent text not null default '',
        domain text not null default 'general',
        task_type text not null default 'general',
        changed_paths_json jsonb not null default '[]'::jsonb,
        validation_status text not null default '',
        mistake_type text not null default '',
        extracted_lesson text not null default '',
        scope text not null default 'personal',
        confidence numeric(4,3) not null default 0.600,
        metadata_json jsonb not null default '{}'::jsonb,
        created_at timestamptz not null default now()
      )
      """,
      """
      create table if not exists memory_platform_patterns (
        id text primary key,
        pattern_key text not null unique,
        domain text not null default 'general',
        module text not null default 'general',
        pattern_type text not null default 'general',
        memory_type text not null default 'fix_pattern',
        title text not null default '',
        summary text not null default '',
        situation text not null default '',
        improved_behavior text not null default '',
        avoid text not null default '',
        stack_tags text not null default '',
        source_count integer not null default 1,
        confidence_score numeric(4,3) not null default 0.600,
        metadata_json jsonb not null default '{}'::jsonb,
        first_seen_at timestamptz not null default now(),
        last_seen_at timestamptz not null default now(),
        updated_at timestamptz not null default now()
      )
      """,
      """
      create table if not exists memory_platform_pattern_events (
        id text primary key,
        pattern_id text not null references memory_platform_patterns(id) on delete cascade,
        domain text not null default 'general',
        module text not null default 'general',
        pattern_type text not null default 'general',
        outcome text not null default 'observed',
        created_at timestamptz not null default now()
      )
      """,
      "create index if not exists idx_memory_episodes_project_session on memory_episodes(project_id, chat_session_id, created_at desc)",
      "create index if not exists idx_memory_episodes_scope_module on memory_episodes(scope, module_tags, created_at desc)",
      "create index if not exists idx_memory_session_snapshots_session on memory_session_snapshots(chat_session_id, created_at desc)",
      "create index if not exists idx_memory_learning_events_user_created on memory_learning_events(user_id, created_at desc)",
      "create index if not exists idx_memory_learning_events_project_run on memory_learning_events(project_id, run_id)",
      "create index if not exists idx_memory_learning_events_domain_task on memory_learning_events(domain, task_type, created_at desc)",
      """
      create unique index if not exists idx_memory_learning_events_unique_run
      on memory_learning_events(user_id, project_id, run_id)
      where run_id <> ''
      """,
      "create index if not exists idx_memory_platform_patterns_domain_module on memory_platform_patterns(domain, module, pattern_type)",
      "create index if not exists idx_memory_user_preferences_user on memory_user_preferences(user_id, updated_at desc)",
      """
      create unique index if not exists idx_memory_episodes_session_run
      on memory_episodes (chat_session_id, generation_run_id)
      where chat_session_id is not null and generation_run_id is not null
      """,
    ]
