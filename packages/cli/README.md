# boberagent-cli

Thin operator-facing command line over public BoberAgent Core services. See the repository root
README for setup and operator examples.

Durable human interactions are inspected and answered through the same explicit Core database:

```shell
boberagent --database /path/to/core.sqlite3 interaction list
boberagent --database /path/to/core.sqlite3 interaction show <interaction-ref>
boberagent --database /path/to/core.sqlite3 --node-url https://node.example/mcp \
  --node-id node-example interaction respond <interaction-ref> --yes
```

`respond` accepts exactly one of `--yes`, `--no`, `--text`, or `--choice`; Core validates it against
the stored request before transport delivery. Use `--json` before the command group for stable
machine-readable output. Text responses are ordinary non-secret input and must never be used for
credentials. The CLI calls `CoreInteractionService`; it contains no duplicate lifecycle or
resumption logic.

Secret and Credential commands show metadata by default:

```shell
boberagent --database /path/to/core.sqlite3 secret list --mission mission-example
boberagent --database /path/to/core.sqlite3 credential list --mission mission-example
boberagent --database /path/to/core.sqlite3 credential show credential-example \
  --mission mission-example
```

Actual values appear only through an explicit reveal command. Text is the default; use
`--encoding base64` for binary material.

```shell
boberagent --database /path/to/core.sqlite3 secret reveal secret-example \
  --mission mission-example
boberagent --database /path/to/core.sqlite3 credential reveal credential-example \
  --mission mission-example --role password
```

Reveal output is intentionally sensitive, including in `--json` mode. It should be redirected and
handled accordingly. Ordinary list/show, workflow, Run, and status output never resolves values.
M16 does not accept plaintext Secret creation on the command line, avoiding routine shell-history
exposure.
