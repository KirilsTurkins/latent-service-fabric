# Namespace persistence and current authority

Issue [#384](https://github.com/KirilsTurkins/latent-service-fabric/issues/384)
uses the selected shared embedded engine for namespace metadata and management
operation receipts. `NamespaceCatalog` retains bounded lifecycle metadata only;
it owns no engine `Arc`, file, worker or provider pool. Run `inspect`, `prepare`,
`outcome` and `page` with the borrowed `EmbeddedStore` supplied by the protected
owner's fixed worker. `read_in` and `page_in` borrow its actual retained
`ReadView`. They never open a database or turn an ID into permission.

Namespace rows contain tenant, independent namespace ID, nonzero incarnation
and generation, schema digest, lifecycle status, quotas and durable protection
counts. A namespace row is at most 4096 bytes; its operation receipt is at most
8192 bytes. IDs are at most 256 UTF-8 bytes. A page has at most 128 records and
1 MiB of row bytes, uses the physical engine ordering and returns a continuation
only when another matching row exists. The native view must remain owned for
all pulls of the same page. The default live registry admits at most 4096
namespace metadata slots and 4096 actual activation/query owners.

`NamespaceCatalog::validate_row` is the bounded startup decoder for the
`Namespace` family. Register it with the protected owner's startup validation
alongside the other families' decoders. It checks canonical framed keys,
scope, record and receipt formats, historical requests and their outcome
versions. Unknown keys, unsupported formats, missing bytes, trailing bytes and
mismatched scopes prevent readiness; startup never replaces them with an empty
store.

## Lifecycle operations

`NamespaceControl` requires a current sealed policy decision for the exact
tenant, namespace and incarnation. Its stable operation context is derived
from the authenticated principal, without token IDs or untrusted claims. The
namespace replacement and immutable management receipt have exact expected
rows in one physical `AtomicBatch`. Retrying a changed request with the same
operation ID conflicts. Replaying a historical receipt additionally requires
current `namespace-inspect` permission and a current namespace row. An old
incarnation's grant cannot inspect or replay a recreated namespace.

The explicit lifecycle is create, active, quiescing, retired, tombstone, and
explicitly approved recreation. Quiescing closes new commands and invalidates
existing command/query/page authority at logical acceptance. Retirement,
destruction and recreation check actual live owners under the same fence; a
caller-supplied count is only a preliminary check. Destruction also requires
zero durable result, unresolved-effect, payload-reference and inbox protection
counts, and retains the metadata tombstone. Recreation increases both
incarnation and generation. Deploying or revoking a publication cannot create,
delete or share a business namespace.

Inside the actual engine writer, after staging and namespace row CAS,
`NamespaceControlFence::accept` reserves a creation slot or advances the live
lifecycle fence. Hold its affine completion through physical I/O. Resolve it
only from a fresh native namespace row after actual commit or explicit recovery.
An abandoned or uncertain completion leaves admission closed. A restart reads
the persisted row with a new bounded owner; it does not infer an abort from a
dropped waiter. Retained handles keep their actual metadata counts until drop,
even after invalidation, so they continue to block retirement. Registry shutdown
also invalidates every retained handle without retaining the engine file.

## Command, query and recovery access

`NamespaceAuthority::seal` takes a decision from the existing policy owner, a
coherent native namespace row, the exact binding schema, trusted recovery
selection and a real `NamespaceLifecycleHandle`. It captures the original
policy revisions and exact publication in an owned bounded lease, suitable for
the fixed worker. Dropping borrowed preparation objects cannot refund that
lease or refresh its grant. A copied allow result, namespace descriptor, cursor
or publication string cannot construct this authority.

Every operation checks the captured grant and a fresh operation decision under
one current policy/publication fence, then checks the mutable namespace fence.
The logical read view alone cannot detect a concurrent lifecycle change, so the
actual handle is mandatory for reads and pages as well as writes. Command and
query operations remain distinct. Read/result/effect access is checked before
lookup and again before exposing bytes or counts. Commit preparation additionally
requires the actual batch to retain the exact coherent namespace expectation.

State policy resources are exact tuples of namespace, incarnation, optional
entity, recovery kind, recovery scope and result-policy identity. A missing
entity is rejected by the closed codec; namespace-wide access explicitly uses
`null`. Tuples do not create a cross-product of separately approved entities
and callers. The exact state and intent capability versions are opt-in; the
supported stateless import set remains unchanged. Internal `commit`, result,
cancellation and management operation labels are derived by trusted host
binding/management code and checked through the same policy intersection. They
are not additional WIT functions or authority supplied by a guest.

Recovery domains are derived from stable authenticated facts: original caller,
service integration, explicit delegation, or an explicitly approved named
shared domain. Tenant/execute access alone grants none of these domains. Caller
scopes include principal kind and subject; token rotation and claimed tenant or
recovery headers cannot change them. Historical results and rejections also
retain entity and result-policy identity. Shared replay requires current
membership in the exact approved tuple; delegated replay requires the current
delegation. An unavailable guest-only visibility decision fails closed. These
ports never replay a mutator to decide visibility; an approved bounded read-only
hook must be implemented separately if the application requires one.

## Final commit acceptance

`CommitIoAcceptance::accept_with` is affine and runs only in
`EmbeddedStore::apply_fenced`. The lock order is current policy/publication,
namespace lifecycle, effect rules, then the cancellation CAS. The effect owner
returns a bounded guard from the callback; it stays held through the final
open-to-accepted CAS and drops before the callback returns to physical engine
I/O. No callback performs disk I/O, guest execution or a blocking wait. A failed
effect revalidation leaves acceptance unconsumed and all staged families
unmodified. Once accepted, cancellation cannot imply abort, refund or successful
durability; the actual writer retains its protected owners until completion or
explicit recovery. This is the logical acceptance boundary described in
[the writer fence](transaction-writer-fence.md).

## Verification boundaries

Native-row tests exercise bounded startup decoding, tenant-scoped coherent
pages, namespace/receipt atomicity and reopen, competing CAS updates,
incarnation monotonicity, actual lifecycle owners, cancellation, current policy
and exact publication withdrawal, separate same-tenant callers, explicit shared
and delegated scope, current result/effect permissions, page isolation, owned
policy leases and effect-guard lifetime. Actual authority fixtures use the
existing policy/catalog owners and the selected redb engine; they do not execute
a guest. The node's protected-store, transaction writer, authenticated management
RPC/CLI, audit and tenant-cleanup integrations retain their own acceptance gates
in #383, #385–#388, #400 and #408–#409. The schedules establish these ports'
behavior without claiming those integrations have already passed.
