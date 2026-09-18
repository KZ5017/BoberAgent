# BoberAgent MCP Transport

This package is the network carrier for the transport-neutral BoberAgent protocol. It uses the
official MCP Python SDK's Streamable HTTP transport. It contains no Core business logic, Execution
Node runtime logic, capability implementations, persistence, Artifact repository, or World State.

Core is the MCP client and an Execution Node is the MCP server. The server exposes only bounded,
namespaced tools for handshake, invocation acceptance, Run status, outbox polling,
acknowledgement, failure polling, and chunked Artifact reads. Capability submission is accepted
asynchronously; Events and Results still originate in the durable Node outboxes and remain pending
until Core acknowledges them.

`McpTransport` implements the existing neutral transport surface. Contract and protocol models are
serialized to JSON before each MCP call and validated again on receipt. The BoberAgent transport
protocol remains versioned independently from MCP and the Capability Contract.

Artifact synchronization is Core-pulled because Core is the client. The adapter reconstructs the
existing start/chunk/finalize exchange and sends every request through the existing Core Artifact
receiver. Artifact bytes are never inserted into Result or Event messages.

Bearer credentials are externally supplied as `SecretStr` configuration and are never included in
representations or diagnostics. Plain HTTP is accepted by default only on loopback. Non-loopback
listeners require TLS certificate/key configuration unless the operator explicitly enables the
insecure development override. DNS-rebinding host/origin checks remain enabled.

The in-memory transport remains the fast deterministic test adapter. This MCP adapter is used when
the component boundary itself, authentication, reconnect behavior, or real network serialization
must be exercised.

## Windows Core to Kali Node smoke test

Use only an authorized lab target and a dedicated bearer credential.

1. On Kali, provision a TLS certificate whose subject/SAN matches the Node address, set
   `BOBERAGENT_MCP_TOKEN` in the Node process environment, and start the listener:

   ```shell
   uv run boberagent-node-mcp \
     --runtime-directory /var/lib/boberagent-node \
     --bind-host 0.0.0.0 --port 8443 \
     --tls-certificate /etc/boberagent/node.crt \
     --tls-private-key /etc/boberagent/node.key \
     --capability-path capabilities/network-service-discovery \
     --tool nmap=/usr/bin/nmap
   ```

2. Permit TCP/8443 only from the authorized Windows Core host. Do not expose the listener broadly.
3. On Windows, configure `McpClientConfiguration` with the explicit Node ID,
   `https://<kali-host>:8443/mcp`, the same bearer token, and the issuing CA path in `verify_tls`.
   Use `CoreMcpNodeConnection.connect_and_refresh()` to verify the handshake and refresh the Core
   provider registry.
4. Use the existing `CapabilityRouter` to explicitly dispatch a scoped test invocation. Pump
   `CoreTransportClient.flush_node()` / `receive_one()` until the terminal Result is acknowledged,
   then call `McpTransport.synchronize_artifacts()` with the existing Core Artifact receiver.
5. Confirm the Run, inbox record, synchronized evidence, and expected World State in Core. Restart
   either side once and confirm pending delivery resumes after a fresh handshake.
6. Stop the Node listener and remove the temporary credential when the test is complete.

For a disposable isolated lab only, `--allow-insecure-remote-transport` and the matching client
flag permit plaintext testing. That override is deliberate and must not be treated as a production
configuration.
