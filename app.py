#!/usr/bin/env python3
"""Streamlit chat UI backed by a lightweight SQLite persistence.

The original application kept all messages only in ``st.session_state``.
To enable users to revisit older conversations we store each chat line
in a file‑based SQLite database.  The database lives in the repository
root as ``chat_history.db`` and contains a single ``chat_log`` table.

The UI now:

* shows a sidebar selector to pick an existing session or start a new one;
* loads the selected conversation on page load; and
* writes every user and assistant message to the DB after it is rendered.

Only the minimal amount of code needed for persistence is added – the
rest of the logic (model calls, tool handling, docs extraction, GitHub
push, etc.) remains unchanged.
"""

import json
import uuid
import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path
from git import InvalidGitRepositoryError, Repo
from app.config import DEFAULT_SYSTEM_PROMPT
from app.client import get_client
from app.tools import get_tools, TOOLS
from app.tools.repo_overview import func
from app.chat import build_messages, stream_and_collect, process_tool_calls
from app.db import init_db, log_message, load_history, get_session_ids

# Initialise the database on first run
init_db()

# Helper: refresh docs from the repo

def refresh_docs() -> str:
    """Run the repository extractor and return its Markdown output."""
    return func()

# Helper: check if local repo is up to date with GitHub

def is_repo_up_to_date(repo_path: Path) -> bool:
    try:
        repo = Repo(repo_path)
    except InvalidGitRepositoryError:
        return False
    if not repo.remotes:
        return False
    try:
        repo.remotes.origin.fetch()
    except Exception:
        return False
    for branch_name in ("main", "master"):
        try:
            remote_branch = repo.remotes.origin.refs[branch_name]
            break
        except IndexError:
            continue
    else:
        return False
    return (repo.head.commit.hexsha == remote_branch.commit.hexsha and not repo.is_dirty(untracked_files=True))

# Streamlit UI entry point

def main() -> None:
    st.markdown(
        """
        <style>
        /* reduce spacing between widgets */
        .stSidebar .css-1v0mbdj{margin: 0.1rem 0;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.set_page_config(page_title="Chat with GPT\u2011OSS", layout="wide")
    REPO_PATH = Path(__file__).parent

    # Session state
    st.session_state.setdefault("history", [])
    st.session_state.setdefault("system_prompt", DEFAULT_SYSTEM_PROMPT)
    st.session_state.setdefault("repo_docs", "")
    st.session_state.setdefault("has_pushed", False)

    # Sidebar
    with st.sidebar:
        # --- session controls
        if st.button("new chat", key="new_chat_btn"):
            st.session_state.session_id = str(uuid.uuid4())
            st.session_state.history = []
            st.session_state.repo_docs = ""
            st.session_state.has_pushed = False
            st.success("Chat history cleared. Start fresh!")
            st.rerun()

        # --- advanced actions (collapsible)
        # with st.expander("...", expanded=False):
        if st.button("ask code"):
            st.session_state.system_prompt += "\n\n" + refresh_docs()
            st.success("Codebase docs updated!")

        # --- status indicator
        if st.button("push to git"):
            with st.spinner("Pushing to GitHub…"):
                try:
                    from app.push_to_github import main as push_main
                    push_main()
                    st.session_state.has_pushed = True
                    st.success("✅ Repository pushed to GitHub.")
                except Exception as exc:
                    st.error(f"❌ Push failed: {exc}")

        status = "✅ Pushed" if st.session_state.has_pushed else "⚠️ Not pushed"
        st.markdown(f"{status}")

        # --- session selector
        session_options = ["new"] + get_session_ids()
        selected = st.selectbox("Choose a session", session_options)
        if selected != "new":
            st.session_state["session_id"] = selected
            st.rerun()

        # --- list of tools
        for t in TOOLS:
            st.markdown(f"{t.name}")

    # Load conversation
    session_id = st.session_state.get("session_id", str(uuid.uuid4()))
    history = load_history(session_id)
    st.session_state.history = history

    # Render past messages
    for user_msg, bot_msg in history:
        st.chat_message("user").markdown(user_msg)
        st.chat_message("assistant").markdown(bot_msg, unsafe_allow_html=True)

    # User input
    if user_input := st.chat_input("Enter request…"):
        st.chat_message("user").markdown(user_input)
        log_message(session_id, "user", user_input)

        client = get_client()
        tools = get_tools()
        msgs = build_messages(history, st.session_state.system_prompt, user_input)
        # msgs = build_messages(history, st.session_state.system_prompt, st.session_state.repo_docs, user_input)

        with st.chat_message("assistant"):
            placeholder = st.empty()
            assistant_text, tool_calls, finished = stream_and_collect(client, msgs, tools, placeholder)

        full_text = assistant_text
        if tool_calls and not finished:
            full_text = process_tool_calls(client, msgs, tools, placeholder, tool_calls, finished, assistant_text)
        else: 
            full_text = assistant_text
                
        history.append((user_input, full_text))
        log_message(session_id, "assistant", full_text)
        st.session_state.history = history

    components.html(
        "<script>window.addEventListener('beforeunload', e=>{'save':true});</script>",
        height=0,
    )

if __name__ == "__main__":
    main()
