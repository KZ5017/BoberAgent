+++
id = "knowledge.network.service_evidence"
version = 1
title = "Service discovery evidence"
type = "reference"
status = "CANONICAL"
source_kind = "author_maintained"
domains = ["network"]
tags = ["service-discovery", "evidence"]
protocol = "tcp"
capability_ids = ["network.service_discovery"]
procedure_ids = ["procedure.network.service_discovery"]
+++
# Service discovery evidence

An observed service endpoint is a Mission fact, not a reusable Knowledge item. Preserve the raw
scan evidence and normalize each supported endpoint as a `network.service` Observation.

## Interpretation

An open port is an observed service state, not automatically a security Finding. Missing product or
version details should remain unknown rather than inferred.

## Related procedure

`procedure.network.service_discovery` describes when to request this capability. It does not
replace Mission-specific scope checks or the Capability Contract.
