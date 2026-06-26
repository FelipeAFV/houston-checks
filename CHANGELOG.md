# ChangeLog for Houston checks - collins

All noteworthy changes to the `collins` release should be documented in this file.

## Collins

- Feature(checks): Adds checks for VP LAG and VXLAN MAC Table on OcNOS switches [PRHOUSTON-316].
- Feature(checks): Adds checks for ufw status and apt upgrades [PRHOUSTON-322].
- Feature(provision): Adds tooling for provisioning the project [PRHOUSTON-321].
- Feature(Tests): Adds bash tests from legacy Houston [PRHOUSTON-321].
- Feature(provision): Adds python tests from legacy houston [PRHOUSTON-321].
- Feature(provision): Adds `NODE_TAGS` variable to checks' environment [PRHOUSTON-316].
- Feature(checks): Adds `load_expected_values` function to load variables from `expected_values.txt` into the environment of the check script [PRHOUSTON-316].
- Feature(checks): Adds `send_commands_to_device` function for checks running from bastion [PRHOUSTON-316].
