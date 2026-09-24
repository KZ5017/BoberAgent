+++
id = "procedure.network.service_discovery"
version = 1
title = "Bounded network service discovery"
status = "CANONICAL"
source_kind = "author_maintained"
goal_type = "service_discovery"
environment = "scoped_network_asset"
technology = "tcp"
required_state = ["asset.address.available"]
produced_state = ["network.service"]
preconditions = ["The Asset and selected address are inside Mission scope."]
completion_conditions = ["A terminal service-discovery Result has been assessed, including a negative result with no services."]
known_failure_modes = ["Missing local scanner dependency", "Target unavailable", "Malformed scan output"]
related_knowledge_ids = ["knowledge.network.service_evidence"]

[[steps]]
step_id = "discover"
capability_id = "network.service_discovery"
operation = "discover"
purpose = "Collect bounded TCP service evidence for one scoped Asset."
+++
# Bounded network service discovery

Resolve one Asset and its address, verify scope, then request `network.service_discovery`.
The Workflow supplies the Mission-specific AssetRef, profile and success policy when it instantiates
the operation; this Procedure does not execute it or decide the target automatically.

## Completion

Review the terminal Result and its normalized Observations. A completed negative scan is valid
assessment information; tool failure or unknown parsing is not a completed inventory.
