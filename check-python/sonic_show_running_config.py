#!/usr/bin/env python3

"""
Name: Running configuration

Description:
Check SONiC running configuration for feature status,
telemetry gNMI VRF, and syslog servers.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from json import JSONDecodeError


from lib.helpers import (
    get_features,
    get_telemetry_gnmi_vrf,
    get_syslog_servers,
    is_feature_up,
    is_feature_enabled,
    format_runningconfiguration_all_output,
)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

RUN_SWITCH_COMMAND = os.path.join(
    SCRIPT_DIR,
    "../lib/python_send_command_to_device_wrapper.sh",
)


EXCLUDED_FEATURES = {
    "database",
    "mfa",
}


def run_show_runningconfiguration_all() -> object:
    """Run show runningconfiguration all on the remote switch."""

    proc = subprocess.run(
        [RUN_SWITCH_COMMAND],
        input="show runningconfiguration all\nexit\n",
        capture_output=True,
        text=True,
        check=False,
    )

    if proc.returncode != 0:
        error = (proc.stderr or proc.stdout or "").strip()

        raise RuntimeError(
            "Failed to execute 'show runningconfiguration all'"
            + (f": {error}" if error else "")
        )

    output = proc.stdout


    print("=== STDOUT ===", file=sys.stderr)
    print(repr(output), file=sys.stderr)
    print("=== STDERR ===", file=sys.stderr)
    print(repr(proc.stderr), file=sys.stderr)
    print("=== RETURN CODE ===", proc.returncode, file=sys.stderr)

    try:
        return json.loads(output)

    except JSONDecodeError:
        try:
            return parse("asciitable", output)[1:]
        except Exception as exc:
            raise RuntimeError(
                "Unable to parse 'show runningconfiguration all' output"
            ) from exc


def check_features(status: object) -> bool:
    """Check that all required features are up and enabled."""

    features = get_features(status)

    failed_features = [
        format_runningconfiguration_all_output(feature)
        for feature in features
        if feature.get("name") not in EXCLUDED_FEATURES
        and (
            not is_feature_up(feature)
            or not is_feature_enabled(feature)
        )
    ]

    if failed_features:
        print(
            "Running configuration feature failures:",
            file=sys.stderr,
        )

        for feature in failed_features:
            print(f"  {feature}", file=sys.stderr)

        return False

    print("  Features: all required features are up and enabled")

    return True


def check_telemetry(status: object) -> bool:
    """Check telemetry gNMI VRF configuration."""

    current_vrf = get_telemetry_gnmi_vrf(status)

    expected_vrf = os.environ.get(
        "expected_telemetry_gnmi_vrf"
    )

    if expected_vrf is None:
        print(
            "ERROR: expected_telemetry_gnmi_vrf is not defined",
            file=sys.stderr,
        )
        return False

    if current_vrf != expected_vrf:
        print(
            "Telemetry gNMI VRF is not properly configured "
            f"(current: {current_vrf}, expected: {expected_vrf})",
            file=sys.stderr,
        )
        return False

    print(f"  Telemetry gNMI VRF: {current_vrf}")

    return True


def check_syslog(status: object) -> bool:
    """Check that the expected syslog servers are configured."""

    current_servers = get_syslog_servers(status)

    expected_servers_raw = os.environ.get(
        "expected_syslog_servers",
        "",
    )

    expected_servers = {
        server.strip()
        for server in expected_servers_raw.split(",")
        if server.strip()
    }

    missing_servers = expected_servers - set(current_servers)

    if not current_servers:
        print(
            "No syslog servers are configured",
            file=sys.stderr,
        )
        return False

    if missing_servers:
        print(
            "Syslog servers are not properly configured "
            f"(missing: {sorted(missing_servers)})",
            file=sys.stderr,
        )
        return False

    print(
        f"  Syslog servers: {sorted(current_servers)}"
    )

    return True


def main() -> int:
    try:
        status = run_show_runningconfiguration_all()

    except RuntimeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    checks = (
        check_features(status),
        check_telemetry(status),
        check_syslog(status),
    )

    if not all(checks):
        print(
            "Running configuration check: FAILED",
            file=sys.stderr,
        )
        return 1

    print("Running configuration check: OK")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())