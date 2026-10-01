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

`StateManagementRecoveryAdmission` wraps the installed node's existing
`NativeCapacityOwner`. It reserves the separate recovery partition before
returning the operation future, charging the original decoded request, an
8 MiB native work allowance, the exact bounded response allowance and the
owner's fixed metadata. It preserves the original monotonic deadline and close
fence. Namespace inspection and receipt recovery use `RecoveryRead`; namespace
mutation and dispatcher controls use `RecoveryWrite` on the same engine and
its reserved fixed worker. These classes cannot borrow ordinary admission.
The real single writer still serializes all writes; a stalled device can cause
an explicit bounded failure rather than successful recovery.

Before native lookup, the backend checks the actual selected artifact and seals
current namespace permissions through the existing policy owner. It retains
those original decisions through the fixed worker and response frame. Native
mutation preparation does not hold a policy lock over I/O. Its actual writer
fence checks the original policy and namespace lifecycle in that order, then
accepts the affine transition before physical commit. A dropped RPC waiter leaves
the accepted worker and its reservation owned until actual completion. Unclaimed
native completions retain that same global reservation until their output values
drop. Published response bodies and byte frames retain it through their actual
destruction. Replays
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
response memory charges. Additional tests install the actual shared native
capacity owner and reserve the actual protected recovery worker. Authenticated
RPC inspection and encoded response frames progress with the ordinary global
slot full, all three ordinary storage workers occupied, and ordinary queue,
accepted-job or retained-byte capacity full. Dropping the body preserves the
charge held by its byte frame. Detached queued writes retain their global
capacity until native retirement; an expired original request creates no receipt,
and an accepted lost response is recovered after a clean engine reopen.
These tests qualify finite admission and worker progress, not recovery from an
unreadable device or a complete standalone CLI workflow. Entity pages,
maintenance jobs and command/effect operations
must be supplied by the corresponding owning runtime ports.

The separate structural boundary tests establish preflight, authenticated
association, original receipt identity and lossless projection. Full issue #400
closure additionally requires actual node composition, command invocation,
dispatcher pause/resume and authorized reconciliation, migration/backup/restore
jobs, typed audit/metrics, and the prescribed real CLI/node recovery and reserved
lane tests against those owning domain implementations.

## Explicit effect-management CLI calls

`latent state plan-effect` requires the original command/effect selectors,
management operation ID, one closed action (`redrive`, `reconcile` or
`terminate`), exact base64 effect record version, namespace policy digest and
bounded review reason. Redrive additionally requires an unsigned delay from
1 through 60000 milliseconds. Reconciliation and termination reject a supplied
retry delay. Planning itself contacts no provider and grants no permission to
execute the action.

The response includes the full human/JSON plan plus `encodedPlan`, a bounded
canonical base64 Protobuf value. `latent state apply-effect --plan ...` preserves
that original action, actor-scoped operation ID, CAS, policy digest and current
publication selector. It makes one explicit RPC. Changed selectors and naked
effect mutations fail preflight; the CLI never refreshes a precondition or
automatically resends a mutation.

`latent state effect-operation --plan ...` recovers the original receipt with
current read authorization. Its explicit current authorization publication may
be newer than the historical plan's selector, while the entire original plan
and its expired deadline remain intact. Provider confirmation, administrator
declaration, durable disposition and the new read's audit acknowledgement are
projected separately. A missing historical receipt remains unknown rather than
an abort or permission to retry.

All 143 CLI library cases passed on the pinned Linux Rust 1.97.1 image,
including full original plan/current-selector association, bounded canonical
plan decoding, malformed CAS/unknown fields and expired historical recovery.
CLI library Clippy completed without CLI warnings; dependencies retain their
existing warnings. This does not qualify an end-to-end standalone manual
provider action before that domain adapter is installed.
