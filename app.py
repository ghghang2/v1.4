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
from app.metrics import get_llama_metrics
from app.metrics_ui import display_metrics_panel

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
        /* force the sidebar wrapper to be 100 px */
        .stSidebar { width: 150px !important; }

        /* force the inner container that actually receives the width */
        .stSidebar .css-1d391kg { width: 150px !important; }

        /* optional: tighten the inner padding */
        .stSidebar .css-1v0mbdj { padding: 0 !important; }
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

        # --- Server Status expander (new)
        display_metrics_panel()
        
        # --- session controls
        if st.button("new chat", key="new_chat_btn"):
            st.session_state.session_id = str(uuid.uuid4())
            st.session_state.history = []
            st.session_state.repo_docs = ""
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
    for role, content, tool_id, tool_name, tool_args in history:
        ## message regarding assistant calling tool require some special treatments. others are fine as is.
        if tool_name:
            st.chat_message(role).markdown(tool_name + ' called with args: ' + tool_args, unsafe_allow_html=True)
        else:
            if content:
                st.chat_message(role).markdown(content, unsafe_allow_html=True)

    # User input
    if user_input := st.chat_input("Enter request…"):
        st.chat_message("user").markdown(user_input)
        log_message(session_id, "user", user_input)

        client = get_client()
        tools = get_tools()
        msgs = build_messages(history, st.session_state.system_prompt, user_input)

        with st.chat_message("assistant"):
            assistant_text, tool_calls, finished, reasoning_text = stream_and_collect(client, msgs, tools)

            # appending reasoning to history
            history.append(("analysis", reasoning_text))
            log_message(session_id, "analysis", reasoning_text)

            if assistant_text: # sometimes, if reasoning assistant_text comes back empty
                history.append(("assistant", assistant_text))
                log_message(session_id, "assistant", assistant_text)
                
        if tool_calls and not finished:
            history = process_tool_calls(client, msgs, session_id, history, tools, tool_calls, finished, assistant_text, reasoning_text)
            
        st.session_state.history = history

    components.html(
        "<script>window.addEventListener('beforeunload', e=>{'save':true});</script>",
        height=0,
    )

if __name__ == "__main__":
    main()
