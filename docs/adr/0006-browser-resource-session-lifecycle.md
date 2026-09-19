# ADR 0006: Browser Resource and non-restorable Session lifecycle

- Status: Accepted for Milestone 13
- Date: 2026-09-19

## Context

The first stateful capability must preserve browser cookies and navigation state across separate
Capability Runs while maintaining the architecture's distinction between runtime infrastructure
and interaction state. Playwright objects and browser state are process-local, can contain
sensitive material, and cannot be reconstructed honestly from logical database records after a
Node crash.

## Decision

The Execution Node owns a `browser_process` Resource and a separate `browser` Session. M13 uses one
dedicated Resource per Session. This keeps ownership, exclusive access, cleanup, and failure
handling deterministic while leaving the generic Contract and SDK capable of other provider
models later.

The Node persists stable Resource/Session refs, ownership, lifecycle, timestamps, supported access
modes, and safe lifecycle metadata. Cookies, local storage, credentials, page contents, and
Playwright handles remain exclusively in the live browser context. A Session is therefore stateful
across Capability invocations while its Node process remains alive, but it is intentionally not
restart-restorable.

Node startup changes any surviving non-terminal browser Resource or Session record to `LOST`.
It does not launch a replacement browser or claim that authenticated state survived. Graceful
close is idempotent: closing a Resource closes its dependent Session before terminating the
runtime. The first implementation supports exclusive access and one Session per Resource.

Playwright is an Execution Node dependency hidden behind the SDK's semantic `BrowserSession`
protocol. The logical `chromium` tool must be configured explicitly; normal invocation never
downloads browser binaries. Browser navigation accepts only HTTP(S), checks the projected scope,
and installs request interception so an out-of-policy redirect or subrequest is blocked.

## Consequences

- Core, transport, capability contracts, and the production capability remain independent of
  Playwright.
- Logical identity and lifecycle survive restart, but live sensitive browser state does not.
- Reusing a closed or lost Session fails explicitly; no replacement Session is created silently.
- Browser inspection evidence uses the existing bounded Artifact path.
- Multi-Session Resources, persistent browser-profile restoration, proxy orchestration, crawling,
  arbitrary JavaScript, and distributed leasing remain deferred.
