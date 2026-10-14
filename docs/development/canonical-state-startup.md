# Canonical protected state startup

Development connects the checked `state` configuration to the real standalone
startup, installed transaction RPCs, shared HTTP transaction routes and separately
authorized deferred HTTP dispatch. The earlier startup-only milestone's
empty-operation restriction is superseded by
[installed transaction RPCs](installed-transaction-rpc.md) and
[deferred HTTP installation](deferred-http-installation.md). The complete native,
application and packaged acceptance gates remain open.

## Configuration boundary

The [state schema](../../schemas/node-state.schema.json) defines the closed
format-version-2 declaration. Select the store identity, configuration epoch,
absolute `checkpointRoot`, one-to-sixty-second startup timeout and finite store,
native and dispatcher partitions. `createIfMissing` defaults to false; it permits
an engine leaf, not automatic parent creation or replacement of checkpoint data.
Provision both private roots before startup.

The business root is `dataDirectory/state`. Its external checkpoint must remain
outside the actual retained ancestry of that business root. A different path
string, symlink or renamed directory cannot establish separate custody. The
[checkpoint contract](transaction-checkpoint.md) specifies the fixed record,
initialization witness, covered clock, owner epochs and physical file retirement.
A matching store label cannot recreate a lost fresh-initialization witness.

The Phase 4 budget profile and `state` settings must appear together. Enforced
supply-chain admission, durable audit and capability-policy ownership are also
required. Optional Phase 3 ceilings fund separately installed stateless services;
they do not authorize immediate HTTP, blob or child calls inside strict commands.
Configuration cannot grant namespace access, clock continuity or restore approval.

The qualification declaration budgets 128 ordinary native slots, a 256 MiB
ordinary aggregate and a 64 MiB per-reservation ceiling. Recovery has eight
slots, a 96 MiB aggregate and a 32 MiB per-reservation ceiling. Derivation must
also leave room for a complete 32 MiB management request after accounting for
the real engine, initializer, validator, namespace and effect-rule residents.
Larger caches require explicit additional capacity. Installation and readiness
share the original bootstrap deadline; physical retention after expiry cannot
renew admission.

## Installed operations and readiness

Each operation pins its actual admitted publication, deployment/revision,
contract/function, signed transaction companion, namespace incarnation and
current state/result policies. The configured provider binding must identify
the real protected engine profile, configuration and epoch. Static declarations
and matching digest strings remain descriptive until the original owners seal
their actual current authority.

The runtime captures signed source, namespace/lifecycle, policy and original
native reservations before exposing execution. Recovery input, retained metadata
and response capacity come from the configured finite partitions. Insufficient
headroom rejects configuration; an omitted partition cannot fall back to an
unlimited or unrelated owner. See [native admission](native-admission-capacity.md)
and [installed RPCs](installed-transaction-rpc.md) for current limits.

A missing namespace exposes authenticated management for its installed binding.
Create it explicitly, stop cleanly and restart with the same configuration before
executing transactions. A changed installed deployment needs another startup
selection. Neither configuration nor a template creator creates the namespace
or installs replacement execution authority.

Dispatch remains under bootstrap suppression while installed source, namespace,
policy, credential and checkpoint checks complete. Readiness releases only that
bootstrap suppression. An operator's durable pause and older-history restore
review remain independent and cannot be cleared by startup. The
[host runtime](phase4-runtime.md) and [effect management contract](effect-management-plans.md)
retain currentness and physical ownership through final acceptance and delivery.
Empty or non-HTTP startup retains its safety pause unless a current-epoch control
has actually selected otherwise. A restored historical Resume cannot release it.

## Stop, preserve custody and recover

Shutdown and cancellation retain native jobs, accepted provider attempts and
response reservations until physical retirement. A detached waiter, idle view
counter or logical pause cannot prove exclusive store custody. Protected snapshot
work additionally needs quiesced namespaces and the original owners' positive
retirement, as defined by [snapshot custody](protected-snapshots.md).

Preserve the external checkpoint, protected clock floors, authoritative catalog,
store and original command/effect history together under the selected recovery
protocol. The [container backup helper](../operations/local-storage-recovery.md)
only copies its fixed roots; it neither follows an external checkpoint path nor
establishes transactional restore approval. Older-history restore changes
incarnation and remains paused for explicit reconciliation. A code rollback
cannot undo business state or an external action.

Use [transaction recovery](../operations/transaction-recovery.md) for original
command, commit and effect inspection. Those read/control commands do not provide
a general qualified checkpoint/restore CLI.

Native `inspect-restore` and `restore` action data accept
`request.destinationStoreIdentity`: one through 128 ASCII letters, digits,
dots, underscores or hyphens. Use the same explicit identity for inspection and
restore. Source validation retains the original source identity; target
validation uses the immutable action's selected destination. Omitting the field
retains the legacy inspection/refusal behavior. This action data introduces no
CLI flag, grant or restore approval.

Protected staging still requires a fresh distinct target, the original current
authority, reviewed window acknowledgement, and clock, checkpoint, quota and
native fences. Require the actual restore receipt's `destinationIdentity` to
match the requested value, then use that actual identity as the restored node's
`state.storeIdentity`. An inspection result alone does not approve restoration.

## Source-bound qualification

Source `1e9fa9cdfa02e2a1e8098d2325908cc460fa2de2` passed 1,994 active
cases across eleven libraries, retained 66 ignores and completed 36 supervised
executions, including three Rust guest controls; all six default roles built
from that source. The signed early HTTP programme passed at the preceding
milestone, while complete terminal and pending recovery programmes failed at
their first current-authority restart. These results do not qualify later code.

The later restore-target milestone tested source
`bd7da024e55a955cba0ca0a7fae6cd5b728dbfcf`, tree
`eaf48f2df5b2e46df483670d20efa3ba8f04a209`: seven new identity/target controls
and all 378 active `latentd` cases passed, with 30 ignores unchanged. Native
formatting and strict maintained Clippy passed. Its integrated commit
`bad50d1e64df83a9c7c5bb45a1aae2ca2cb923be` has that tested tree. The unchanged
collector passed 46 focused Python controls on source
`e5f947af2da815488ce99c74027626c9d341c807`.

Fresh complete eleven-library and six-role evidence, signed terminal/pending
recovery programmes, packaged distributions and broader-ticket acceptance
remain required on the delivered final source. The
[parent's detailed record](https://github.com/KirilsTurkins/latent-service-fabric/blob/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/development/canonical-state-startup.md)
retains the original registration notes and qualification identities.

## Earlier source record

The detailed unexecuted schedules and remaining-work notes from the original
startup/capture milestone are retained at their
[original source](https://github.com/KirilsTurkins/latent-service-fabric/blob/1e9fa9cdfa02e2a1e8098d2325908cc460fa2de2/docs/development/canonical-state-startup.md).
They describe that milestone's boundary, not current installation support or a
fresh passing result. Current receipts keep their own source and environment;
this guide does not upgrade historical compiler/model evidence into native or
packaged acceptance.
