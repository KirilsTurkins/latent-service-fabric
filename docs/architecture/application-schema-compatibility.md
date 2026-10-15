# Exact application schema compatibility

An application schema ID is `sha256:` followed by the hash of its exact bounded
definition bytes. It describes application data, independently of the selected
engine format, package digest, WIT version and publication. The aggregate v1 and
v2 definitions in `contracts/state` describe eight-byte little-endian and tagged
twelve-byte data respectively. Their source bytes are immutable identities;
changing the definition changes the schema ID.

`namespace::compatibility::SchemaDeclaration` binds one exact package SHA256 to
at most eight distinct reader and eight distinct writer schema IDs. The installed
host reviewer must accept the canonical declaration digest and an exact nonzero
conformance proof digest before constructing `ReviewedSchema`. A declaration or
claimed range cannot establish compatibility for arbitrary opaque application
values. These metadata ports confer no publication, migration or access authority.

`require_composition` checks the current namespace schema and every selected
writer against every selected reader, for at most eight exact package revisions.
The compatible aggregate v2 canary reads v1 and v2 but continues writing v1.
After a separately quiesced and validated migration, the v2 writer emits v2;
selecting the old v1 reader then refuses. Ordinary code rollback never rewrites
business values or rolls back external effects. Deployment and commit owners must
call this port under their existing current publication/policy fences; these
foundation ports alone do not claim completed deployment integration for #398.

Retained work uses its own exact format identities. `RetainedInventory` bounds
the observed linked work to 128 identities, 65,536 observations and 128 MiB and
refuses overflow without changing the prior inventory. The installed codec owner
must cover effect envelopes, payloads, adapter profiles, success and rejection
results, fingerprints, attempts, inbox identities, ordering groups and migration
checkpoints. Removing an old decoder or changing an inbox subscription is not
made safe by a new application schema. Planned migration or drain is not accepted
as actual decoder coverage, and unresolved original work blocks normal retirement.

The inventory is built by trusted decoders from one actual coherent store view.
Its counts and original associations remain descriptive: they do not authorize
result replay, renew a revoked grant, move work to a replacement publication or
permit skipping an ordered predecessor. The current
[installed recovery reviewer](../../apps/latentd/src/standalone/state/recovery/profile.rs)
checks exact signed Java declarations, captured source/codec/HTTP marker and
executes its fixed reader/writer conformance before accepting `ReviewedSchema`.
Its [linked catalog reviewer](../../apps/latentd/src/standalone/state/recovery/catalog.rs)
validates actual retained command/result/effect associations. Extra decoder
publications supply original decoding sources, never new execution permission.
This is a closed installed recovery profile, not a general schema evaluator or
automatic deployment/canary compatibility gate. The broader deployment, native
application and packaged qualification remains separate. See
[fixed migration](fixed-aggregate-offline-migration.md) and the
[installed qualification](../testing/installed-transaction-recovery.md).
