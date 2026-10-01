def get_features(status):
    return [
        {"name": name, **data}
        for name, data in status.get("FEATURE", {}).items()
    ]


def get_telemetry_gnmi_vrf(status):
    return status.get("TELEMETRY", {}).get("gnmi", {}).get("vrf")


def get_syslog_servers(status):
    return list(status.get("SYSLOG_SERVER", {}).keys())


def is_feature_enabled(feature):
    return feature.get("state") in {"enabled", "always_enabled"}


def is_feature_always_enabled(feature):
    return feature.get("state") == "always_enabled"


def is_feature_up(feature):
    return feature.get("check_up_status") == "True"


def is_feature_auto_restart(feature):
    return feature.get("auto_restart") == "True"


def format_runningconfiguration_all_output(item):
    return (
        f"{item.get('name')}: "
        f"{'Up' if is_feature_up(item) else 'Down'} | "
        f"State {item.get('state')} | "
        f"Auto restart {item.get('auto_restart')}"
    )