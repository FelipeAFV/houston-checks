#!/usr/bin/env python3
# Name: Nova Compute VFs configuration
# Description: All VFs in Nova Compute configuration must be trusted.
"""Check Nova Compute VFs configuration on this host."""

from __future__ import annotations
from utils import cat_file, parse_ini_config

import json
import os
import sys


NOVA_CONFIG_PATH = os.environ.get("NOVA_CONFIG_PATH", "/etc/whitecloud/.kolla/nova-compute/nova.conf")


def main() -> int:

    try:
        nova_config = parse_ini_config(cat_file(NOVA_CONFIG_PATH))
        if not nova_config:
            print("Empty nova.conf file.")
            return 1

        if "pci" not in nova_config:
            print("Non-existent 'pci' section in nova.conf file.")
            return 0

        passthrough_whitelist = json.loads(nova_config.get("pci", {}).get("passthrough_whitelist", "[]"))
        if not passthrough_whitelist:
            print("Non-existent or empty 'passthrough_whitelist' in nova.conf file.")
            return 1

        non_trusted_vfs = [item.get("physical_network") for item in passthrough_whitelist if item.get("trusted") != "true"]
        if non_trusted_vfs:
            print(f"Non-trusted VFs in nova.conf file: [{', '.join(non_trusted_vfs)}].")
            return 1
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    print("All VFs in nova.conf file are trusted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
