# Transaction, query and durable effect contracts

The Phase 4 definition profile is `lsf-transaction-v1`, with host ABI
`lsf-host-abi-phase4-v1` and WIT world `latent:platform/capsule@0.5.0`.
[The ABI matrix](../../wit/host-abi-phase4-v1.json) identifies exact sources.
This is a contract definition. It installs no engine, transport integration or
authority. Unsupported profiles fail before execution. The supported stateless
V4 profile and existing invocation field numbers retain their meanings.
The unsupported state 0.1 declaration with guest `begin`/`commit` is retired;
historical release and evidence bytes remain unchanged.

## Guest access and host commitment

[State WIT](../../wit/platform/state/package.wit) imports owned `transaction`,
`query-view` and `page` resources. Only `acquire-command` or `acquire-query`
returns the activation's admitted access. There is no constructor, namespace
selector or guest commit. Every borrowed access checks the store's activation,
generation, access mode and live resource owner. Drop releases only access
ownership; abandoned staging remains charged until host cleanup and never
commits. Reacquiring a dropped owner cannot obtain a new snapshot or authority.
Only one access owner may be acquired for the selected activation mode.

`get` and `get-query` return `option<versioned-value>`: absence differs from an
empty value. `put`/`delete` and [intent staging](../../wit/platform/intents/package.wit)
require the command resource. Queries cannot stage mutations, intents or child
effects. The host validates successful output, settles all accepted logical
work, seals staging and exclusively attempts the atomic state/outbox/command
result/inbox boundary. No guest callback can commit early. See the
[transaction decision in ADR-0062](https://github.com/KirilsTurkins/latent-service-fabric/pull/765)
for isolation and settlement ownership.

The namespace OCC generation covers the read snapshot including missing reads
and prefix predicates. A changed snapshot at commit is `conflict`; a failed
application-selected expected-version precondition at admission is `stale-input`.
Opaque versions include namespace incarnation and must not be parsed, narrowed,
incremented or compared lexically by clients. Restoring older history changes
incarnation; the old version is rejected explicitly.

## Bounds, presence and encoding

| Value | Maximum |
| --- | --- |
| Nonempty key; prefix may be empty | 1,024 bytes |
| State value, command result or intent payload | 1 MiB each |
| Identity, entity, operation, scope, schema/format name | 256 UTF-8 bytes |
| Opaque version or page cursor | 256 bytes, nonempty when present |
| Media type | 128 ASCII bytes, nonempty |
| Metadata | 32 unique pairs; 8 KiB UTF-8 total; value 1,024 bytes |
| Expected-version preconditions | 128 unique keys |
| Page | 128 entries and 1 MiB encoded bytes |
| Staged intents | Default 32, explicit policy ceiling at most 128 |
| Shared staging ledger | 8 MiB encoded mutations, intents, result and inbox |

Admission/policy may reduce these limits. Each operation and accumulated work
also consumes its host budget before allocation. Page `limit` is 1–128; zero is
invalid. Pages own their bounded selected data and charge the original view.
`page-next` pulls one entry, and exhaustion returns absence. Its returned cursor
is bound to activation/view, prefix, access mode and incarnation. Historical or
cross-request query cursors explicitly fail. Management history cursors instead
bind the authenticated tenant, filter, revision and finite expiry.

WIT bytes are `list<u8>`; strings are strict UTF-8. Protobuf bytes remain bytes,
and `uint64` retains the entire unsigned range. HTTP uses canonical padded
base64 and decimal strings for u64. Invalid present values, nulls, empty
identities, unknown enums/versions and overflowing integers fail validation;
none becomes absence, zero, success or a stateless fallback. Structural schemas
also require byte-aware decoding in [the shared decoder](../../tools/transaction_contracts.py).
Errors have a finite enum, at most 32 detail pairs, a 256-byte code and 1,024-byte
message with an 8 KiB aggregate detail ceiling.

## Command identity, rejection and explicit attempts

The durable key is the length-framed tuple tenant, namespace, incarnation,
host-derived recovery scope, operation, optional entity and client key. Default
scope is stable authenticated caller identity. Shared or delegated scopes require
current host approval; knowing a string or being in the same tenant is insufficient.
Routes, source revisions, activation correlation IDs, session cookies, bearer
tokens, CSRF values and credential rotation never change business identity.

The SHA-256 fingerprint covers the admitted canonical input format, media type,
canonical input bytes, explicitly declared business metadata, and sorted
incarnation-aware expected versions. The application defines canonicalization
before framing; arbitrary JSON reserialization is not canonicalization.
Duplicate metadata/precondition keys reject. Framing, optional discriminants and
domain separators are executable in [Rust](../../crates/latent-core/src/transaction_contract.rs)
and the shared decoder. A mismatching fingerprint is a terminal request error
without executing the guest. Budget/deadline and transport security data are not
business input unless an explicit application contract selects their semantic value.

An admitted terminal business rejection persists its original application result
and inbox outcome while discarding staged state/effects. `metadata-durable=true`
and `application-state-committed=false` distinguish that outcome from a commit.
It is replayed even if later business state would now accept the command.
Current execute/result-read and result-policy authorization is checked before
initial invocation and every replay/lookup; retained decoding grants no permission.

A technical abort permits a new explicit attempt only with the server's durable
`AbortFence` identifying command, old attempt, transaction and retired physical
owner fence. The retry request has its own attributable `request-id`; atomic
compare-and-advance admits one competing attempt and retains the original receipt.
Unknown, expired, transport timeout or empty lookup never proves abort. SDKs
perform no implicit reexecution, even when clocks or entropy were observed.

## RPC and HTTP application boundaries

[TransactionService](../../api/proto/latent/transaction/v1/transaction.proto)
defines transactional invoke, fresh query, command/commit lookup, effect status
and history, and command cancellation. Its wrapper requests negotiate the whole
profile and retain the existing generic invocation fields. The stateless Invoke
API gains no durable authority from `idempotency-key`. Captured source identity
contains exact publication, revision, separate component and release digests, route generation,
contract digest, state schema and input/result format. Replays retain that
source identity despite subsequent route changes.

[StateService](../../api/proto/latent/control/v1/state.proto) defines namespace
inspection, entity selection and guarded approved mutations with immutable
operation receipts. Writes require current management credentials, expected
version and policy digest. Guests and browser routes never acquire this authority.
Retry of uncertain dispatched effects is not a generic approved write.

[HTTP envelopes](../../schemas/transaction-api.schema.json) distinguish
`command`, `query`, `recovery` and `response`. Route bindings select the declared
operation/mode, namespace and admitted exact source; requests cannot override
them. The host derives tenant and stable caller scope from current authentication.
Command/recovery routes require the client key; queries require none and write
no durable command row. Fresh views are selected at admission and observe at
least the acknowledged version through `minimum-view-version`; incarnation
mismatch fails. Queries are fresh again on each new request, not cached command
replays. All envelope and application result bytes are bounded before lifting.

The shared `decode_envelope` validates byte/depth/node limits before JSON
allocation, rejects duplicate fields, then checks structural and decoded bounds.
Receipt IDs, source formats, opaque versions and effect attempts must agree.
An opaque abort fence passing shape validation grants no retry authority; the
host must prove durable technical abort and physical-owner retirement.

Only explicit application data, permitted media type and application response
metadata are retained. Set-Cookie, Authorization, CSRF tokens, CORS/CSP/security
headers and credentials are not replayable historical data by default. Current
transport headers are reconstructed under current route/security policy. A
committed application result with cleanup, cancellation or transport failure
stays committed; `already-committed` cancellation returns its receipt. Lost commit
acknowledgement yields lookup/recovery, never an invented abort.
`application-state-committed=false` on an unknown outcome is not proof of abort.
A known commit remains `committed` after payload expiry, with its receipt and
`payload-available=false`; expiry cannot fabricate a safe retry.

## Durable effects and formats

Staging accepts a logical binding, approved operation, payload and requested
expiry. The host chooses admitted provider profile, deterministic command-attempt
sequence identity, finite retry policy, independent dispatch/payload lifetime and
current authority. The sequence allocates IDs, with no completion ordering promise.
Receipts distinguish pending/dispatching, provider acknowledgement, known failure,
uncertainty after dispatch, expiry, policy block and terminal administrative
disposition. Provider acknowledgement does not establish universal exactly-once
effects. Known failure is distinct from uncertain dispatch; neither silently
becomes success or safe automatic retry.

[Durable records](../../schemas/transaction-durable-record.schema.json) independently
version command results, intents, inbox, ordering and checkpoints. Record
format/version, application payload format and active ABI are separate identities.
Decoders for retained supported old formats remain bounded while linked retention
still requires them. Unknown formats reject without deleting bytes. Result-read
permission is checked currently after format recognition. Linked retention exposes
payload/identity expiry and remaining recovery; purge cannot remove a dependency
still needed by a result, deduplication tombstone, intent or checkpoint.
Independent record formats do not add a workflow, timer or continuation engine.

[TransactionBinding](../../schemas/transaction-binding.schema.json) is a bounded
companion declaration linking exact existing capsule/deployment/binding IDs,
namespace, schema digest, operation modes and profile identity. It does not widen
their current stateless admission or bypass missing runtime support. Workflow,
cluster, cross-namespace and historical-snapshot modes remain rejected.

## Six language profiles and preparation evidence

Both required profiles cover Rust, C, TypeScript, Go, Java and C#/.NET: guest
state/query/intent operations for #389/#718, and all external transactional RPCs
plus authenticated management inspection/writes for #401. Client generation
cannot qualify guest lowering; guest compilation cannot qualify a client transport.
[The generated requirements](../../sdk/profile/transaction-requirements-v1.json)
enumerate all 13 guest operations and 11 external/management RPCs. Guest profile
`latent.guest.transaction.v1` and client profile `latent.client.transaction.v1`
both consume the single `lsf-transaction-v1` wire contract and retain independent
execution evidence; neither becomes qualified by generating the other.

Required compiler probes cover reuse of imported types, result/option/record/list
lifting, imported own/borrow resource ownership and host suspension. Freestanding
resource operations accommodate the maintained Java generator's prohibition on
resource methods. Stackful lowering retains authoritative async WIT metadata;
it introduces no hidden guest event loop. The maintained Go/Java/.NET clocks,
entropy, GC and bounded log imports remain narrowly authorized runtime support,
separate from denied immediate application effects. Initialization does not grant
arbitrary I/O. Runtime observations never make automatic replay safe.

Preparation identity includes exact engine/version, host ABI digest, codec profile,
type-node/depth/name/collection bounds, lifting bytes and hostcall allowance, plus
each signature's checked allocation plan. The HTTP-enabled profile uses the
existing 2 MiB hostcall allowance and 64 MiB lifted-byte ceiling; these are not
globally increased. Pages pull one nested entry per call to avoid list-element
amplification from #708. Successful generation/compilation alone is not successful
preparation or real state-engine execution. #708 retains its separate composed
Java regression; the definition probes consume the same preparation limits.

[The generated preparation profile](../../sdk/profile/transaction-preparation-v1.json)
binds these dimensions with its own digest. Engine reflection checks all 13
operations, including eight async imports, and writes per-signature allocation
plans when `LSF_TRANSACTION_PREPARATION_REPORT` names a new output file. A
negative nested-page signature consumes the #708 allocation regression, and
unrecognized resource owners reject before lifting.

[The shared compiler inputs](../../sdk/transaction-contract) use each maintained
language owner through `tools/qualify_transaction_contracts.py --language LANGUAGE
--output NEW_DIRECTORY`. Java also needs `--wasi-sdk`; TypeScript and .NET need
their existing pinned `--tools` directory. The six existing language CI lanes
retain actual components, exact generated bindings, source identity and compiler
definition receipts. They preserve the later executable SDK gates. The required
Jco `delete` declaration and Java shared-owner alias corrections are exact
compiler projections; neither changes WIT authority or lowers typecheck strictness.

[Shared vectors](../../sdk/profile/transaction-vectors.json) retain one scenario
vocabulary across guest models, external client models, HTTP and actual execution.
Every result must name its actual boundary and source/compiler/engine/profile
identity. The vocabulary and digest vectors claim no execution qualification.
Reproduce definitions with `python tools/generate_transaction_contracts.py --check`.
The [observed six-language compiler and HTTP preparation receipts](../evidence/phase4-contract-definitions-2026-10-01/README.md)
qualify the definition at the exact recorded source and profile. The later real
guest, external-client, runtime and HTTP integration gates retain independent
execution evidence; generated stubs do not complete them.
