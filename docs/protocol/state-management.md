# Authenticated transaction management

The native `StateService` and `TransactionService` boundaries use the exact
[`lsf-transaction-v1` profile](transactions.md). The generated negotiation
constants come from the complete WIT and preparation declarations. An unknown
profile fails before domain admission. These adapters require the node's actual
`Phase4Runtime`; defining the protocol and supplying a test runtime does not
install transactional execution on a standalone node.

## Current access and historical identity

Every namespace inspection or recovery request supplies its current
`authorization_publication`. This is a requested installed target within the
authenticated tenant. The same publication/binding resolver used by invocation
must seal current namespace and result-read permissions before lookup and
again before delivery. A publication ID, command ID, cursor, tenant membership
or execution permission alone grants no result access.

This current target is separate from the result's immutable `SourceIdentity`.
A compatible current publication may authorize an older result without changing
its original publication, component, release, input format or result format.
It cannot refresh the original executor's revoked authority. The current target
does not participate in the command key, fingerprint or abort fence.

`StateService` uses the existing administrator and tenant boundary.
Application `TransactionService` calls preserve the authenticated stable caller
scope; they do not require administrator elevation. A supplied shared recovery
scope still needs current host approval. The domain owner enforces namespace,
publication, provider, delegation and result policy after transport preflight.

## Explicit namespace operations and recovery

The CLI exposes `state inspect`, `create`, `quiesce`, `retire`, `destroy`,
`recreate`, `operation` and `entities`. Every command requires `--namespace`,
canonical positive `--incarnation`, and `--authorization-publication`.
Mutations additionally require the original `--operation-id` and
`--expected-generation`. Create supplies generation zero and incarnation one;
other transitions require a positive generation. Create/recreate take a finite
closed `--configuration` file:

```json
{
  "stateSchema": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "quota": {
    "stateKeys": "4096",
    "stateBytes": "8388608",
    "resultRows": "4096",
    "resultBytes": "8388608",
    "effectRows": "4096",
    "effectBytes": "8388608",
    "payloadBytes": "8388608",
    "recoveryBytes": "1048576"
  }
}
```

The host checks the exact generation, lifecycle transition, durable pins and
current policy in the engine's existing writer. The response reports its
disposition and audit acknowledgement independently. A lost response is
recovered with `state operation --operation-id ORIGINAL` and the original
namespace selector. The CLI does not generate a replacement operation ID,
refresh a generation, repeat a mutation or poll silently.

## Command, commit and effect inspection

`transaction lookup` selects namespace, incarnation, operation, client key,
optional entity/shared scope and optional original attempt. `transaction commit`
also supplies the exact receipt ID. `transaction effect` and `effect-history`
select the exact effect; `transaction cancel` retains the selected original
attempt. Each performs one request through the existing authenticated session.

Business rejection is a durable terminal application outcome with
`metadataDurable=true` and `applicationStateCommitted=false`. It remains distinct
from a successful commit and a technical abort. `unknown`, `recovery-required`,
`expired` and `in-progress` never imply nonexecution or permit a retry.
Only an explicit server-issued fence proving retirement and no commit permits
an explicit attempt. Cancellation requested is distinct from physical retirement
and cannot overwrite a committed outcome or its independent cleanup failure.

History/entity pages carry explicit opaque continuations. A short or filtered
empty page can still have `nextCursor`; exhaustion is only its absence. The CLI
accepts canonical padded base64, performs no follow-up fetch, and preserves
all unsigned 64-bit generations, timestamps, quotas and retention counters as
decimal strings in human and JSON output. Original component and signed release
digests remain separate fields.

## Bounded ownership and diagnostics

Native preflight charges retained allocation capacities before encoded length:
requests/responses are at most 2 MiB, pages at most 128 rows and 1 MiB, and
identities/cursors are bounded. A runtime may impose smaller configured limits.
It reserves actual work and response capacity synchronously before returning
the execution future; recovery uses the actual reserved recovery lane.

`OwnedPhase4Response` carries that real reservation through deferred protobuf
encoding, body Drop and retained transport byte frames. Response publication
uses a short current-policy fence after encoding. Disconnect or a returned
response does not refund a still-live physical owner. An absent or insufficient
reservation fails explicitly; the adapter creates no fallback pool or worker.

Retained technical failures and cleanup diagnostics use the existing closed
public error producer/redactor. Private engine paths and arbitrary provider text
are removed while original application success/rejection payloads remain intact.
Failure stage, cleanup status, audit status and durable disposition are separate
facts; missing diagnostics do not prove an abort.

## Remaining full-workflow qualification

The concrete `latent_wire::phase4::StateManagementBackend` now composes namespace
inspection, lifecycle mutations and actor-scoped operation recovery from the
installed `ArtifactRepository`, original authenticated context, `PolicyStore`,
metadata-only `NamespaceCatalog`, and the same `ProtectedStoreOwner` used for
commands. Its finite trusted bindings name the exact installed publication,
tenant-qualified service, component, namespace, incarnation, schema and policy
constraints. Requests cannot install these bindings or derive authority from
their IDs. The constructor also requires the node's actual retained admission
port; it supplies no default capacity pool.

Before native lookup, the backend checks the actual selected artifact and seals
current namespace permissions through the existing policy owner. It retains
those original decisions through the fixed worker and response frame. Native
mutation preparation does not hold a policy lock over I/O. Its actual writer
fence checks the original policy and namespace lifecycle in that order, then
accepts the affine transition before physical commit. A dropped RPC waiter leaves
the accepted worker and its reservation owned until actual completion. Replays
preserve the original actor, operation, request and generations; a separate
authorized read recovers a durable receipt after response revocation.

Inspection reads namespace metadata, native usage, command/effect counts and
caller-visible retention from one coherent engine snapshot. Native inventory
work has finite row, byte and deadline limits. At most 128 caller retention
descriptors are returned; exceeding that unpaged response bound fails explicitly.
`payloadAvailable` describes verified retained result bytes. It grants no replay
permission and does not prove unexpired retention. The engine profile digest
describes the actual configured owner and selected format; it is not a
qualification receipt.

If auditing is configured, the backend reserves and durably begins a typed
namespace audit attempt before mutation preparation. The exact original
operation ID and generation remain in the audit. Publication/component,
namespace/incarnation and schema are descriptive audit identities; business
keys and payloads are omitted. Audit enqueue and acknowledgement happen outside
the policy/lifecycle locks. Mutation disposition and audit acknowledgement remain
independent, including uncertain audit completion after a known native commit.

The native Linux tests use real catalog, policy, protected engine and audit
owners. They cover concurrent generation CAS, lifecycle/tombstone access,
detached waiter retention and clean reopen, exact selected service rejection,
stable actor recovery, namespace accounting, original revocation and actual
response memory charges. Their admission fixture uses the production activation
memory owner; it does not qualify the node's reserved recovery lane or saturated
store progress. Entity pages, maintenance jobs and command/effect operations
must be supplied by the corresponding owning runtime ports.

The boundary tests establish preflight, authenticated association, original
receipt identity, lossless projection and transport owner retention. They are
not storage, saturation or real CLI/node workflow evidence. Full issue #400
closure additionally requires actual node composition, command invocation,
dispatcher pause/resume and authorized reconciliation, migration/backup/restore
jobs, typed audit/metrics, and the prescribed real CLI/node recovery and reserved
lane tests against those owning domain implementations.
