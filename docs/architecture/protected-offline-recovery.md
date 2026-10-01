# Protected offline recovery

The first physical profile is Linux x86-64 on an explicit local ext4 root.
`OfflineRecoverySource` uses the same bounded embedded engine and fixed storage
workers as ordinary commands. It exposes backup, inspection and fresh-root
restore operations, with no guest, command, query, dispatcher or expiry entry.
Its installed `RecoveryCodecs` owner supplies immutable artifact checks, actual
linked row/payload/format validation, current operator authorization and review.
These callbacks may perform only bounded local work; they may not run guests,
shells or provider effects. Application reader declarations are insufficient
for decoding retained commands, results, inbox entries, effects or payloads.

The operator workflow is:

1. Close affected command, query, consumer, dispatch and maintenance admissions.
   Quiesce every namespace in the selected root. Drain actual commit, view,
   physical-request and dispatcher owners, then close the ordinary engine.
   Offline startup requires an existing private root and engine, an exclusive
   owner lock, quiesced namespace metadata and valid linked recovery inventory.
   A dropped waiter, timeout or live descriptor does not establish retirement.
2. Select a pre-existing private ext4 destination and safe leaf name. Review the
   exact operator, tenant, installed runtime and artifact associations. Backup
   creates a private file exclusively; it never reopens or overwrites an old
   partial export. The canonical logical stream uses the selected engine's
   consistent view, covers every family, validates linked closure and immutable
   artifacts, syncs the file and reads it back before returning a receipt.
3. Inspect the exact private snapshot with its expected digest and installed
   decoders. This reports the actual current recovery window and checks target
   capacity before creating a staged engine. A stale acknowledgement, missing
   artifact, unknown runtime, unsupported retained format, bad path, corruption
   or current authorization failure refuses restoration.
4. Acknowledge that exact window and review the explicit fresh private root.
   Restoration locks and creates its engine exclusively, writes `Staging`
   before importing, rechecks protected file identities around every durable
   write and validates the complete linked view. It retains original business,
   command, effect and inbox identities while advancing the live recovery
   epoch. The engine is flushed and physically closed before its receipt is
   returned. The resulting guard and namespace histories remain paused.
5. Reconcile current publication, provider, result-read and consumer permissions;
   original grant horizons; uncertain or post-backup remote effects; newer
   commands and inbox deduplication history; and conservative clock continuity.
   Only separately reviewed activation and resumption can accept this history.
   Pending snapshot rows never authorize automatic redrive or expiry.

Input and target failures do not poison or replace the current source. Every
accepted operation retains its physical worker, scratch accounting and
exclusive root until actual completion, even after its waiter is dropped.
A drain deadline leaves that ownership quarantined until physical retirement.
Private partial exports and failed staged roots remain operator evidence and
must use new destinations for a later attempt.

The snapshot codec bounds are 65,536 rows, 128 MiB logical data, a 160 MiB file,
128 namespaces, 128 immutable artifact references and a 1 MiB canonical
manifest. Scans and import batches are bounded to 128 rows and 4 MiB. The
physical operation reserves 32 MiB scratch plus the installed codec's bounded
scratch and retained paths; staged engine cache is at most 8 MiB. These bounds
do not silently raise the selected engine's own quotas. The original operator
deadline, at most one minute, applies throughout inspection, review and writes.

The finite physical fixture uses actual protected engines and schema-bound
state. It covers fresh restore and paused history, a live ordinary owner,
active namespace refusal, missing roots, lost waiter retirement, missing
artifacts, current authorization loss, bad digest and an existing failed
destination. Its installed runtime and empty retained-work inventory are
closed fixture inputs. Real command/result/inbox/effect closure and the case
where a remote effect succeeded after a pending backup require the composed
transaction and qualified transport owners; this fixture does not certify them.
Backups contain sensitive application data and are never public test artifacts.
