## app/__init__.py

```python
__all__ = ["client", "config", "utils", "docs_extractor"]
```

## app/client.py

```python
from openai import OpenAI
from .config import NGROK_URL

def get_client() -> OpenAI:
    """Return a client that talks to the local OpenAI‑compatible server."""
    return OpenAI(base_url=f"{NGROK_URL}/v1", api_key="token")
```

## app/config.py

```python
# Configuration – tweak these values as needed
NGROK_URL = "http://localhost:8000"
MODEL_NAME = "unsloth/gpt-oss-20b-GGUF:F16"
DEFAULT_SYSTEM_PROMPT = "Be concise and accurate at all times"
```

## app/docs_extractor.py

```python
# app/docs_extractor.py
"""
extract_docs.py → docs_extractor.py
-----------------------------------
Walk a directory tree and write a single Markdown file that contains:

* The relative path of each file (as a level‑2 heading)
* The raw source code of that file (inside a fenced code block)
"""

from __future__ import annotations

import pathlib
import sys
import logging

log = logging.getLogger(__name__)

def walk_python_files(root: pathlib.Path) -> list[pathlib.Path]:
    """Return all *.py files sorted alphabetically."""
    return sorted(root.rglob("*.py"))

def write_docs(root: pathlib.Path, out: pathlib.Path) -> None:
    """Append file path + code to *out*."""
    with out.open("w", encoding="utf-8") as f_out:
        for p in walk_python_files(root):
            rel = p.relative_to(root)
            f_out.write(f"## {rel}\n\n")
            f_out.write("```python\n")
            f_out.write(p.read_text(encoding="utf-8"))
            f_out.write("\n```\n\n")

def extract(repo_root: pathlib.Path | str = ".", out_file: pathlib.Path | str | None = None) -> pathlib.Path:
    """
    Extract the repo into a Markdown file and return the path.

    Parameters
    ----------
    repo_root : pathlib.Path | str
        Root of the repo to walk.  Defaults to the current dir.
    out_file : pathlib.Path | str | None
        Path to write the Markdown.  If ``None`` uses ``repo_docs.md``.
    """
    root = pathlib.Path(repo_root).resolve()
    out = pathlib.Path(out_file or "repo_docs.md").resolve()

    log.info("Extracting docs from %s → %s", root, out)
    write_docs(root, out)
    log.info("✅  Wrote docs to %s", out)
    return out

def main() -> None:  # CLI entry point
    import argparse

    parser = argparse.ArgumentParser(description="Extract a repo into Markdown")
    parser.add_argument("repo_root", nargs="?", default=".", help="Root of the repo")
    parser.add_argument("output", nargs="?", default="repo_docs.md", help="Output Markdown file")
    args = parser.parse_args()

    extract(args.repo_root, args.output)

if __name__ == "__main__":
    main()
```

## app/utils.py

```python
# app/utils.py  (only the added/modified parts)
from typing import List, Tuple, Dict, Optional
from .config import DEFAULT_SYSTEM_PROMPT, MODEL_NAME
from .client import get_client
from openai import OpenAI

# --------------------------------------------------------------------------- #
# Build the messages list that the OpenAI API expects
# --------------------------------------------------------------------------- #
def build_api_messages(
    history: List[Tuple[str, str]],
    system_prompt: str,
    repo_docs: Optional[str] = None,
) -> List[Dict]:
    """
    Convert local chat history into the format expected by the OpenAI API.

    Parameters
    ----------
    history : List[Tuple[str, str]]
        (user, assistant) pairs.
    system_prompt : str
        Prompt given to the model.
    repo_docs : str | None
        Full code‑base text.  If supplied it is sent as the *first* assistant
        message so the model can read it before answering.
    """
    msgs = [{"role": "system", "content": system_prompt}]
    if repo_docs:
        msgs.append({"role": "assistant", "content": repo_docs})
    for user_msg, bot_msg in history:
        msgs.append({"role": "user", "content": user_msg})
        msgs.append({"role": "assistant", "content": bot_msg})
    return msgs

# --------------------------------------------------------------------------- #
# Stream the assistant reply token‑by‑token
# --------------------------------------------------------------------------- #
def stream_response(
    history: List[Tuple[str, str]],
    user_msg: str,
    client: OpenAI,
    system_prompt: str,
    repo_docs: Optional[str] = None,
):
    """Yield the cumulative assistant reply while streaming."""
    new_hist = history + [(user_msg, "")]
    api_msgs = build_api_messages(new_hist, system_prompt, repo_docs)

    stream = client.chat.completions.create(
        model=MODEL_NAME, messages=api_msgs, stream=True
    )

    full_resp = ""
    for chunk in stream:
        token = chunk.choices[0].delta.content or ""
        full_resp += token
        yield full_resp
```

## app.py

```python
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
    if "history" not in st.session_state:
        st.session_state.history = []          # [(user, bot), ...]
    if "system_prompt" not in st.session_state:
        st.session_state.system_prompt = DEFAULT_SYSTEM_PROMPT
    if "repo_docs" not in st.session_state:
        st.session_state.repo_docs = ""        # will hold the full codebase
    if "has_pushed" not in st.session_state:
        # Initialise based on the current git state
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
```

## push_to_github.py

```python
#!/usr/bin/env python3
"""
Push a local folder to GitHub without leaking the PAT.
The PAT must be supplied via the environment variable GITHUB_TOKEN.
"""

import os
import sys
from pathlib import Path

from github import Github, GithubException
from github.Auth import Token
from git import Repo, GitCommandError, InvalidGitRepositoryError

# ------------------------------------------------------------------
# USER SETTINGS
# ------------------------------------------------------------------
LOCAL_DIR   = Path(__file__).parent          # folder you want to push
REPO_NAME   = "v1"                      # GitHub repo name
USER_NAME   = "ghghang2"         # e.g. ghghang2

IGNORED_ITEMS = [
    ".config",
    ".ipynb_checkpoints",
    "sample_data",
    "llama-server",
    "nohup.out",
    "__pycache__",
]

# ------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------
def token() -> str:
    """Get the PAT from the environment."""
    t = os.getenv("GITHUB_TOKEN")
    if not t:
        print("Error: GITHUB_TOKEN env variable not set.")
        sys.exit(1)
    return t

def remote_url() -> str:
    """HTTPS URL that contains the token (used only for git push)."""
    return f"https://{USER_NAME}:{token()}@github.com/{USER_NAME}/{REPO_NAME}.git"

def ensure_remote(repo: Repo, url: str) -> None:
    if "origin" in repo.remotes:
        repo.delete_remote("origin")
    repo.create_remote("origin", url)

def create_repo_if_missing(g: Github) -> None:
    user = g.get_user()
    try:
        user.get_repo(REPO_NAME)
        print(f"Repo '{REPO_NAME}' already exists on GitHub.")
    except GithubException:
        user.create_repo(REPO_NAME, private=False)
        print(f"Created repo '{REPO_NAME}' on GitHub.")

def write_gitignore(repo_path: Path, items: list[str]) -> None:
    gitignore_path = repo_path / ".gitignore"
    gitignore_path.write_text("\n".join(items) + "\n")
    print(f"Created .gitignore at {gitignore_path}")

# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
def main() -> None:
    if not LOCAL_DIR.is_dir():
        print(f"Local directory '{LOCAL_DIR}' not found.")
        sys.exit(1)

    repo_path = LOCAL_DIR

    # Open or initialise repo
    try:
        repo = Repo(repo_path)
        if repo.bare:
            raise InvalidGitRepositoryError(repo_path)
        print(f"Using existing git repo at {repo_path}")
    except (InvalidGitRepositoryError, GitCommandError):
        repo = Repo.init(repo_path)
        print(f"Initialised new git repo at {repo_path}")

    # Create the remote repo on GitHub (if needed)
    g = Github(auth=Token(token()))
    create_repo_if_missing(g)

    # Attach the remote URL
    ensure_remote(repo, remote_url())

    # Create .gitignore
    write_gitignore(repo_path, IGNORED_ITEMS)

    # Stage everything (ignores applied)
    repo.git.add(A=True)

    # Commit – ignore “nothing to commit” error
    try:
        repo.index.commit("Initial commit")
        print("Committed changes.")
    except GitCommandError as e:
        if "nothing to commit" in str(e):
            print("Nothing new to commit.")
        else:
            raise

    # Switch to / create the local 'main' branch
    if "main" not in [b.name for b in repo.branches]:
        repo.git.checkout("-b", "main")
        print("Created local branch 'main'.")
    else:
        repo.git.checkout("main")
        print("Switched to existing branch 'main'.")

    # Push to the remote and set upstream
    try:
        repo.git.push("-u", "origin", "main")
        print("Push complete. Remote 'main' is now tracked.")
    except GitCommandError as exc:
        print(f"Git operation failed: {exc}")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

