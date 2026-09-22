# SDK surfaces

Start with [Invoke, cancel and recover with a client SDK](../docs/learn/use-a-client.mdx)
for the shared six-language learning path, native setup and source-backed examples.

The six maintained external clients now implement the common bounded
numeric-loopback HTTP/2 + Protobuf transport on Linux x86-64. Their separately
owned real-node qualification and full PR CI completed in
[PR #366](https://github.com/KirilsTurkins/latent-service-fabric/pull/366).
Use each SDK's instructions for toolchain, resource ownership and generation;
this does not imply published packages, remote node listeners or guest runtimes.

| Client | Shipped transport and native build | Language-specific ownership |
| --- | --- | --- |
| Rust | [Generated RPC client](rust/README.md) | Retain activation IDs across dropped futures; await bounded shutdown. |
| TypeScript | [Node client](typescript-client/README.md) | Bigint/presence, AbortSignal and explicit shutdown; browser application ingress is separate. |
| Go | [Native client](go/README.md) | Context deadlines, live recovery contexts and bounded Close. |
| C | [Linkable native library](c/README.md) | Copied retained requests, callback lifetimes, call release and stop/drain. |
| Java | [Native client](java-client/README.md) | Lossless unsigned values, local future cancellation and owned channel/executor closure. |
| C#/.NET | [Native client](dotnet/README.md) | Live recovery tokens, single-consumption ValueTask and async disposal. |

The external client SDK directories separate portable programming models from
executable transport packages. Rust network delivery and its transport-specific
documentation are tracked in [#228](https://github.com/KirilsTurkins/latent-service-fabric/issues/228);
model validation alone does not establish transport readiness.
The [common executable client profile](profile/README.md) supplies a complete,
protobuf-derived eight-operation facade in all six languages, including policy,
redacted provider inspection, preconditioned mutation and recovery. Its models
and fast semantic fixtures are separate from the network implementations owned
by Rust #228, TypeScript #230, Go #260, C #261, Java #262 and .NET #263.
The [Rust guest SDK](rust-guest/README.md) provides generated typed capability
bindings and ownership helpers for actual Wasm components;
[C guest fixtures](c-guest/README.md) validate generated ownership and ABI behavior.
See the [guest workflow](../docs/component-development/guest-sdk.md) for exact
profiles, signed admission and runtime validation.

WIT remains authoritative for typed capsule contracts. Language SDKs are convenience surfaces and must preserve deadlines, cancellation, platform errors, domain errors, resource budgets, identity, and idempotency semantics.

Go, .NET, Java and TypeScript use their complete profile interfaces and native transport
clients. Their obsolete invocation models, compatibility constructors and
adapters have been removed. The older interfaces described below still apply only to their
remaining language-specific implementations.

## Java SDK runtime compatibility

| Surface | Build and minimum runtime | Qualification boundary |
| --- | --- | --- |
| Java models, native RPC transport and examples | Java 25; repository builds use exact Eclipse Temurin 25.0.4.1+1 | Existing Linux CI owns semantic/transport and separate-node evidence; native generators also exist for Windows x86-64, which is not by itself runtime qualification. |

The [Java SDK](java-client/README.md) now emits non-preview Java 25 class files
(69.0), not Java 21-compatible bytecode. Applications adopting the new JAR must
upgrade their Java build/runtime first; no public model or wire semantics change
as part of this toolchain migration. The repository pins an exact Temurin build
for validation rather than claiming every Java 25 distribution or later JDK is
qualified. Historical Java 21 evidence and Windows tests that used
`--release 21` do not establish Java 25-targeted Windows support.

The standalone Python/JDK build still needs no Gradle or Maven. The optional
Gradle path requires Gradle 9.1.0 or newer, uses the exact `JAVA_HOME` installation
and is checked alongside the standalone path by existing SDK CI. See
[toolchain setup and migration](../docs/development/toolchain.md#java-25-sdk-baseline-and-migration)
for exact pins, commands, class-file checks and retained evidence locations.
This changes an external client baseline, not the Rust node or guest runtimes.

## Invocation identity and cancellation

Every SDK's invocation request carries optional activation, root activation, and
parent activation IDs. These map directly to Protobuf `InvokeRequest` fields
1Ã¢â‚¬â€œ3. Supplying an activation ID lets a caller retain it before invoking and use
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
identity and lineage rules. The shared profile includes executable test doubles;
network packages and their separate delivery evidence
determine which executable clients are available.

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

### Legacy C callback contract

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

The additive `<latent/profile.h>` facade has explicitly released local call
handles and its own [callback lifetime contract](profile/README.md#c-callback-and-response-lifetime).
Do not mix its handle ownership with the legacy interface described here.

### Alpha API changes

Obsolete invocation facades have been removed from Rust, Go, TypeScript, Java
and .NET. Recompile integrations against the complete shared profile; no
compatibility alias or deprecation waiting period is provided. Rebuild C
producers and consumers together whenever its public layouts change. No stable
C ABI is claimed, and no Protobuf field numbers or types change in this cleanup.

## Executable contract fixtures

The [.NET transport](dotnet/README.md) implements the complete native profile
with one bounded owned HTTP/2 connection.
Its [retained qualification](dotnet/EVIDENCE.md) separates the original
controlled-peer checks from an actual 18-assertion separate-node provider run.
The current profile-only transport suite passes 518 controlled-peer checks. It is a Linux host
client, not a .NET guest binding. The maintained six-language real-node gate
completed in PR #366; subsequent changes still require fresh matching validation.

`tools/validate_sdks.sh` compiles and runs the Go, TypeScript, Java, .NET and
C contract suites. Rust equivalents run through `cargo test -p latent-sdk`.
The current shared profile exercises identity presence, explicit lineage,
local cancellation, response ownership and recovery. Controlled native TCP
suites separately prove bounded transport behavior. The Rust suite retains all
ten transport lifecycle scenarios on `management::ClientProfile`, including
lost-response recovery, distinct outcomes, capacity, deadlines and shutdown.
Model fixtures establish representable values; transport validation rejects
present-invalid requests without normalizing them into absence.

The shared Phase 3 suite contains 67 protobuf-selected vectors, 16 strict unsigned
decimal boundaries, and local cancellation/response ownership/recovery fixtures
in every language. The existing runners execute these suites, including ordinary
public Rust crate tests. See the [profile validation commands](profile/README.md#executable-semantic-fixtures)
and [bounded local evidence](profile/EVIDENCE.md) for exact coverage and limits.

## Management boundary

The operator CLI and generated Rust RPC clients expose package, release,
deployment, rollout and audit workflows. See the
[operator workflow contract](../docs/phase-2-operator-workflows.md).
The [shared client profile](profile/README.md) is the SDK entry point for
invocation, policy, provider inspection and operation recovery. Its error model
retains raw RPC status, dispatch uncertainty, activation/operation IDs and
independent audit facts. Package and SDK versions do not change independently
versioned WIT and Protobuf contracts.

## Publication identity (Phase 3)

All six SDKs provide transport-neutral `PublicationRef` (ID and tenant) and
`PublicationIdentity` (publication, component and package) models. A corrected
embedded SBOM changes the package identity while retaining executable bytes;
the same package in two tenants has separate publications. These identities
must remain distinct from opaque invocation payloads and authorization grants.

Management requests select an exact publication in their authenticated tenant.
The obsolete component-or-publication `ReleaseSelector` has been removed from
both the handwritten facades and the generated common profile. Component
checksums identify bytes and cannot replace a publication reference.

The common profile retains raw strings for explicit boundary validation.
Rust response validation uses the canonical PublicationId parser. No facade
normalizes an invalid ID or infers authority from it.

Successful responses and common invocation receipts add an optional captured
publication ID, mapping to InvokeResponse field 10. The existing release digest
still denotes component bytes. Absence represents unresolved
failures; a present invalid ID must fail a real client's response validation.
Route/deployment selection chooses the publication; these models do not add a
direct Invoke publication selector. See [public API and recovery](../docs/reference/publication-api.md)
for precise selector, recovery, lifecycle and compatibility behavior.

The shared contract vectors exercise coexistence, distinct tenant scope,
publication absence and full-width 64-bit receipt values. Executable clients
also reject invalid returned publication IDs. These models consume the
authoritative RPC definitions; they do not define a second identity model.
