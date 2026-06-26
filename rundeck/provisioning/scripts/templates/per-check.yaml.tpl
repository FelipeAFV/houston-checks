- defaultTab: nodes
  description: '__DESCRIPTION__'
  executionEnabled: true
  group: __JOB_GROUP__
  loglevel: INFO
  name: houston - __CHECK_ID__
  nodeFilterEditable: false
  scheduleEnabled: false
  timeout: __JOB_TIMEOUT__
  nodefilters:
    dispatch:
      excludePrecedence: true
      keepgoing: true
      rankOrder: ascending
      successOnEmptyNodeFilter: false
      threadcount: '__NODE_THREADCOUNT__'
    filter: 'tags: check-__CHECK_ID__'
  sequence:
    strategy: __WORKFLOW_STRATEGY__
    keepgoing: __SEQUENCE_KEEPGOING__
    commands:
      - script: |
          NODE_BASE='__CHECK_SCRIPT_BASE__'
          mkdir -p "${NODE_BASE}/scripts/lib" "${NODE_BASE}/lib" "${NODE_BASE}/capture"
        scriptInterpreter: /bin/bash
        description: 'Create check paths on the node (Copy File/SCP does not mkdir -p).'
        errorhandler:
          nodeStep: true
          type: localexec
          configuration:
            command: >
              __RUNDECK_SCRIPTS_DIR__/curl-step.sh fail "${node.uptime_ping___CHECK_ID__}"
      - nodeStep: true
        type: copyfile
        description: 'Copy run-check-step.sh to the node.'
        configuration:
          sourcePath: __RUNDECK_SCRIPTS_DIR__/run-check-step.sh
          destinationPath: '__CHECK_SCRIPT_BASE__/scripts/'
          recursive: 'false'
          echo: 'true'
        errorhandler:
          nodeStep: true
          type: localexec
          configuration:
            command: >
              __RUNDECK_SCRIPTS_DIR__/curl-step.sh fail "${node.uptime_ping___CHECK_ID__}"
      - nodeStep: true
        type: copyfile
        description: 'Copy lib/check-capture.sh to the node.'
        configuration:
          sourcePath: __RUNDECK_SCRIPTS_DIR__/lib/check-capture.sh
          destinationPath: '__CHECK_SCRIPT_BASE__/scripts/lib/'
          recursive: 'false'
          echo: 'true'
        errorhandler:
          nodeStep: true
          type: localexec
          configuration:
            command: >
              __RUNDECK_SCRIPTS_DIR__/curl-step.sh fail "${node.uptime_ping___CHECK_ID__}"
      - nodeStep: true
        type: copyfile
        description: 'Copy check-shell/__CHECK_ID__.sh to the node.'
        configuration:
          sourcePath: __SCM_BASE_DIR__/check-shell/__CHECK_ID__.sh
          destinationPath: '__CHECK_SCRIPT_BASE__/'
          recursive: 'false'
          echo: 'true'
        errorhandler:
          nodeStep: true
          type: localexec
          configuration:
            command: >
              __RUNDECK_SCRIPTS_DIR__/curl-step.sh fail "${node.uptime_ping___CHECK_ID__}"
      - nodeStep: true
        type: copyfile
        description: 'Copy check-shell/lib/ to the node (switch helpers, etc.).'
        configuration:
          sourcePath: __SCM_BASE_DIR__/check-shell/lib
          destinationPath: '__CHECK_SCRIPT_BASE__/'
          recursive: 'true'
          echo: 'true'
        errorhandler:
          nodeStep: true
          type: localexec
          configuration:
            command: >
              __RUNDECK_SCRIPTS_DIR__/curl-step.sh fail "${node.uptime_ping___CHECK_ID__}"
      - script: |
          NODE_BASE='__CHECK_SCRIPT_BASE__'
          chmod +x "${NODE_BASE}/scripts/run-check-step.sh" 2>/dev/null || true
          chmod +x "${NODE_BASE}/__CHECK_ID__.sh" 2>/dev/null || true
          find "${NODE_BASE}/lib" -type f -name '*.sh' -exec chmod a+x {} + 2>/dev/null || true
          export NODE_NAME='@node.name@'
          export JOB_EXECID='@job.execid@'
          export TARGET_HOST='@node.target_host@'
          export TARGET_USER='@node.target_user@'
          export TARGET_PORT='@node.target_port@'
          set +e
          if [[ -n "${TARGET_HOST}" ]]; then
            REMOTE="${TARGET_USER}@${TARGET_HOST}"
            SSH_OPTS=(-p "${TARGET_PORT:-22}" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)
            ssh "${SSH_OPTS[@]}" "${REMOTE}" "mkdir -p ${NODE_BASE}/scripts/lib ${NODE_BASE}/lib ${NODE_BASE}/capture"
            scp -P "${TARGET_PORT:-22}" -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
              "${NODE_BASE}/scripts/run-check-step.sh" "${REMOTE}:${NODE_BASE}/scripts/"
            scp -P "${TARGET_PORT:-22}" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -r \
              "${NODE_BASE}/scripts/lib" "${REMOTE}:${NODE_BASE}/scripts/"
            scp -P "${TARGET_PORT:-22}" -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
              "${NODE_BASE}/__CHECK_ID__.sh" "${REMOTE}:${NODE_BASE}/"
            scp -P "${TARGET_PORT:-22}" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -r \
              "${NODE_BASE}/lib" "${REMOTE}:${NODE_BASE}/"
            ssh "${SSH_OPTS[@]}" "${REMOTE}" \
              "chmod +x ${NODE_BASE}/scripts/run-check-step.sh ${NODE_BASE}/__CHECK_ID__.sh 2>/dev/null || true; \
               find ${NODE_BASE}/lib -type f -name '*.sh' -exec chmod a+x {} + 2>/dev/null || true; \
               export NODE_NAME='${NODE_NAME}'; export JOB_EXECID='${JOB_EXECID}'; \
               ${NODE_BASE}/scripts/run-check-step.sh shell __CHECK_ID__ ${NODE_BASE}"
            CHECK_RC=$?
          else
            "${NODE_BASE}/scripts/run-check-step.sh" shell __CHECK_ID__ "${NODE_BASE}"
            CHECK_RC=$?
          fi
          set -e
          printf 'CHECK_RC=%s\n' "${CHECK_RC}"
          printf 'RUNDECK:DATA:check_rc=%s\n' "${CHECK_RC}"
          exit 0
        scriptInterpreter: /bin/bash
        description: 'Remote exec: run check-shell/__CHECK_ID__.sh on target (SSH hop via bastion when target_host is set). Always exits 0 so the curl step receives log-filter data.'
        plugins:
          LogFilter:
            - type: key-value-data
              config:
                regex: ^RUNDECK:DATA:(.+?)\s*=\s*(.+)$
                logData: 'false'
            - type: key-value-data
              config:
                name: check_output_b64
                regex: ^CHECK_BODY_B64=(.+)$
            - type: key-value-data
              config:
                name: check_rc
                regex: ^CHECK_RC=(.+)$
      - nodeStep: true
        type: localexec
        configuration:
          command: >
            __RUNDECK_SCRIPTS_DIR__/curl-step.sh from-data
            "${data.check_rc}"
            "${data.check_output_b64}"
            "${node.uptime_ping___CHECK_ID__}"
        description: 'Localexec on Rundeck: curl Uptime ping URL; exits with CHECK_RC so Rundeck marks fail when the check failed.'
