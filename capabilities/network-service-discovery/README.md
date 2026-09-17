# Network service discovery

`network.service_discovery` is BoberAgent's tool-independent TCP service-discovery capability. It
supports the single `discover` operation and accepts one `AssetRef`, one semantic scan profile,
and a bounded timeout. The public input never accepts Nmap command-line fragments.

Profiles express assessment intent:

- `quick`: TCP connect and light version detection across Nmap's top 100 ports.
- `standard`: TCP connect and version detection across Nmap's top 1,000 ports.
- `full_tcp`: TCP connect and version detection across all TCP ports.

The current provider requires the logical `nmap` tool. It resolves the Asset through
`ExecutionContext.entities`, checks both Asset and address scope, runs Nmap through
`ProcessService`, and stores Nmap XML as a `network_scan.nmap_xml` Artifact. An isolated parser
normalizes explicit TCP port records. The capability emits `network.service` Observations only for
ports whose state is exactly `open`; closed, filtered, and unknown states remain available in the
raw evidence without creating materialized Service endpoints.

Malformed output does not discard evidence: the result is `COMPLETED` with an `UNKNOWN` semantic
outcome, the XML Artifact, and a diagnostic. A valid scan with no open ports is `COMPLETED` with a
`NEGATIVE` outcome. Nmap is an implementation dependency, not part of the capability identity.

This package depends only on Contracts, the Capability SDK, and Pydantic. It has no Core,
Execution Node, transport, persistence, or workflow dependency.
