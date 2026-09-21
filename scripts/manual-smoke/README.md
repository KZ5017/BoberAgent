Manual cross-machine smoke tests only.

These scripts are not part of the automated pytest suite.
They require an explicitly running Kali Execution Node and lab configuration.
Do not execute them automatically from CI or normal test runs.

## Stateful browser smoke test

This procedure proves that one browser Session retains a cookie across separate MCP-delivered
Capability Runs. Use only an authorized lab. The HTTP fixture must be reachable from Kali and expose
two URLs on the same host:

- a `set` URL that responds with `Set-Cookie: browser_state=preserved; Path=/`;
- a `check` URL whose page title is `cookie-preserved` only when that cookie is received.

On Kali, install Chromium and the Python dependencies from the locked workspace, then run the Node
with the production capability and an explicit logical tool mapping:

```shell
export BOBERAGENT_MCP_TOKEN='<dedicated-test-token>'
uv run boberagent-node-mcp \
  --runtime-directory /var/lib/boberagent-browser-smoke \
  --bind-host 0.0.0.0 --port 8443 \
  --tls-certificate /etc/boberagent/node.crt \
  --tls-private-key /etc/boberagent/node.key \
  --capability-path capabilities/browser-interaction \
  --tool chromium=/usr/bin/chromium
```

From Core/WSL, use the Node ID printed by the listener and an explicit Core runtime directory:

```shell
export BOBERAGENT_MCP_TOKEN='<dedicated-test-token>'
uv run python scripts/manual-smoke/browser_state_smoke_test.py \
  --endpoint https://<kali-host>:8443/mcp \
  --node-id <node-id> \
  --core-runtime-directory /tmp/boberagent-browser-core \
  --asset-ref asset-browser-smoke \
  --set-url http://<fixture-host>:8080/set \
  --check-url http://<fixture-host>:8080/check \
  --ca-file /path/to/lab-ca.pem
```

For an isolated plaintext lab only, replace `--ca-file` with
`--allow-insecure-remote-transport`. The script performs `open → navigate(set) →
navigate(check) → close`, verifies `cookie-preserved`, and confirms a post-close navigation fails.
It never prints the bearer token. This is manual validation only; deterministic automated tests use
a controlled loopback server and do not require Kali or network access.

## Incoming TCP Session smoke test

This procedure proves asynchronous Session creation across real MCP without shell or payload
semantics. Choose an uncommon high port, bind the Kali interface explicitly, and authorize only
the controlled client's source IP. Ensure the lab firewall permits that single TCP path; these
scripts never change firewall configuration.

On Kali, start the Node with the production listener capability:

```shell
export BOBERAGENT_MCP_TOKEN='<dedicated-test-token>'
uv run boberagent-node-mcp \
  --runtime-directory /var/lib/boberagent-listener-smoke \
  --bind-host 0.0.0.0 --port 8443 \
  --tls-certificate /etc/boberagent/node.crt \
  --tls-private-key /etc/boberagent/node.key \
  --capability-path capabilities/network-listener
```

From Core/WSL, start the orchestration script. `--allowed-peer-address` must be the source address
Kali will actually observe for the controlled client:

```shell
export BOBERAGENT_MCP_TOKEN='<dedicated-test-token>'
uv run python scripts/manual-smoke/listener_session_smoke_test.py \
  --endpoint https://<kali-host>:8443/mcp \
  --node-id <node-id> \
  --core-runtime-directory /tmp/boberagent-listener-core \
  --bind-address <kali-interface-address> \
  --allowed-peer-address <controlled-client-source-address> \
  --port 45873 \
  --ca-file /path/to/lab-ca.pem
```

When it reports that the Listener is ready, run the bounded fixture client from the authorized
machine:

```shell
uv run python scripts/manual-smoke/listener_test_client.py \
  --host <kali-interface-address> --port 45873
```

The client sends only `hello-boberagent` and expects `pong-boberagent`. Core waits for the normal
`session.created` Event, performs separate `receive`, `send`, `close_session`, and `close_listener`
Capability Runs, then exits. No command interpreter, PTY, payload generation, or received-byte
execution is involved. For an isolated plaintext lab only, the Core script also accepts
`--allow-insecure-remote-transport` instead of `--ca-file`.
