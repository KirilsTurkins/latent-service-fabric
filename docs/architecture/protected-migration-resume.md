# Explicit fixed-migration activation

The fixed [migration owner](../../crates/latent-state/src/recovery/migration.rs)
persists a complete new business format and schema epoch while leaving its
namespace quiescing and history awaiting review. Completion is not activation.
`MigrationResumePlan` adds an explicit original operation for this narrow profile.
It compares the exact completed migration request and progress, current 67-byte
NV2 view, namespace, schema history and global recovery guard. Its accepted schema
must match the original package, declaration and tested proof. Incomplete work,
changed original inputs, unsupported schema, exhausted counters and stale plans
refuse before activation.

The resulting closed LMR version 1 receipt retains the full original migration
and activation inputs, paused namespace/history and exact original progress
digest. Activation atomically writes the active namespace, ready history and
receipt, increments only the namespace generation, and charges the new metadata
through the same tenant ledger. It changes no business cell, command, effect,
payload, inbox identity, schema epoch or recovery epoch. Its retained format is
`latent.migration-resume.v1`, independent of business and storage formats. The
original progress remains linked and required; dropping its decoder or row
cannot turn receipt recovery into an absent operation.

`inspect_receipt` is descriptive recovery under the host's separate current read
permission. A later namespace pause or global restore review does not rewrite the
historical activation result. Original receipt replay compares every original
input and prepares no mutations. It still checks actual current rows and tenant
configuration and requires a present current-authorized reviewer. Refreshing the
NV2 token, replacing the operation ID, or using old receipt bytes to reopen a
paused namespace is unsupported.

`ProtectedStoreOwner::resume_migration` consumes the same affine protected
snapshot custody used for migration. The actual original storage owner excludes
live views, callbacks, dispatch, writers, maintenance and retirement backlog;
there is no caller-supplied quiescence flag. It re-reads the original private file
on the fixed Recovery worker, checks its exact original checkpoint digests,
validates required artifacts and current linked work, then invokes the current
reviewer. The final actual engine writer retains namespace/history/guard,
progress, receipt and tenant CAS checks. The reviewer holds its original short
policy, namespace and effects fences before consuming the affine original-native
acceptance gate. No file I/O, guest call, clock renewal, audit flush or await
belongs inside those fences. Post-acceptance loss cannot become no-commit proof;
the exact original receipt must be recovered.

Existing `AggregateMigrationOwners` deny the new review and acceptance callbacks
by default. A production host must supply actual current operator policy,
critical audit, selected publication/schema evidence, conservative protected
clock continuity and retained-work review. Configured IDs, receipt digests,
`ReviewedSchema` data or a declared range are not grants. The lower implementation
does not create a schema/publication installation owner or refresh an old grant.

The response has its own prepaid buffer permit on the same original native
reservation. Receipt and request metadata are destroyed before that permit and
reservation. Positive native file retirement cannot refund a still-retained
response; the transport must carry this same response owner through its last
physical encoded frame. Waiter loss detaches the already accepted worker and
cannot release the file, authority inputs or global capacity early.

The nonmutating `review_restore_window` read follows the same physical response
rule. Before decoding the original private archive, it reserves an 8 MiB response
permit from that archive's existing native reservation. The source manifest and
canonical window are each bounded by 1 MiB, with at most 128 namespace, retained
format and artifact entries; current closure collections must also fit those
limits, including retained allocation capacity. The returned
`ProtectedRestoreInput` retains the exact original reservation and installed
current read, audit and artifact owners after positive file retirement.
`encode_window` carries that owner through the last actual frame. A smaller
original response declaration refuses before archive decode; expired original
deadlines or revoked current read decisions refuse without renewing authority.
The native capacity profile and its existing request ceilings stay unchanged.
Six additional source-registered schedules exercise these response cases; their
native execution remains pending. None supplies a Fresh destination or restore
approval.

Thirteen source-registered schedules cover Count and captured Java format
activation, actual original receipt/restart recovery, stale and wrong-scope
requests, revoked current review, actual guard races, incomplete migration,
metadata high water, original expiry, corrupt input versus source uncertainty,
old token refusal, detached worker cleanup and response custody after file
retirement. The reviewers are controlled fixtures. **Native compilation, these
schedules and Clippy are pending the shared compiler hold.** Source formatting
and repository checks establish neither authenticated Node/CLI qualification nor
whole-ticket completion.

An older-history restore cannot reuse this activation path: its recovery history
differs from the original migration result. Its separate [paused review
guard](offline-recovery-guard.md), Fresh destination, mode marker, current owner
and clock floors, external checkpoint and explicit reconciliation/resume remain
owned by their actual producers. This source adds no restore approval, automatic
redrive or automatic business-data downgrade. The public management protocol
remains its frozen sixteen-operation surface; migration/backup CLI and six-client
extensions and signed deployment/canary/rollback schema installation are still
outstanding requirements.
