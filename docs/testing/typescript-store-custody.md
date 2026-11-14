# Store custody and trusted runtime reuse disposition

Continuation for PR #1931, restacked without rewriting history onto parent
`5857840d85dc06e2658c5d8bcddda0103e2a2dce`. Earlier timer/import/queue fixes
already integrated into that parent remain unchanged.

## Implemented boundaries

The pinned Wasmtime `Store<T>::drop` destroys host data before instance backing.
`StoreCustody` instead consumes the Store once through `into_data`, retains the
original host data through that destruction path, then drops the original data.
It does not reconstruct tokens, mint a second budget, or invoke guest cleanup
after a Wasm trap. Fuel and memory observations precede destruction as before.
Custody begins immediately after Store construction, before fallible fuel and
event-loop setup. A setup error therefore follows the same destruction order
and cannot escape without its trusted retirement disposition.

Runtime finalization and Store destruction are distinct trusted facts. An
invocation-local, allocation-free `RuntimeRetirement` records both. A failed
finalization is sticky: later destructor refunds or a later successful check
cannot turn the earlier failure into a reusable result. Missing finalization,
incomplete destruction, and attempted proof reuse veto `ExecutionCleanup::Reusable`.
Guest trap strings cannot supply or suppress this evidence. Original outcomes,
consumption, host-result disposition, and earlier quarantine reasons are retained.

## Executed validation

The seven new test methods execute the pinned Wasmtime implementation, real table
allocation callbacks, and the original `ActivationRuntime`/`ActivationBudget`.
They cover on-demand and pooled allocation, ordinary return, an actual Wasm
`unreachable` trap, cancellation of a polled future, outer Rust unwinding, and
an actual engine fuel-setup refusal after allocation. A negative control
reproduces the old early Native-owner refund. The selected path retains that
owner until the actual table backing's allocation guard dies. A real refused
`ActivationRuntime::retire` remains a reuse veto after Store cleanup reduces its
owner count to zero. Tests also preserve existing quarantine and host-result
states and reject duplicate Store proof reuse.

Local Rust 1.97.1, locked/offline build:

```sh
cargo test -p latent-wasmtime --locked --offline --lib backend::store::tests
LSF_TEST_STREAM_OUTERS_COMPONENT=/path/to/native-stream-outers.wasm \
  cargo test -p latent-wasmtime --locked --offline --lib
```

The focused selection passed all seven tests. The final library selection passed
499, failed zero, and retained 11 existing ignored tests. These are observed
counts, not a required inventory. The missing stream fixture from the earlier
attempt was parsed from the unchanged maintained WAT using the retained JCO
toolchain; no assertion or library test was disabled. `git diff --check` passed.

Source scope matters: the local checkout was recovered from authenticated
`12a40da53ce33e2ef297892b8e0a9b09f327adcc` history. Each modified production-file
preimage was separately matched to the current parent Git blob, including the
four-line development timer witness in backend.rs. Adjacent files used the
recovered checkout. The complete current parent, all-feature closure, formatter,
signed SpiderMonkey component and final remote CI were not qualified by this
local run. Uploaded modified file blobs matched the tested bytes.

## Remaining physical boundary

`into_data` is a normal backing-destruction ordering fix, not an OS decommit
acknowledgement. The pinned pool still has failed-decommit fallback behavior;
a Cell quarantine disposition alone does not retain its original Store and all
reservations. Failed-decommit custody/retry still needs separate engine-owner work and
fault injection. Destructor-internal panic retention is addressed below. The new trusted veto prevents
an actual logical-finalization refusal from being silently treated as reusable,
but it does not fabricate proof for those physical paths. Complete aggregate
byte attribution and signed cross-tenant/GC qualification are not asserted.

No owner ceiling, grant, deadline, profile-support flag or issue acceptance
checkbox is changed. This report supersedes the earlier claim that no Store
ordering or trusted runtime-finalization veto had been implemented; it does not
close the remaining physical and signed-execution obligations.

## Consuming teardown panic continuation — 2026-11-11

The pinned engine's old `into_data` moved `T` into an ordinary local before
calling `drop(inner)`. A panic from an engine allocation destructor therefore
dropped that local and refunded original host owners without proving physical
retirement. A second earlier hazard allowed a panic in manual cleanup to enter
ordinary Store destruction and repeat cleanup while unwinding.

The consuming API now enters `ManuallyDrop` before manual cleanup and retains
`T` in `ManuallyDrop` through all subsequent engine/guard destruction. It returns
`T` only after those operations complete. The existing invocation-local trusted
witness remains incomplete if any operation panics; catching a panic cannot
claim reusable state. No new ledger, token, heap queue, grace period, owner
ceiling, or guest cleanup operation is introduced. Retention after catastrophic
teardown is terminal, not retryable reclamation or a successful OS decommit.

A new actual-engine fault-injection test first reproduced the old early refund
(original Native count zero after a physical table-allocation destructor panic).
The corrected source passes the same test with both pooled and on-demand
allocation: the original owner stays live, actual allocation destruction is
attempted once, and reuse remains quarantined even after a later logical check.
The engine in this catastrophic test is deliberately retained; a partially
interrupted allocator cannot safely be torn down a second time. The existing
seven Store controls still pass. The complete source used for this continuation
is the authenticated archive of `b670f5239d74a325815563d32d15f1f11d9f7f33`,
with its current locked registry and Rust 1.97.1. Vendored crate bytes, cumulative
upstream patch, and the v38 native cohort are bound by updated exact identities.

On the final continuation source, the focused Rust selection passed eight tests,
the complete `latent-wasmtime` library passed 508 tests with zero failures and
11 pre-existing ignored tests, and all 15 vendor source-integrity tests passed.
The unchanged stream-outers WAT was parsed with retained JCO 1.34.0 tooling for
this local run; this does not relabel it as the workflow's pinned wasm-tools
1.254.0 execution. These counts describe observed runs, not required inventories.
