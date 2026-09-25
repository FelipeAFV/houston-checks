# ChangeLog for Houston checks - collins

All noteworthy changes to the `collins` release should be documented in this file.

## Collins

- Feature(Checks): Adds checks for VP LAG and VXLAN MAC Table on OcNOS switches [PRHOUSTON-316].
- Feature(Checks): Adds checks for ufw status and apt upgrades [PRHOUSTON-322].
- Feature(Provisioning): Adds tooling for provisioning the project [PRHOUSTON-321].
- Feature(Tests): Adds bash tests from legacy Houston [PRHOUSTON-321].
- Feature(Provisioning): Adds python tests from legacy houston [PRHOUSTON-321].
- Feature(Provisioning): Adds `NODE_TAGS` variable to checks' environment [PRHOUSTON-316].
- Feature(Checks): Adds `load_expected_values` function to load variables from `expected_values.txt` into the environment of the check script [PRHOUSTON-316].
- Feature(Checks): Adds `send_commands_to_device` function for checks running from bastion [PRHOUSTON-316].
- Chore(Provisioning): Updates provisioning files with latest changes [PRHOUSTON-321].
- Feature(Checks): Adds check for ensuring power profile is in optimized mode [PRHOUSTON-31].
- Feature(Provisioning): Adds support for parameterization of custom variables in checks scripts [PRHOUSTON-327].
- Feature(Checks): Adds check for active alerts in WhiteMon [PRHOUSTON-72].
- Feature(Checks): Adds check for sysctl limits in WhiteMist workers [PRHOUSTON-126].
- Feature(Checks): Adds a parameterized NFS read/write/delete check [PRHOUSTON-223].
- Feature(Checks): Adds checks for validating timezone data freshness [PRHOUSTON-45].
- Feature(Checks): Adds check for active alerts in Prometheus' Alertmanager and Keep [PRHOUSTON-329].
- Bugfix(Checks): Adds missing configurations for dynamic environment variables parameterization to job definition templates [PRHOUSTON-329].
- Bugfix(Provisioning): Fixes `lib` dir recursive copy [PRHOUSTON-340].
- Feature(Checks): Adds check for chronyc sources [PRHOUSTON-330].
- Bugfix(Checks): Fixes `max_queued_events` param name in sysctl checks [PRHOUSTON-352].
- Feature(Checks): Adds a check that verifies directory sizes stay below configurable limits [PRHOUSTON-332].
- Feature(Checks): Adds password expiration check with a configurable warning window and detection of passwords that never expire [PRHOUSTON-331].
- Feature(Checks): Adds check for Virsh threads per core [PRHOUSTON-333].
- Feature(Checks): Adds check for Nova Compute Virtual Functions configuration [PRHOUSTON-334].
- Bugfix(Checks): Adds Prometheus' Alertmanager and Keep pods existence condition to active alerts check.
- Bugfix(Checks): Fixes false negative in kolla configuration check due to permissions lacking [PRHOUSTON-341].
