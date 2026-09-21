# `network.listener`

`network.listener` proves asynchronous incoming Session creation without adding shell semantics.
The `open` operation creates a Mission-owned `tcp_listener` Resource and completes immediately.
When an explicitly authorized peer connects later, the Execution Node creates a distinct
`tcp_stream` Session and persists a `session.created` Event through the ordinary Event outbox.

Supported operations are `open`, `inspect`, `receive`, `send`, `close_session`, and
`close_listener`. `receive` and `send` exchange opaque bytes only, use exclusive Session leases,
enforce a 64 KiB per-operation bound and a 30-second maximum timeout, and represent Result bytes as
canonical base64. They never interpret bytes as commands or automatically store stream contents.

Bind scope, peer scope, and ownership are separate checks:

- the bind address must be an explicit projected IP address; wildcard binds are rejected;
- each allowed peer must be an explicit projected IP address and is checked again on accept;
- later Session operations require matching Mission/Workflow/Run provenance and projected peer
  authorization.

One listener accepts up to the configured bounded number of simultaneous Sessions (maximum 32).
Excess or unauthorized connections are closed and produce a metadata-only `session.rejected`
Event. Closing one Session does not stop the listener. Closing the Listener closes all dependent
live Sessions and stops its accept tasks.

Sockets and asyncio tasks remain entirely inside the Execution Node. Only safe logical metadata is
persisted; application bytes are not. After an unclean Node restart, non-terminal listener and
stream records become `LOST`; the Node never silently rebinds or claims that TCP state survived.

M14 does not provide a shell, payload generation, PTY, terminal emulation, UDP, firewall changes,
automatic callbacks, event-triggered Workflow continuation, or World State materialization.
