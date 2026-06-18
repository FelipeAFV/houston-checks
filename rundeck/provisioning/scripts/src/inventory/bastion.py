"""Python bastion node helpers for Rundeck resources YAML."""

from __future__ import annotations

from typing import Any, Protocol


class BastionConfig(Protocol):
    bastion_host: str
    bastion_port: str
    bastion_user: str
    bastion_key_storage: str
    bastion_ssh_keypath: str


def bastion_connect_hostname(host: str, port: str) -> str:
    """Return host:port or host when port is 22 or empty."""
    if port and port != "22":
        return f"{host}:{port}"
    return host


def emit_bastion_ssh_key_attrs(jg: BastionConfig) -> list[str]:
    """Return ssh-authentication YAML lines for the bastion node entry."""
    if jg.bastion_ssh_keypath:
        return [
            "  ssh-authentication: privateKey",
            f"  ssh-keypath: {jg.bastion_ssh_keypath}",
        ]
    return [
        "  ssh-authentication: privateKey",
        f"  ssh-key-storage-path: {jg.bastion_key_storage}",
    ]
