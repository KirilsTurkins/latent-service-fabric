# Existing-v1 readiness completion

This correction applies to the existing stream provider, independently of the
[uninstalled nonblocking companion](nonblocking-v2-decision.md). It changes no
WIT signatures, endpoint grants, production installation gates, resource limits,
transport selection, or supported readiness events.

## The completion boundary

A physical readiness observation is not permission to return a successful result
before its required audit and authority checks finish. The original waited-ready
path and the buffered-TLS shortcut finalized the audit but did not use the final
currentness fence already used by immediate and elapsed observations. Audit
finalization itself does not revalidate authority.

All successful readiness paths now use `complete_readiness_observation`. Its
existing `ReadinessFlight` retains the accepted `ready` call and its original
pending socket through audit. Before returning, the provider checks both the
original connect authority and the independently accepted readiness authority,
plus cancellation, connection state and the original effective lifetime. The
physical observation's `HostCompleted` audit outcome does not grant permission
to hand it off after revocation or expiry.

An audit failure or failed final check fences the same connection. Dropping a
suspended completion also fences it before releasing either owner. Other live
operations still retain their original socket and ledger charges until they
retire; this is not early cleanup, a replacement connection, or a new allowance.
A successful observation releases its own waiter without consuming application
bytes or renewing the connection's idle deadline.

## Focused regression command

From the repository root with the pinned Rust toolchain:

```console
cargo test -p latent-streams --lib --locked -- connection::readiness_tests:: --nocapture --test-threads=1
```

The required runtime contract lane runs this selection separately from the full
workspace suite. The controls use the maintained provider, sealed broker policy,
and real loopback TCP peers. A deterministic test-only audit gate holds a
successful writability observation while policy revocation, abandonment, audit
failure, or original idle expiry occurs. An unpolled read remains live to check
that the physical socket and its charges cannot retire early. Positive controls
check waiter reuse, unchanged idle time and a single original connection.

The gate and injected audit failure are doubles. These controls do not execute a
durable journal, a signed guest, libcurl, the buffered-TLS shortcut, or a
protected/q35 backend. They are not qualification for the proposed companion,
all post-audit transfer paths, or mixed C file/socket descriptors. Broader backend
and ordinary-library qualification remains subject to the proposal's owner
review and acceptance gates.
