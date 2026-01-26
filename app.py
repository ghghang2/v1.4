import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path
from git import Repo, InvalidGitRepositoryError
from app.config import DEFAULT_SYSTEM_PROMPT
from app.client import get_client
from app.utils import stream_response
from app.docs_extractor import extract
import push_to_github

# --------------------------------------------------------------------------- #
# Helper – run the extractor once (same folder as app.py)
# --------------------------------------------------------------------------- #
def refresh_docs() -> str:
    """Run the extractor once (same folder as app.py)."""
    out_path = extract()
    return out_path.read_text(encoding="utf‑8")

# --------------------------------------------------------------------------- #
# Git helper – determine whether local repo is identical to remote
# --------------------------------------------------------------------------- #
def is_repo_up_to_date(repo_path: Path) -> bool:
    """
    Return True iff the local HEAD is the same as the remote `origin/main`
    *and* there are no uncommitted changes.

    If any of these conditions fail the function returns False.
    """
    try:
        repo = Repo(repo_path)
    except InvalidGitRepositoryError:
        # No .git → definitely not up‑to‑date
        return False

    # If no remote defined → not up‑to‑date
    if not repo.remotes:
        return False

    origin = repo.remotes.origin
    # Fetch the latest refs from the remote
    try:
        origin.fetch()
    except Exception:
        # If fetch fails we conservatively say “not up‑to‑date”
        return False

    # Remote branch may be `main` or `master`; try `main` first
    remote_branch = None
    for branch_name in ("main", "master"):
        try:
            remote_branch = origin.refs[branch_name]
            break
        except IndexError:
            continue

    if remote_branch is None:
        # Remote has no `main`/`master` branch → not up‑to‑date
        return False

    # Compare commit SHA
    local_sha = repo.head.commit.hexsha
    remote_sha = remote_branch.commit.hexsha

    # No uncommitted changes
    dirty = repo.is_dirty(untracked_files=True)

    return (local_sha == remote_sha) and (not dirty)

# --------------------------------------------------------------------------- #
# Streamlit UI
# --------------------------------------------------------------------------- #
def main():
    st.set_page_config(page_title="Chat with GPT‑OSS", layout="wide")

    # Path of the repository (where this script lives)
    REPO_PATH = Path(__file__).parent

    # ---- Session state ----------------------------------------------------
    st.session_state.history = st.session_state.get("history", [])
    st.session_state.system_prompt = st.session_state.get(
        "system_prompt", DEFAULT_SYSTEM_PROMPT
    )
    st.session_state.repo_docs = st.session_state.get("repo_docs", "")

    # Re‑compute every time the script runs
    st.session_state.has_pushed = is_repo_up_to_date(REPO_PATH)

    # ---- Sidebar ----------------------------------------------------------
    with st.sidebar:
        st.header("Settings")

        # 1️⃣  System‑prompt editor (unchanged)
        prompt = st.text_area(
            "System prompt",
            st.session_state.system_prompt,
            height=120,
        )
        if prompt != st.session_state.system_prompt:
            st.session_state.system_prompt = prompt

        if st.button("New Chat"):
            st.session_state.history = []          # wipe the chat history
            st.session_state.repo_docs = ""        # optional: also clear docs
            st.success("Chat history cleared. Start fresh!")

        # 2️⃣  One‑click “Refresh Docs” button
        if st.button("Refresh Docs"):
            st.session_state.repo_docs = refresh_docs()
            st.success("Codebase docs updated!")

        if st.button("Push to GitHub"):
            with st.spinner("Pushing to GitHub…"):
                try:
                    push_to_github.main()          # run the external script
                    # After a successful push we consider the repo up‑to‑date
                    st.session_state.has_pushed = True
                    st.success("✅  Repository pushed to GitHub.")
                except Exception as exc:
                    st.error(f"❌  Push failed: {exc}")

        # Show push status
        status = "✅  Pushed" if st.session_state.has_pushed else "⚠️  Not pushed"
        st.markdown(f"**Push status:** {status}")

    # ---- Conversation UI --------------------------------------------------
    # Render the *past* messages
    for user_msg, bot_msg in st.session_state.history:
        with st.chat_message("user"):
            st.markdown(user_msg)
        with st.chat_message("assistant"):
            st.markdown(bot_msg)

    # ---- Input -------------------------------------------------------------
    if user_input := st.chat_input("Enter request…"):
        # Show the user’s text immediately
        st.chat_message("user").markdown(user_input)

        client = get_client()
        bot_output = ""

        with st.chat_message("assistant") as assistant_msg:
            # Placeholder inside that element – we’ll update it in place
            placeholder = st.empty()

            for partial in stream_response(
                st.session_state.history,
                user_input,
                client,
                st.session_state.system_prompt,
                st.session_state.repo_docs, 
            ):
                bot_output = partial
                placeholder.markdown(bot_output, unsafe_allow_html=True)

        # Save the finished reply
        st.session_state.history.append((user_input, bot_output))

    # -----------------------------------------------------------------------
    # Browser‑leaving guard – depends on the *session* flag
    # -----------------------------------------------------------------------
    has_pushed = st.session_state.get("has_pushed", False)
    components.html(
        f"""
        <script>
        // Store the push state in a global JS variable
        window.hasPushed = {str(has_pushed).lower()};

        // Hook into the browser's beforeunload event
        window.onbeforeunload = function(e) {{
          if (!window.hasPushed) {{
            // Returning a string triggers the browser confirmation dialog
            return 'You have not pushed to GitHub yet.\\nDo you really want to leave?';
          }}
        }};
        </script>
        """,
        height=0,
    )

if __name__ == "__main__":
    main()