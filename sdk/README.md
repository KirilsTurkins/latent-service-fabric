# SDK surfaces

The SDK directories contain interface-only client and guest programming models. They do not contain transports, serializers, retry logic, code generation, or runtime integration.

WIT remains authoritative for typed capsule contracts. Language SDKs are convenience surfaces and must preserve deadlines, cancellation, platform errors, domain errors, resource budgets, identity, and idempotency semantics.

## Invocation identity and cancellation

Every SDK's invocation request carries optional activation, root activation, and
parent activation IDs. These map directly to Protobuf `InvokeRequest` fields
1–3. Supplying an activation ID lets a caller retain it before invoking and use
it for cancellation or status while the invocation response is still pending.
The ID is a correlation identifier, not an idempotency key or authorization
credential. A lost response does not establish whether execution happened;
query retained status using the original ID rather than automatically invoking
again. Status retention is bounded, so `not-found` does not prove that an
activation never ran.

| Request value | Contract |
| --- | --- |
| Activation ID absent | The server assigns the effective activation ID. The SDK preserves absence and generates nothing. Without another receipt, the caller cannot identify this pending invocation by ID. |
| Activation ID present | Preserve the exact caller value for server validation and collision handling. Accepted invocation receipts and status use that identity. |
| Any ID present but empty | Present-invalid, never equivalent to absence. The SDK model preserves presence; the server rejects the malformed request. |
| Parent and root absent | A new root invocation uses its effective activation ID as its root. |
| Root and parent present | Preserve both lineage claims exactly. The server validates them against trusted context; they grant no authority. |
| Parent present without root | Phase 1 rejects this incomplete lineage; adapters must not guess a root from caller metadata. |
| Root present without parent | Preserve it for server validation; this does not authorize joining another invocation tree. |

The delivered [activation manager](../docs/activation-lifecycle.md) and
[invocation adapter](../docs/protocol/invocation-service.md) enforce these server
identity and lineage rules. The SDKs provide interfaces and executable test
doubles; applications still need a transport implementation.

All six client surfaces cancel and query status by known activation ID.
Cancellation has three successful RPC dispositions: `accepted`,
`already-terminal` with its terminal state, and `not-found`. `accepted` means
the request was accepted, not that cleanup has finished. RPC transport failures
use the separate error channel and must never be translated into a disposition.
Stopping a local future, context, signal, task, or callback wait is not proof of
server cancellation. Only an explicit cancellation response confirms its
disposition; automatic cancellation forwarding and retry policy are outside
these interfaces.

The [extension's caller-budget guidance](../docs/phase-1-extension-completion.md#tuning-and-closure)
distinguishes useful responses, deadline misses and eventual cleanup.
Its benchmark client results do not add transports, automatic cancellation
forwarding or retries to these SDK interfaces.

### C callback contract

The C vtable's `cancel` takes an activation ID, reason, callback, and user data.
Its callback receives exactly one of a cancellation response or transport
error. The opaque `latent_invocation` returned by `invoke` identifies a local
operation for callback correlation; it is not a persistent activation ID and
is no longer accepted by cancellation. Callers never dereference or free the
handle, and must not use it after its completion callback returns.

Request data, IDs, and reasons are borrowed for the duration of the method call. An asynchronous
implementation must copy everything it retains. Response/error values and
their nested pointers are borrowed until the callback returns; callers copy
anything they retain. Callbacks may run inline. The implementation must deliver
one completion callback per operation, including transport failure. Client and
user-data lifetime must cover outstanding callbacks; `destroy` requires those
operations to have completed.

### Compatibility

This is a pre-stabilization source/ABI correction. Rust struct literals need
the three new `Option<ActivationId>` fields; Go unkeyed struct literals need
updating, while keyed literals retain nil defaults. TypeScript fields are
optional. Java and .NET retain the old construction form with absent identity,
but the record shape changes affect generated accessors, equality,
deconstruction/reflection, and binary consumers; recompile integrations.

C request layout and the vtable cancellation signature change. Rebuild every
producer and consumer together, update cancellation implementations and calls
to the ID/callback form, and do not mix old and new binaries. No stable C ABI
compatibility is claimed. No Protobuf field numbers or types change.

## Executable contract fixtures

`tools/validate_sdks.sh` compiles and runs small Go, TypeScript, Java, .NET, and
C fake-client fixtures. Rust equivalents run through `cargo test -p latent-sdk`.
They exercise pending invocation with status/cancel by caller ID, all three
cancellation dispositions, transport failure, status after a lost invocation
response without reinvoking, absent/server-assigned identity, explicit lineage,
and present-empty identity. Each fake deliberately holds invocation completion
until the assertions before completion have run; no network server or long
workload is required. These checks establish that the interface can express the
contract. Actual wire conversion and server behavior are covered separately by
the invocation adapter tests and the completed
[Phase 1 conformance gate](../docs/phase-1-completion.md).
