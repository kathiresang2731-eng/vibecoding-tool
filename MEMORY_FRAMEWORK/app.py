import html
import json
import uuid

import streamlit as st

from src.extraction import extract_all_memories
from src.meili_client import ensure_indexes_ready
from src.response import ChatRequest, generate_response
from src.retriever import (
    get_user_preferences,
    get_user_profile,
    retrieve_episodes,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Memory Testbed · Vibe Coding",
    page_icon="🧠",
    layout="wide",
)

try:
    ensure_indexes_ready()
except Exception as e:
    st.error(
        f"Meilisearch not ready: {e}. "
        "Start it with: `MEILI_MASTER_KEY=jayesh ./meilisearch --db-path ./data.ms`"
    )
    st.stop()

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Sora:wght@300;400;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Sora', sans-serif; }
.stApp { background-color: #0d0f14; color: #e2e8f0; }
#MainMenu, footer, header { visibility: hidden; }
.app-title { font-size: 1.5rem; font-weight: 700; color: #f8fafc; }
.app-subtitle { font-size: 0.75rem; color: #64748b; letter-spacing: 2px; text-transform: uppercase; }
.meta-bar { font-family: 'JetBrains Mono', monospace; font-size: 0.65rem; color: #475569; }
.msg-user { display: flex; justify-content: flex-end; margin: 0.5rem 0; }
.msg-user .bubble {
    background: linear-gradient(135deg, #3b82f6, #6366f1); color: #fff;
    padding: 0.6rem 0.9rem; border-radius: 16px 16px 4px 16px; max-width: 75%;
    font-size: 0.9rem; white-space: pre-wrap;
}
.msg-assistant { display: flex; justify-content: flex-start; margin: 0.5rem 0; }
.msg-assistant .bubble {
    background: #1e2330; color: #cbd5e1; padding: 0.6rem 0.9rem;
    border-radius: 16px 16px 16px 4px; max-width: 75%; font-size: 0.9rem;
    border: 1px solid #2d3748; white-space: pre-wrap;
}
.tool-pill {
    font-family: 'JetBrains Mono', monospace; font-size: 0.7rem; color: #60a5fa;
    background: #0f1923; border: 1px solid #1e40af; border-radius: 6px;
    padding: 0.25rem 0.5rem; margin: 0.2rem 0; display: inline-block;
}
.memory-panel {
    background: #141820; border: 1px solid #2d3748; border-radius: 10px;
    padding: 0.75rem; font-family: 'JetBrains Mono', monospace; font-size: 0.72rem;
    color: #94a3b8; max-height: 420px; overflow-y: auto;
}
</style>
""",
    unsafe_allow_html=True,
)


def safe_text(value) -> str:
    return html.escape(str(value or ""))


def extract_tool_names(res) -> list[str]:
    names = []
    if isinstance(res, dict):
        for tc in res.get("tool_calls") or []:
            name = tc.get("function", {}).get("name")
            if name and name not in names:
                names.append(name)
    return names


# ── Session state ─────────────────────────────────────────────────────────────
if "user_id" not in st.session_state:
    st.session_state.user_id = "user_demo_1"

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())[:8]

if "messages" not in st.session_state:
    st.session_state.messages = []

if "episode_message" not in st.session_state:
    st.session_state.episode_message = None

if "last_extraction" not in st.session_state:
    st.session_state.last_extraction = None


def end_session():
    convo = st.session_state.episode_message
    if convo:
        with st.spinner("Extracting memories…"):
            st.session_state.last_extraction = extract_all_memories(
                convo, st.session_state.user_id
            )
    st.session_state.messages = []
    st.session_state.episode_message = None
    st.session_state.session_id = str(uuid.uuid4())[:8]
    st.rerun()


# ── Layout ────────────────────────────────────────────────────────────────────
col_main, col_side = st.columns([2, 1])

with col_main:
    st.markdown('<div class="app-title">🧠 Vibe Coding · Memory Testbed</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="app-subtitle">Session · Profile · Preference · Episodic (personal)</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="meta-bar">USER · {safe_text(st.session_state.user_id)} &nbsp;|&nbsp; '
        f'SESSION · {safe_text(st.session_state.session_id)}</div>',
        unsafe_allow_html=True,
    )

with col_side:
    st.session_state.user_id = st.text_input(
        "User ID",
        value=st.session_state.user_id,
        help="All profile and preference memory is scoped to this ID. "
        "Episodic memory is personal per user (shared is opt-in via config).",
    )
    episode_intent = st.text_input(
        "Test episode retrieval",
        placeholder="e.g. fix Next.js hydration error",
    )
    if st.button("Retrieve episodes", use_container_width=True) and episode_intent.strip():
        hits = retrieve_episodes(st.session_state.user_id, episode_intent.strip())
        st.session_state["episode_preview"] = hits


# ── Chat history ──────────────────────────────────────────────────────────────
with col_main:
    for msg in st.session_state.messages:
        content = safe_text(msg.get("content", ""))
        if msg.get("role") == "user":
            st.markdown(f'<div class="msg-user"><div class="bubble">{content}</div></div>', unsafe_allow_html=True)
        elif msg.get("role") == "assistant":
            for tool_name in msg.get("tools", []):
                st.markdown(f'<span class="tool-pill">⚙ {safe_text(tool_name)}</span>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="msg-assistant"><div class="bubble">{content}</div></div>',
                unsafe_allow_html=True,
            )

    with st.form("chat_form", clear_on_submit=True):
        c1, c2 = st.columns([5, 1])
        with c1:
            user_input = st.text_input("Message", placeholder="Describe what you want to build…", label_visibility="collapsed")
        with c2:
            send = st.form_submit_button("Send", use_container_width=True)

    b1, b2, b3 = st.columns(3)
    with b2:
        if st.button("End session → extract memories", use_container_width=True):
            end_session()


# ── Memory inspector ──────────────────────────────────────────────────────────
with col_side:
    st.subheader("Memory inspector")

    profile = get_user_profile(st.session_state.user_id)
    prefs = get_user_preferences(st.session_state.user_id)

    st.caption("Profile (long-term facts)")
    st.markdown(
        f'<div class="memory-panel">{safe_text(json.dumps(profile, indent=2, default=str))}</div>',
        unsafe_allow_html=True,
    )

    st.caption("Preferences")
    st.markdown(
        f'<div class="memory-panel">{safe_text(json.dumps(prefs, indent=2, default=str))}</div>',
        unsafe_allow_html=True,
    )

    if st.session_state.get("episode_preview"):
        st.caption("Episode retrieval preview")
        st.markdown(
            f'<div class="memory-panel">{safe_text(json.dumps(st.session_state["episode_preview"], indent=2, default=str))}</div>',
            unsafe_allow_html=True,
        )

    if st.session_state.last_extraction:
        st.caption("Last extraction result")
        st.markdown(
            f'<div class="memory-panel">{safe_text(json.dumps(st.session_state.last_extraction, indent=2, default=str))}</div>',
            unsafe_allow_html=True,
        )


# ── Send handler ──────────────────────────────────────────────────────────────
if send and user_input.strip():
    prompt = user_input.strip()
    st.session_state.messages.append({"role": "user", "content": prompt})

    tool_names_called = []
    try:
        import src.response as resp_module

        original_run = resp_module.LLM.run

        def patched_run(messages, tools=None):
            result = original_run(messages=messages, tools=tools)
            if isinstance(result, dict):
                for name in extract_tool_names(result):
                    if name not in tool_names_called:
                        tool_names_called.append(name)
            return result

        try:
            resp_module.LLM.run = patched_run
            res, full_conversation = generate_response(
                ChatRequest(
                    userID=st.session_state.user_id,
                    sessionID=st.session_state.session_id,
                    query=prompt,
                )
            )
        finally:
            resp_module.LLM.run = original_run

        st.session_state.episode_message = full_conversation
        assistant_content = res.get("content") or "No response content returned."

    except Exception as e:
        assistant_content = f"Error: {type(e).__name__}: {e}"

    st.session_state.messages.append(
        {"role": "assistant", "content": assistant_content, "tools": tool_names_called}
    )
    st.rerun()
