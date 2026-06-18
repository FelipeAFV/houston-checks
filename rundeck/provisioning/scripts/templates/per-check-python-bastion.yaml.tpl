- defaultTab: nodes
  description: '__DESCRIPTION__'
  executionEnabled: true
  group: __JOB_GROUP__
  loglevel: INFO
  name: houston - __CHECK_ID__
  nodeFilterEditable: false
  scheduleEnabled: false
  timeout: __JOB_TIMEOUT__
  options:
    - name: SWITCH_PASSWORD
      description: Switch SSH password (Key Storage). Path from config.yaml switch_ssh.password_key_storage_path.
      storagePath: __SWITCH_PASSWORD_KEY_STORAGE__
      secure: true
      valueExposed: true
      required: true
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
          mkdir -p /tmp/rundeck/scripts/lib /tmp/rundeck
        scriptInterpreter: /bin/bash
        description: 'Create /tmp/rundeck paths on python bastion (Copy File does not mkdir -p).'
        errorhandler:
          nodeStep: true
          type: localexec
          configuration:
            command: >
              __RUNDECK_SCRIPTS_DIR__/curl-step.sh fail "${node.uptime_ping___CHECK_ID__}"
      - nodeStep: true
        type: copyfile
        description: 'Copy run-check-step.sh to python bastion.'
        configuration:
          sourcePath: __RUNDECK_SCRIPTS_DIR__/run-check-step.sh
          destinationPath: /tmp/rundeck/scripts/
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
        description: 'Copy lib/check-capture.sh to python bastion.'
        configuration:
          sourcePath: __RUNDECK_SCRIPTS_DIR__/lib/check-capture.sh
          destinationPath: /tmp/rundeck/scripts/lib/
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
        description: 'Copy check-python/ tree to python bastion.'
        configuration:
          sourcePath: __SCM_BASE_DIR__/check-python
          destinationPath: /tmp/rundeck/
          recursive: 'true'
          echo: 'true'
        errorhandler:
          nodeStep: true
          type: localexec
          configuration:
            command: >
              __RUNDECK_SCRIPTS_DIR__/curl-step.sh fail "${node.uptime_ping___CHECK_ID__}"
      - script: |
          chmod +x /tmp/rundeck/scripts/run-check-step.sh 2>/dev/null || true
          mkdir -p /tmp/rundeck/check-python
          for _py in /tmp/rundeck/*.py; do
            [[ -e "${_py}" ]] || continue
            mv "${_py}" /tmp/rundeck/check-python/
          done
          export NODE_NAME='@node.name@'
          export JOB_EXECID='@job.execid@'
          export TARGET_HOST='@node.target_host@'
          export TARGET_USER='@node.target_user@'
          export TARGET_PORT='@node.target_port@'
          export TARGET_PASSWORD='@option.SWITCH_PASSWORD@'
          export NETMIKO_DEVICE_TYPE='@node.netmiko_device_type@'
          export NETMIKO_COMMAND='@node.netmiko_command@'
          set +e
          /tmp/rundeck/scripts/run-check-step.sh python __CHECK_ID__ /tmp/rundeck/check-python
          CHECK_RC=$?
          set -e
          printf 'CHECK_RC=%s\n' "${CHECK_RC}"
          printf 'RUNDECK:DATA:check_rc=%s\n' "${CHECK_RC}"
          exit 0
        scriptInterpreter: /bin/bash
        description: 'Remote exec on python bastion: Netmiko check __CHECK_ID__.py toward switch target. Always exits 0 so the curl step receives log-filter data.'
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
