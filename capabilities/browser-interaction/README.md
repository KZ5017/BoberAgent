# `browser.interaction`

The first stateful BoberAgent capability creates and operates a managed headless browser without
exposing Playwright as the platform identity. It supports `open`, `navigate`, `inspect`, and
idempotent `close` operations.

`open` creates one dedicated `browser_process` Resource and one browser Session. Later invocations
use the returned `SessionRef`; cookies, local storage, pages, and Playwright objects remain only in
the live Node process. `navigate` accepts only HTTP(S) URLs whose normalized host is authorized by
the invocation scope, and the driver blocks redirects that leave that host. `inspect` preserves a
bounded HTML snapshot through the normal Artifact spool.

M13 deliberately uses one browser Resource per Session. This makes ownership and cleanup
deterministic while proving independent Resource/Session identity. A Node restart cannot restore
the live browser context, so persisted non-terminal browser Resources and Sessions become `LOST`;
authenticated state is never silently reconstructed. Chromium must be provisioned explicitly and
registered as the Node's logical `chromium` tool. Browser downloads never occur during invocation.

This capability is not a crawler, does not execute arbitrary JavaScript, and does not perform
autonomous web assessment.
