# Common executable client profile v1

`latent.client.v1` is the common contract for Rust #228, TypeScript #230,
Go #260, C #261, Java #262 and .NET #263. Those tickets implement transports;
#227 supplies the complete transport-neutral facade, reproducible models and
fast semantic fixtures. A compiling facade or fixture double is **not** evidence
of a working network client. No transport can claim this profile by implementing
only its preferred management subset.

## Authority and generation

[`client-profile.json`](client-profile.json) selects definitions and RPCs from
the checked-in [protobuf API](../../api/proto). `generate.py` reads those source
definitions, including field numbers, message presence and oneof membership;
[`contract.json`](contract.json) records the result. Generated files are not a
second wire schema. The only non-wire records are local call/error metadata and
the existing publication selector/identity convenience shapes.

Run from the repository root:

```text
python sdk/profile/generate.py --check
python sdk/profile/generate.py --write
```

`--write` is the reproducible regeneration command. `--patch` emits an
`apply_patch` patch instead. There are no generator dependencies outside the
Python standard library; formatting uses the repository's pinned `rustfmt` and
`gofmt` executables on `PATH`. Handwritten semantic tests are not overwritten.

| Language | Complete facade | Lifetime/cancellation |
| --- | --- | --- |
| Rust | `management::ClientProfile`, `management::{Request,Response}` named exactly as protobuf | Owned DTOs; dropping `ClientFuture` cancels the local wait, not an activation or mutation. |
| Go | `sdk/go/profile`, `profile.ClientProfile` | Every method takes `context.Context`; cancellation is local. Returned maps/slices belong to that response and must not alias a recycled transport buffer. |
| TypeScript | `profile` namespace from the SDK entry point, `profile.ClientProfile` | Every method accepts `CallOptions` with optional `AbortSignal`; `Uint8Array` results remain owned after promise settlement. |
| Java | `Management.ClientProfile` and nested `Management` records | Returns a cancellable `CompletableFuture`; cancelling it stops the local wait, not remote work. Returned buffers/collections must not alias recycled transport storage. |
| .NET | `Latent.Sdk.Profile.IClientProfile` | Each method takes `CancellationToken`; `ValueTask` results own their memory after completion. |
| C | `<latent/profile.h>`, `latent_profile_client_vtable` | Explicit local call handles, exactly-once callbacks and borrowed response data; detailed contract below. |

The legacy invocation interfaces remain source-compatible convenience surfaces;
their older error/enum models cannot represent every v1 fact. The new facade
therefore has its own namespace, including protobuf-shaped `InvokeRequest`,
`InvokeResponse`, `CancelResponse` and `ActivationStatus`. In particular, it
does not silently map an unknown cancellation enum to an old success variant.
Network clients may expose generated protobuf objects and lossless conversions
instead of duplicating storage. The conversion must retain every profile field.

Rust exports `pub mod management;` from `sdk/rust/src/lib.rs`; ordinary crate
tests use that public API, not a hidden path include. The transport owner alone
changes `Cargo.toml`, `network*` and the network export. No wildcard root reexport
is needed: it would collide with the legacy convenience types.

## The eight required operations

Every operation is unary, cancellable locally, single-attempt and bounded.
Each takes its protobuf-named request and local `CallOptions`; it returns
`ClientResponse<Response>` with `value` and `ResponseMetadata`. RPC paths and
request/response names are machine-readable in `client-profile.json`.

| Operation | Request and response | Required behavior |
| --- | --- | --- |
| Invoke | `InvokeRequest` / `InvokeResponse` | Keep caller activation/lineage IDs, budget, absolute invocation deadline, priority, media type and opaque payload. Preserve exactly one success/declared-error/platform-failure result and the common receipt even for failure. |
| Cancel | `CancelRequest` / `CancelResponse` | Uses the known activation ID. Accepted is advisory, already-terminal retains its state, and not-found is not proof of nonexecution. RPC errors are never dispositions. |
| GetActivation | `GetActivationRequest` / `ActivationStatus` | Recover by the original activation ID; retain terminal outcome, time and final consumption independently. Bounded status retention makes missing status inconclusive. |
| GetPolicy | `GetPolicyRequest` / `GetPolicyResponse` | Both `POLICY` and `PROVIDER_BINDING` record kinds; absence is retained, not an invented zero-generation record. |
| ListPolicies | `ListPoliciesRequest` / `ListPoliciesResponse` | Both record kinds; explicit positive page size, exact opaque cursor, catalog generation and next-token presence. Never auto-drain pages. |
| ListCapabilities | `ListCapabilitiesRequest` / `ListCapabilitiesResponse` | Explicit selected deployment, optional filters and bounded page; redacted binding/provider identity, revisions, configuration epoch, sampled state and unavailable resource owners. |
| ApplyPolicy | `ApplyPolicyRequest` / `ApplyPolicyResponse` | Both record kinds; explicit `expected_generation` and caller-known nonempty `operation_id` before dispatch. Zero is create-only, not absence. Preserve the exact record and operation receipt. |
| GetPolicyOperation | `GetPolicyOperationRequest` / `GetPolicyOperationResponse` | Recover by the original operation ID before deciding whether to replay. Missing receipt is unknown/not retained, never proof that the mutation did not run. |

`ApplyPolicy.policy` follows the server's closed document profile. Input
generation is zero, digest is empty, revoked is false, metadata name matches ID,
and the explicit metadata tenant must match authenticated scope. Namespace,
labels and annotations are not accepted in this closed mutation. The language
and document select the authoritative policy/provider-binding schema. These
constraints do not authorize the request: the server authenticates the tenant
administrator and validates the document, generation and operation identity.
The client never supplies actor/principal claims or provider credentials.

Matching retained operation ID, request content and precondition permit the
server's existing replay recovery; changing the content under that ID conflicts.
No facade generates IDs, guesses a generation, automatically retries a mutation,
or treats an idempotency key as an exactly-once guarantee.

### Provider identity and limits

`CapabilityDescriptor.inspection` carries the definition digest, provider binding
ID/revision/digest, policy ID/revision/digests, provider profile, configuration
digest/epoch and sampled state. `revision` preserves deployment, revision,
component, optional publication, route generation and catalog transaction.
Counters and `unavailable` remain separate; an absent owner is not zero usage.
`include_node_usage` requests an additional server-authorized view; it is not a
node-operator claim.

The authoritative `ListCapabilitiesResponse` has **no effective grant-ceiling
field**. Do not invent one or populate it with zeros. Inspect referenced records
with `GetPolicy` to retain their closed JSON limit documents (including absent
versus present-zero narrowing). `CapabilityInspectionCeiling` also preserves the
typed public ceiling shape, but an evaluated ceiling belongs to the separate
`ExplainCapabilityGrant` RPC, which is not one of the eight mandatory calls.
Neither a stored limit, descriptive Allow, capability handle, validation report
nor publication identity grants execution authority. Live admission remains
server-owned. There is no client-side policy evaluation in this profile.

Current server bounds, subject to lower configured limits:

| Surface | Bound/presence rule |
| --- | --- |
| Policy requests/responses | 128 KiB / 1 MiB encoded protobuf; one policy read owner through response consumption. |
| Policy pages | Page message required; page size 1 through the configured maximum (default 16, hard store ceiling 32); cursor at most 117 bytes. |
| Capability requests/responses | 8 KiB / 128 KiB; at most 128 bindings, cursor at most 160 bytes. |
| Capability pages | Absent page or scalar zero uses the server's 128-record default; scalar zero has no protobuf presence bit. |
| Policy operation IDs | At most 256 bytes; explicit nonempty IDs, never generated by the SDK. |
| Policy/inspection deadline | The server caps the original request deadline at 30 seconds; client connection and RPC work share one local absolute deadline. |

Cursors are opaque and scoped to authenticated identity and filters. Do not
normalize empty to absent, decode/rebuild tokens, splice generations together or
silently restart an expired listing. Policy and capability pagination have
different server defaults; a generic helper must not erase that distinction.

## Presence, integers and compatibility

Every protobuf message field retains presence, including non-`optional` message
fields. Optional scalars use `Option`, pointers, optional properties, `Optional`,
nullable values, or a C `has_*` flag. Empty strings, zero and malformed selectors
stay representable for rejection; they never trigger fallback or defaulting.
Nonoptional proto3 scalar absence is its documented default, not invented
presence. DTOs also preserve contradictory oneof members for boundary rejection;
an adapter must reject contradictions rather than silently choose a result.

Unsigned values cover zero through `18446744073709551615`. TypeScript uses
`bigint`, never `number`, for every `uint64`. Java uses all 64 bits of `long` and
`Long.parseUnsignedLong`/`Long.toUnsignedString`, not signed range checks; u32
similarly retains all bits of `int`. Other facades use native unsigned integers.
Canonical fixture JSON uses decimal strings for u64 and base64 for bytes. The
`parseU64Decimal` family rejects signs, fractions, whitespace, leading zeroes and
overflow. This fixture convention does not replace the protobuf transport or
authorize unbounded generic JSON decoding.

Enums are open signed i32 values: Rust numeric newtypes with `.0`, Go int32-based
types, TypeScript numbers, Java/.NET numeric records and C `int32_t`. Known
constants match protobuf values; unknown zero/positive/negative values survive
without turning into a known success. Unknown response enum values remain
inspectable; adapters may reject unsupported behavior but retain its raw value
in failure evidence. Unknown field numbers are a wire-layer concern, not DTO
members. String states, error codes and detail kinds remain open strings.

`PublicationRef` carries the exact publication ID and authenticated tenant.
The obsolete component-or-publication selector model has been removed. Tenant
is independent of package/component identity: a corrected package can preserve
component bytes, and identical packages in different tenants have distinct
publications. `release_digest` means executable bytes, never a fallback selector.
Captured `publication_id` in an invocation response is not an Invoke selector.


## Error and uncertainty profile

`ClientFailure` retains `category`, redacted `message`, optional raw `grpc_status`,
optional typed `platform_error`, `dispatched`, `outcome`, `identity`, optional
`audit_ack`, optional raw `audit_status`, optional independent u64
`audit_attempt_sequence`, and optional `unsupported_wire_value`.
`UnsupportedWireValue` holds a controlled field label and at most 256 bytes of
untrusted future wire text. It is diagnostic data, never routing, principal or
execution authority. Unsupported invocation phase/terminal/error codes may fail
explicitly as Decode/InvalidResponse while retaining this bounded raw evidence;
they must not become a known success. `RequestIdentity` contains only
optional activation/operation IDs. Every invocation outcome retains its receipt;
structured platform detail items are not flattened into a message or mistaken
for declared guest errors. WIT provider errors stay in the declared typed
payload unless the authoritative host mapping returns a platform failure.

| Category | Meaning |
| --- | --- |
| LocalCancelled | A future/context/signal/token/local C call was cancelled. |
| Deadline | Local timeout or remote deadline exhaustion, distinguished by raw RPC status. |
| Transport | Connection/framing failure; dispatch is conservative, never guessed false after a send. |
| Rpc | A non-OK RPC status; retain its exact code, bounded redacted details and recovery identity. |
| Decode | Malformed/contradictory response; never manufacture success or nonexecution. |
| Limit | A finite client admission/body/queue limit was exhausted. |
| InvalidRequest | A request cannot be represented or fails the profile boundary. |

RPC status integers retain `InvalidArgument` (3), `DeadlineExceeded` (4),
`NotFound` (5), `PermissionDenied` (7), `ResourceExhausted` (8),
`FailedPrecondition` (9), `Unimplemented` (12), `Internal` (13),
`Unavailable` (14), `Unauthenticated` (16), and unknown values without collapsing
them to a boolean retry hint. `Cancelled` (1) remains distinct from Cancel RPC
acceptance. No status alone authorizes retry or proves rollback.

`OutcomeKnowledge` is `NotDispatched`, `Unknown` or `Observed` (with open numeric
compatibility). A local failure before any send may be NotDispatched. Losing a
response after dispatch stays Unknown. Observed means the specific returned
outcome is known, not that an effect is transactional or safe to replay. A
GetPolicyOperation response without a receipt leaves the mutation Unknown.

`ResponseMetadata` carries identity/outcome plus independent audit acknowledgement,
raw `audit_status`, and optional u64 `audit_attempt_sequence`. `ClientFailure`
exposes the same independent sequence. `AuditAck` preserves open numeric status and optional u64
attempt sequence. Current policy calls do **not** emit an audit acknowledgement;
absence must stay absent, not fabricated Durable or Disabled. Where present,
bounded `latent-audit-status` / `latent-audit-attempt` response metadata map to
these fields. Retain a valid attempt sequence independently even when header
status text is unknown: `future-state` with `18446744073709551615` retains both
raw fields and leaves `audit_ack` absent. Do not fabricate an `UNSPECIFIED` or
other numeric acknowledgement from unknown header text. Known status mappings
retain `AuditAck` as well as both independent raw fields. An explicitly received
protobuf `AuditAck` with an unknown numeric status remains representable, which
is different from inventing one for a textual header. An unknown audit outcome
cannot overwrite an observed mutation receipt, and a durable attempt alone is
not proof of commit. Errors and partial decoding must retain already-known IDs.

`CallOptions.timeout_millis` is relative local RPC time, not the absolute
`InvokeRequest.deadline_unix_millis` or relative activation
`ResourceBudget.wall_time_limit_millis`. Missing local timeout uses a finite
transport default; zero expires immediately. Full-width values remain in the
model; a transport must reject values outside its bounded clock representation
without wraparound. Every transport retains a single absolute deadline through
connect, send, wait, decode and local completion.

Errors remain discoverable through each language's native cancellation surface:
Go's `ClientFailure` supports `errors.As` and unwraps local cancellation/deadline
categories for `errors.Is`; TypeScript's `ClientError` retains `failure`; Java's
`ClientException` and `ClientCancellationException` retain the same record.
`Management.clientFailure(Throwable)` follows a bounded cause chain, including
JDKs that wrap a future's cancellation exception. .NET's
`ClientCancellationException` retains the record and `CancellationToken` while
remaining an `OperationCanceledException`. These local error categories do not
convert a Cancel RPC response into a cancellation exception.

## C callback and response lifetime

All eight vtable methods return a local `latent_profile_call*`, not an activation
or operation ID. Requests/options and nested pointers are borrowed only until
the initiating function returns; asynchronous implementations copy retained
inputs. Exactly one completion callback runs, with exactly one of result/failure
non-null, including local cancellation and admission failure. Callbacks may run
inline. Returned result/failure pointers and all nested bytes are borrowed until
that callback returns. Callers copy what they retain. Strings are length-delimited
and need not be NUL-terminated; presence never depends on pointer or length.

A successfully returned handle remains caller-owned until `release_call` after
its callback has returned, even if completion was inline. `cancel_local` only
cancels the local wait and still owes the completion callback. Admission failure
may return NULL only after its failure callback; no release is needed for NULL.
Clients/user data outlive callbacks. `destroy` requires all callbacks completed
and all non-null handles released. No returned pointer authorizes remote Cancel,
operation replay or capability dispatch. C ABI is pre-stabilization: rebuild
all consumers/producers together.

This profile returns fully materialized bounded unary values, not public response
streams. Transports own sockets, decoders and frames through consumption or drop;
they cannot refund still-retained resources merely because a waiter disappeared.
Future streaming APIs need their own explicit body lifetime contract. No dormant
application acquires a dedicated connection, listener, worker or provider pool.

## Executable semantic fixtures

[`fixtures.json`](fixtures.json) is the common canonical input, not a network
JSON encoding. `generate_fixtures.py` materializes every case into each language's
public DTOs and generates field-by-field native assertions. `generate.py --check`
checks both model and vector reproducibility against protobuf and this input.
The 68 shared cases cover nested typed failures, every operation's DTOs, retained
publication/operation identity, absent/present-empty/present-zero values, u64
maximum, unknown signed enum values, policy/provider pagination, audit absence
and uncertainty, and contradictory oneofs. Sixteen decimal parser inputs cover
exact boundaries, overflow, signs, leading zeroes, NUL and trailing whitespace.

Each language also runs a handwritten all-eight-operation fixture client. Those
tests exercise local cancellation or dropped waits after a retained mutation,
receipt recovery without automatic replay, single-page behavior, zero timeout,
and response ownership. The C fixture poisons caller inputs and callback buffers
after their documented lifetime, copies retained results, tests inline callbacks,
and releases handles only after callbacks return. Waits are bounded; these are
not network servers, production policy stores or wire-decoder conformance tests.

```text
python sdk/profile/validate.py
python -m unittest discover -s sdk/profile -p "test_*.py"
cargo test -p latent-sdk --locked
tools/validate_sdks.sh
```

The Python validator checks source selection, finite fixture sizes, unsigned and
enum ranges, publication/presence cases and selected invalid-request markers.
It does not duplicate the complete server authorization or closed-document
validator. Native tests consume generated constructors, not a permissive JSON
bridge; transport tickets must additionally prove lossless protobuf conversion
and behavior against bounded peers and real nodes.

The Go package tests and existing TypeScript, Java, .NET and C semantic entry
points include the new suites; Rust integration tests import the public
`latent_sdk::management` module. The shell runner uses its existing pinned Linux
toolchain. The dedicated Python regeneration/validator command is separate from
that runner; a CI owner can invoke it where pinned `rustfmt` and `gofmt` are
available. No workflow or shared shell-runner changes are part of this ticket.
See [local evidence and remaining integration boundaries](EVIDENCE.md).
