#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import shutil
from pathlib import Path

from github import Github, GithubException
from github.Auth import Token
from git import Repo, GitCommandError, InvalidGitRepositoryError

# ------------------------------------------------------------------
# USER SETTINGS
# ------------------------------------------------------------------
LOCAL_DIR   = Path(__file__).parent          # folder you want to push
REPO_NAME   = "v1.1"                            # GitHub repo name
USER_NAME   = "ghghang2"                      # e.g. ghghang2

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
    """Delete any existing `origin` remote and create a fresh one."""
    if "origin" in repo.remotes:
        repo.delete_remote("origin")
    repo.create_remote("origin", url)

def create_repo_if_missing(g: Github) -> None:
    """Create the GitHub repo if it does not already exist."""
    user = g.get_user()
    try:
        user.get_repo(REPO_NAME)
        print(f"Repo '{REPO_NAME}' already exists on GitHub.")
    except GithubException:
        user.create_repo(REPO_NAME, private=False)
        print(f"Created repo '{REPO_NAME}' on GitHub.")

def write_gitignore(repo_path: Path, items: list[str]) -> None:
    """Write a .gitignore file with the supplied items."""
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

    # *** NEW: discard any stale merge‑conflict files ***
    repo.git.reset("--hard")

    # ------------------------------------------------------------------
    # Pull the latest changes from the remote so we can push
    # ------------------------------------------------------------------
    try:
        # Clean up a stale rebase directory if it exists
        rebase_dir = repo_path / ".git" / "rebase-merge"
        if rebase_dir.exists():
            shutil.rmtree(rebase_dir)
            print("Removed stale rebase-merge directory.")

        # Tell Git that we want to rebase automatically
        repo.git.config('pull.rebase', 'true')

        # Rebase local commits onto the fetched remote branch.
        repo.git.pull('--rebase', 'origin', 'main')
    except GitCommandError as exc:
        print(f"Rebase failed: {exc}. Falling back to merge.")

        # Ensure we have a Git identity (local config is sufficient)
        repo.git.config('user.email', 'you@example.com')
        repo.git.config('user.name', 'Your Name')

        try:
            repo.git.merge('origin/main')
        except GitCommandError as merge_exc:
            print(f"Merge also failed: {merge_exc}. Aborting push.")
            sys.exit(1)

    # Push to the remote and set upstream
    try:
        repo.git.push('-u', 'origin', 'main')
        print("Push complete. Remote 'main' is now tracked.")
    except GitCommandError as exc:
        print(f"Git operation failed: {exc}")
        sys.exit(1)

if __name__ == "__main__":
    main()