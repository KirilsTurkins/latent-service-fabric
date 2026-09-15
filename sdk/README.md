# SDK surfaces

The external client SDK directories contain interface-only programming models.
The [Rust guest SDK](rust-guest/README.md) provides generated typed capability
bindings and ownership helpers for actual Wasm components;
[C guest fixtures](c-guest/README.md) validate generated ownership and ABI behavior.
See the [guest workflow](../docs/component-development/guest-sdk.md) for exact
profiles, signed admission and runtime validation.

WIT remains authoritative for typed capsule contracts. Language SDKs are convenience surfaces and must preserve deadlines, cancellation, platform errors, domain errors, resource budgets, identity, and idempotency semantics.

## Invocation identity and cancellation

Every SDK's invocation request carries optional activation, root activation, and
parent activation IDs. These map directly to Protobuf `InvokeRequest` fields
1â€“3. Supplying an activation ID lets a caller retain it before invoking and use
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

## Phase 2 management boundary

The operator CLI and generated Rust RPC clients expose package, release,
deployment, rollout and audit workflows. See the
[operator workflow contract](../docs/phase-2-operator-workflows.md) and
[completed Phase 2 gate](../docs/phase-2-completion.md). These additive management
RPCs do not change the six handwritten SDKs' invocation and guest interfaces;
their existing identity/cancellation fixtures remain required.

Capability/provider management models, usable Rust/TypeScript transports and
maintained guest capability bindings are planned in
[Phase 3 #201](https://github.com/KirilsTurkins/latent-service-fabric/issues/201).
None is implemented merely by the presence of a WIT package or a compiling SDK
interface. The node still exposes only its supported context/log/clock guest
imports; general providers, application ingress and browser/SSR execution remain
planned. Package and SDK release versions do not change the independently
versioned WIT and Protobuf contracts.

## Publication identity (Phase 3)

All six SDKs provide transport-neutral `PublicationRef` (ID and tenant),
`ReleaseSelector` (optional component digest or scoped publication), and
`PublicationIdentity` (publication, component and package) models. A corrected
embedded SBOM changes the package identity while retaining executable bytes;
the same package in two tenants has separate publications. These identities
must remain distinct from opaque invocation payloads and authorization grants.

A request boundary requires exactly one selector. The DTOs preserve absent,
present empty and contradictory values for validation; they never choose a
fallback, enumerate candidates, infer a tenant or pick the newest publication.
Rust uses the canonical typed PublicationId parser and rejects malformed IDs
before constructing that typed reference. Other interfaces retain strings for
the future transport validator. `ReleaseSelector.componentDigest` maps to the
specific RPC's legacy digest field; it is not an alternative wire schema.

Successful responses and common invocation receipts add an optional captured
publication ID, mapping to InvokeResponse field 10. The existing release digest
still denotes component bytes. Absence supports old servers and unresolved
failures; a present invalid ID must fail a real client's response validation.
Route/deployment selection chooses the publication; these models do not add a
direct Invoke publication selector. See [public API and migration](../docs/reference/publication-api.md)
for precise selector, recovery, lifecycle and compatibility behavior.

Rust struct literals need the new optional receipt field. Go keyed literals keep
nil defaults; TypeScript fields remain optional. Java retains old constructors
with Optional.empty; .NET retains old construction with a null default. Record
shapes and the C response/receipt layouts change: rebuild binary consumers and
producers together. No stable C ABI or executable management transport is claimed.
All six small contract suites exercise coexistence, distinct tenant scope,
legacy presence, present-invalid selection and full-width 64-bit receipt values.
The Phase 3 shared SDK profiles and real-client tickets consume these models
and authoritative RPC definitions; they do not define a second identity model.
