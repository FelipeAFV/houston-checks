"""Git commit and push helpers for the SCM repo after provision.

After the provision pipeline writes Rundeck job YAML files and the resources
``nodes.yaml`` to the SCM working tree, this module stages all changes, creates
a timestamped commit, and pushes to the remote.

Authentication is handled via a temporary ``GIT_ASKPASS`` shell script that
injects ``SCM_GIT_USERNAME`` and ``SCM_GIT_PASSWORD`` from the environment so
no credentials are ever written to the git config.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.utils.util import fatal, log


def commit_and_push(
    repo_dir: str,
    workdir: str,
    *,
    dry_run: bool,
    auto_push: bool,
    git_username: str,
    git_password: str,
) -> None:
    """Stage all changes in ``repo_dir``, commit, and push to the remote.

    No-ops when ``dry_run`` is ``True`` or ``auto_push`` is ``False``.
    Also no-ops when there are no staged changes after ``git add .``.
    Exits with code 1 when the push fails so the Rundeck job step is marked
    as failed.
    """
    if dry_run or not auto_push:
        log("git publish skipped (dry_run or SCM_AUTO_PUSH not true)")
        return
    if not Path(repo_dir).is_dir():
        fatal(f"SCM_BASE_DIR is not a git repository: {repo_dir}")
        return
    if subprocess.run(
        ["git", "-C", repo_dir, "rev-parse", "--git-dir"],
        capture_output=True,
    ).returncode != 0:
        fatal(f"SCM_BASE_DIR is not a git repository: {repo_dir}")
        return

    askpass = Path(workdir) / "git-askpass.sh"
    askpass.write_text(
        """#!/bin/sh
case "$1" in
  *[Uu]sername*|*[Uu]ser\\ for*) printf '%s\\n' "${SCM_GIT_USERNAME:-oauth2}" ;;
  *[Pp]assword*) printf '%s\\n' "${SCM_GIT_PASSWORD:-}" ;;
  *) printf '\\n' ;;
esac
""",
        encoding="utf-8",
    )
    askpass.chmod(0o700)

    log(f"git: configuring local user in {repo_dir}")
    subprocess.run(["git", "-C", repo_dir, "config", "user.name", "rundeck"], check=True)
    subprocess.run(
        ["git", "-C", repo_dir, "config", "user.email", "rundeck@whitestack.com"],
        check=True,
    )
    subprocess.run(["git", "-C", repo_dir, "add", "."], check=True)
    diff = subprocess.run(
        ["git", "-C", repo_dir, "diff", "--cached", "--quiet"],
        capture_output=True,
    )
    if diff.returncode == 0:
        log("git: nothing to commit (working tree matches index after add)")
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    subprocess.run(
        ["git", "-C", repo_dir, "commit", "-m", f"houston-provision: sync job definitions {ts}"],
        check=True,
    )
    log("git: pushing to remote")
    env = os.environ.copy()
    env["GIT_ASKPASS"] = str(askpass)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["SCM_GIT_USERNAME"] = git_username
    env["SCM_GIT_PASSWORD"] = git_password
    proc = subprocess.run(
        ["git", "-C", repo_dir, "push"],
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        log(f"FATAL: git push failed (exit {proc.returncode})")
        sys.exit(1)
    if proc.stdout:
        print(proc.stdout, file=sys.stderr)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    log("git: push completed")
