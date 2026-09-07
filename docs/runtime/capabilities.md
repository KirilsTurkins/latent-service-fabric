# Activation-scoped capabilities

The generic Wasmtime backend implements four imports: `latent:context/context`,
`latent:log/log`, `latent:clock/monotonic`, and `latent:clock/wall`, all at version
`0.1.0`. They are explicit Component Model imports supplied to a fresh store for
each activation. Preparation verifies the component's declared surface, and an
invocation must bind exactly its prepared imports. No WASI filesystem,
environment, network, process, or other ambient authority is installed. The
remaining platform capability packages are contracts for later implementation.

These Rust APIs are building blocks for activation orchestration. They do not
provide the standalone node, public invocation service, or a capability broker
for later-phase state, network, secrets, or child-call access.

## Context disclosure

Identity, lineage, authenticated principal identity, core trace fields, and the
effective deadline come from the pinned activation envelope and its admission
budget. The guest cannot replace these fields through metadata or log fields.
Lineage alone does not grant authority. Mutable context is never retained for
the next occupant of a reused execution cell.

`WasmtimeConfig.context_policy` is a `ContextExposurePolicy` with three public
lists. Defaults expose metadata whose key starts with `guest.` and expose no
principal claims or trace baggage. Metadata keys keep their complete namespace.
`metadata_prefixes` selects case-sensitive prefixes; `claim_keys` and
`baggage_keys` select exact, case-sensitive keys. An empty list exposes nothing
from that map. The policy does not remove pinned identity, principal
subject/kind/tenant/service, trace ID/span ID, or trace flags.

Each policy list permits at most 32 distinct nonempty entries, each at most 256
UTF-8 bytes without control characters. Factory creation rejects invalid policy.
The exposure policy participates in preparation compatibility. Request context
also has a bounded allocation allowance checked before its strings and maps are
cloned into host state. Operators should deliberately select guest-visible
metadata and allowlist claims/baggage for the intended workload.

## Clocks and live accounting

`WasmtimeHostServices` supplies an `Arc<dyn ActivationClock>` and an optional
structured log sink. `WasmtimeComponentEngineFactory::with_host_services` accepts
these node-owned dependencies; the ordinary constructor uses the system clock
and bounded capture. The same clock abstraction is available in `latent-core`
and reexported by `latent-node` for existing callers.

The monotonic capability reports elapsed nanoseconds from an origin sampled once
by the node factory. Values saturate at `u64::MAX` and clamp backward observations
within that activation. A fresh activation shares the origin and has fresh clamp
state, so it can observe a lower value after an injected clock regression. Wall
time reports Unix milliseconds and may move backward after a clock adjustment;
it is not the elapsed-time or deadline source. Admission and execution must use
the same monotonic clock domain. An injected clock makes those distinctions
testable without waiting for time to pass.

Terminal wall-time consumption uses this same monotonic clock. Runtime profiling
timings measure real process elapsed time independently of injected test clocks.

`remaining-budget` observes the live activation ledger, current store fuel, and
aggregate observed memory. CPU and memory consumption already incurred by the
guest reduce the result; accepted log bytes reduce the same ledger immediately.
Remaining wall time follows the original effective monotonic deadline. It does
not restart at guest entry or after a host call.

An activation owner supplies its existing `ActivationBudget` through
`ExecutionCancellation::budget_accounting`. This shares accounting with the
capabilities and terminal reconciliation. Direct backend callers that omit the
ledger get one local fallback ledger. The backend reports consumption and cleanup;
the activation owner performs terminal finalization. No separate guest-visible
budget grants additional resources.

## Structured log acceptance

The host validates the message and guest fields before publication. Messages
are limited to 256 UTF-8 bytes, guest field counts to 16, names to 64 bytes, and
values to 256 bytes. Names must be nonempty ASCII letters, digits, underscore,
hyphen, or period. Duplicate names are invalid.

The case-insensitive `latent.` namespace is reserved. The host adds trusted
`latent.activation_id`, `latent.trace_id`, and `latent.span_id` fields. An
unprefixed `activation_id` field is ordinary guest data, preserving the retained
echo fixture's convention without making that field authoritative.

Log-byte accounting charges the complete compact UTF-8 JSON record in this
top-level field order:

```json
{"activation_id":"a","level":"info","message":"m","fields":{"latent.activation_id":"a","latent.span_id":"s","latent.trace_id":"t"}}
```

Fields are sorted by key. The charge includes names, punctuation, escaped string
bytes, and trusted correlation, with no trailing newline. The activation log
budget and configured per-invocation entry/byte limits must all admit the record.
Invalid fields and exhausted limits return typed WIT failures and publish nothing.

A custom `StructuredLogSink::try_emit` receives the `CapturedLog` and those exact
encoded bytes. Implementations must make a bounded, nonblocking acceptance
decision. Returning `LogSinkError::Unavailable` becomes the WIT `unavailable`
error, refunds the reservation, and leaves bounded capture unchanged. After
custom acceptance, or when using the default sink, the host commits the charge
and records the accepted log in bounded node capture. `write` success means
acceptance by that sink; it does not establish external durable delivery.
`factory.log_sink()` and backend snapshots expose bounded accepted capture.

## Focused validation

`tools/validate_contracts.sh` builds a separate maintained Rust/WIT capability
component and runs `capabilities_backend`. Its small tests cover default and
explicit context filtering, pinned identity across cell reuse, live fuel/memory
and log accounting, backward wall adjustments, monotonic clamping/reset, escaped
record byte boundaries, reserved/invalid fields, sink rejection/refund, missing
clock grants, and actual imports from nine unavailable capability families.
Each invocation has a five-second watchdog and checks resource cleanup.

After the contracts gate has built the fixture, run it directly with:

```bash
LSF_CAPABILITIES_COMPONENT=target/capsules/capabilities/capabilities-capsule.wasm \
  cargo test -p latent-wasmtime --test capabilities_backend --locked -- \
    --ignored --nocapture --test-threads=1
```

These are bounded semantic regressions. They do not establish the long-running
reclamation, dormant-release scale, or complete Phase 1 conformance evidence in
the [validation contract](../../VALIDATION.md).
