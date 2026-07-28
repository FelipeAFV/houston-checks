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
- Feature(Checks): Adds check for active alerts in Whitemon [PRHOUSTON-72].

