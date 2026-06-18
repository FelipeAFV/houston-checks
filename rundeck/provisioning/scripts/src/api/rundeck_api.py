"""Write Rundeck resources (nodes) YAML into the Git SCM checkout.

The generated ``nodes.yaml`` is committed/pushed by :mod:`src.scm.git_publish`.
Rundeck reloads it via the Git Resource Model source on the next pull.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from src.utils.util import log


def resources_dest_path(scm_base: str, raw_path: str) -> str:
    """Resolve the destination path for the resources YAML file.

    Falls back to ``<SCM_BASE_DIR>/rundeck/resources/nodes.yaml`` when
    ``raw_path`` is empty or contains only quote characters.
    """
    raw = (raw_path or "").strip().replace("\r", "").replace("\n", "")
    if raw in ('""', "''"):
        raw = ""
    if not raw:
        return f"{scm_base.rstrip('/')}/rundeck/resources/nodes.yaml"
    if raw.startswith("/"):
        return raw
    return f"{scm_base.rstrip('/')}/{raw.lstrip('./')}"


def write_resources_to_repo(
    yaml_body_path: str,
    scm_base: str,
    resources_path: str,
) -> None:
    """Copy the staging resources YAML into the SCM repo working tree."""
    dest = resources_dest_path(scm_base, resources_path)
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(yaml_body_path, dest)
    size = Path(dest).stat().st_size
    log(f"[rd] wrote resources YAML -> {dest} ({size} bytes)")
    log("[rd] publish via git push (scm.auto_push) and Git Resource Model pull on Rundeck")
