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
