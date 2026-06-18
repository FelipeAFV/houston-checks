- defaultTab: nodes
  description: '__DESCRIPTION__'
  executionEnabled: true
  group: __JOB_GROUP__
  loglevel: INFO
  name: houston - group __GROUP_ID__
  scheduleEnabled: false
  timeout: __JOB_TIMEOUT__
  nodefilters:
    dispatch:
      keepgoing: true
      threadcount: '1'
    filter: '__PARENT_NODE_FILTER__'
  sequence:
    strategy: parallel
    keepgoing: true
    commands:
__JOBREFS__
