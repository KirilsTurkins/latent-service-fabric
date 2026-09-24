# Activation-scoped capabilities

The generic Wasmtime backend supplies four built-in imports: `latent:context/context`,
`latent:log/log`, `latent:clock/monotonic`, and `latent:clock/wall`, all at version
`0.1.0`. They are explicit Component Model imports supplied to a fresh store for
each activation. Preparation verifies the component's declared surface, and an
invocation must bind exactly its prepared imports. No WASI filesystem,
environment, network, process, or other ambient authority is installed. The
configured [local service adapter](local-service-invocation.md) additionally
implements canonical async `latent:service/invoke@0.1.0`. The configured
[outbound HTTP adapter](outbound-http.md) implements `latent:http/client@0.2.0`; [streaming HTTP](streaming-http.md) adds
`latent:http/streaming@0.3.0` with owned upload/body/chunk resources. The Linux
[local blob provider](local-blobs.md) and [S3 provider](s3-blobs.md) implement `latent:blob/blob@0.2.0` with
scoped durable references and owned read chunks. The configured
[local](local-secrets.md) and [Vault KV-v2](vault-secrets.md) secret providers implement `latent:secrets/reader@0.1.0`
with protected sources, atomic rotation and separate opaque provider credentials.
[NATS JetStream publication](nats-events.md) implements immediate `latent:events/publisher@0.2.0` with broker receipts and explicit uncertainty.
[Cryptographic randomness](random.md) implements both `latent:random/random@0.1.0` methods through the activation broker and original ledger.
[Custom metrics](custom-metrics.md) implements all four `latent:telemetry/custom@0.1.0` kinds through a shared bounded registry and exporter.
Package delivery, native caching and rollout control do not expand this guest
import set. The [versioned host ABI profile](host-abi-profile.md) defines the
supported contract versions.
Package inspection recognizes its exact provider contracts and selected async
imports, while preparation rejects providers without installed owners. The [sealed activation broker](capability-broker.md) now implements session,
handle and call ownership and can gate the four built-in imports in explicit
managed embeddings. [Exact plan compilation](capability-bindings.md) and
conserved [descendant budgets](descendant-budgets.md) support local child calls.
The [standalone bootstrap](../reference/standalone-providers.md) installs the
supported HTTP/local-blob configuration and exposes scoped provider management.
Other concrete adapters use their documented trusted Rust compositions; declaring
their contracts does not install them through standalone configuration. Start with
[the capability walkthrough](../learn/use-capabilities.md) to exercise the actual
configuration, allowed and denied operations, revocation and cleanup.

The [bounded asynchronous I/O substrate](async-host-io.md) now adds affine queue,
buffer and stream ownership on the existing runtime. Cancellation retains charges
for actual work and delayed consumers; waiting never refunds an execution cell.
Its real async guest conformance fixture does not expand the production import set.
The [shared provider pools](provider-pools.md) add configured client reuse,
tenant/provider fairness, credential epochs, connection limits and bounded
worker/cleanup shutdown. They run on the node's existing control runtime.

The delivered [durable capability policy owner](capability-policies.md) provides
bounded rules, scoped revisions, provider-binding metadata and authenticated
apply/get/list/revoke/explain control. Sealed decisions recheck policy and
publication authority at final admission. This control foundation does not itself
install the remaining guest providers.

[Capability audit and inspection](capability-audit.md) records required provider
attempts and typed outcomes through the existing audit owner. Scoped management
reads explain compiled grants and retained resources without granting execution
permission or exposing credential-bearing selectors.

The [local activation manager](../activation-lifecycle.md) supplies these
capabilities with the activation's shared accounting owner inside the delivered
[standalone node](../reference/standalone-node.md). The standalone provider
configuration and application ingress remain distinct authority boundaries. Transactional
state/effects, cluster transport and durable workflow suspension are not
implemented; declared WIT alone makes none of them callable.

## Immediate provider operations

[ADR-0025](../../adr/0025-separate-immediate-capability-operations-from-transactional-effect-intents.md)
defines the semantic mode for external providers. HTTP, blob and event
operations are immediate activation-scoped capability calls, not application
state transactions or durable effect intents. Provider contracts must distinguish
rejection before dispatch, provider acknowledgement, known provider failure and
uncertain outcome after possible dispatch wherever the underlying protocol can
support that distinction.

Cancellation and deadline expiry stop work that LSF still controls. Once an
external operation may have been dispatched, they cannot prove that the remote
effect did not occur. A lost acknowledgement therefore cannot be rewritten as a
definite failure or used to justify automatic replay of an uncertain mutation.
An idempotency key is an input to an explicit provider retry/deduplication policy;
it is not permission for a hidden retry.

Provider acknowledgement is also narrower than application completion. An HTTP
response, blob-provider acknowledgement or broker publication receipt does not
by itself prove downstream consumer processing, invocation success, a guest-state
commit or end-to-end exactly-once execution. Audit observations report what LSF
observed; provider cleanup/recovery records retain provider-owned work. Neither is
an application transaction or outbox receipt.

Buffered/streaming HTTP, local/S3 immutable blobs, local/Vault secrets and
immediate NATS publication preserve these distinctions in their typed results
and cleanup. Inbound consumer
triggers are implemented by the [shared JetStream poller](nats-triggers.md).

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
reclamation, dormant-release scale, or complete runtime conformance evidence in
the [validation contract](../../VALIDATION.md).
