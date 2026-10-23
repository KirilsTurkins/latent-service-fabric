# Stopped-node audit-journal lifecycle

This is the bounded local-owner lifecycle for the durable administrative journal
at `dataDirectory/audit`. It is not publication/content retention, a background
exporter, or permission to disable audit. Required administrative mutations still
fail closed when their audit admission cannot be reserved.

## Decision and availability boundary

The first lifecycle implementation uses **explicit stopped-node maintenance**.
`latent audit maintenance` calls the existing `latent-audit` filesystem owner;
it never moves a live journal directory or starts another audit worker. Stop the
node and its supervising restart loop before maintenance. The existing root lock
must be acquired exclusively. A worker with a started critical attempt keeps that
lock until its actual completion or abandonment; a timed-out shutdown does not
release ownership merely because its deadline elapsed.

Maintenance needs no ordinary audit-record reservation. Consequently a healthy,
fully record-exhausted journal can be sealed without granting a mutation or using
the revocation exception. Filesystem space for the bounded transition marker and
verified archive is still required. Unavailable storage is a refusal, not an
instruction to delete history.

This profile causes node downtime. Schedule it before both audit headroom and
publication-evidence freshness become critical. Stopping a node or changing an
epoch does not extend evidence validity. After maintenance, normal authorization,
verification, freshness and route preconditions remain mandatory. A stale signed
publication can still correctly return HTTP 403.

## Authorization

Run these commands on Linux as the **effective UID that owns the node's private
journal**. `--local-operator` acknowledges this distinct local authorization
boundary. The commands reject explicit RPC configuration, profiles, endpoints and
RPC timeout options; they do not load ambient credentials or connect to a node.
They are not a tenant-management endpoint.

Every root, retained file and ancestor is checked by the existing private-path
owner. Symlinks, foreign ownership, unsafe permissions, hard-linked record files,
unknown files and inconsistent history fail closed. A root-owned sticky system
temporary ancestor is the existing narrowly allowed exception. Root paths must
be separate, bounded and canonical; an archive cannot be nested inside its active
journal or another selected custody root.

The authenticated live `latent audit query` path is unchanged: tenant scope must
match the authenticated tenant, and node scope additionally requires the trusted
node-operator claim. Offline archive queries require filesystem ownership and an
explicit scope filter. A supplied tenant, archive, receipt or cursor is not an
RPC authorization credential.

## What a rollover preserves

The archive contains the original `MODE`, `HEAD` and record files byte for byte,
plus a bounded canonical `SEAL`. The seal binds the journal and epoch identities,
first and next sequence, record count and bytes, head digest, original header
hashes, predecessor seal, successor epoch and original maintenance operation.

The active root keeps its original filesystem lock. Its new epoch starts at the
old epoch's next sequence, with the previous head as its chain seed. **Global
sequences do not reset.** Existing audit attempt acknowledgements therefore do not
collide merely because maintenance created another epoch. The new version-2 mode
marker records the predecessor linkage and cumulative unknown-outcome count.

Unrolled version-1 journals remain readable. Once rollover has written a version-2
mode marker, an older implementation that does not understand it must reject the
root. Do not downgrade by replacing its mode marker or creating an empty journal.

A seal and SHA-256 chain detect inconsistencies within the private-filesystem
threat model. They are not signatures, an external witness, or protection against
the filesystem owner rewriting all history.

## Finite custody and work

| Resource | Bound |
| --- | --- |
| Active epoch | Existing configured limit; at most 16,384 records and 256 MiB of record bytes |
| Locally retained archive suffix | Four epochs and 1 GiB of record bytes in one explicitly selected custody root |
| In-progress archive staging | One epoch; included in the destination slot/byte admission, never a fifth archive |
| One explicit transfer destination | One sealed epoch; at most 16,384 records and 256 MiB of record bytes |
| Custody index and seal | 4 KiB each; no unbounded archive catalog |
| Rollover or transfer marker | 16 KiB each; only one transition may own the journal |
| Individual copy buffer/staged record | Existing 16 KiB record ceiling; records are copied individually |
| Offline query | At most 128 records, 256 KiB requested page allowance and 1,024 scanned entries per page |
| Maintenance invocation | One synchronous caller, no added worker or per-publication resource; explicit 1–120 second cooperative deadline |

Record-byte limits are not filesystem-allocation estimates. Provision additional
bounded space for directory entries, headers, metadata, the active epoch and an
external transfer copy. Verification uses a fixed number of bounded scans, not
an unbounded directory walk. Each epoch scan uses the existing hard record,
record-byte and metadata validation limits; each index contains at most four
archive descriptors. A history query verifies its selected archive before paging.

Deadline checks occur between bounded operations and during record scans/copies.
A filesystem call that physically blocks cannot be made to stop by returning a
fictional clean-shutdown acknowledgement. Its process and filesystem ownership
remain real until it returns or the operating system terminates that process.
An interrupted transition remains recoverable from its original durable marker.

## Planning before exhaustion

The maintained `tools/static-release/audit-headroom.mjs` calculator consumes an
explicit node-scoped usage snapshot and the actual audit configuration:

```sh
node tools/static-release/audit-headroom.mjs \
  --usage /private/operator/audit-usage.json \
  --audit-config /private/operator/audit-config.json \
  --route-pairs 1 --diagnostic-records 2 --competing-operations 1 \
  --warning-percent 80 --cadence-minutes 10 --output human
```

Both input files must be private ordinary files. The configuration file contains
the node's audit object, for example `{"mode":"durable","records":4096}`. Usage
is either the native CLI result containing `data.nodeUsage`, or that node-scoped
usage object itself. The calculator refuses missing/unavailable counters rather
than treating them as zero. It does not establish snapshot freshness, filesystem
free space or future admission, and does not create a reservation.

One renewal plus GET and HEAD mutations needs at least six critical records.
At ten-minute cadence that lower bound is 864 records/day; 4,096 records represent
about 4.74 days from empty, and 16,384 about 18.96 days. These are arithmetic, not
measured lifetimes. The default planning margin instead charges ten records and
160 KiB per cycle: six critical records, two diagnostics and one competing
critical operation. Actual competing traffic is not bounded by this calculation.

Charged reservations are subtracted from record and byte headroom. Queue,
metadata, pending-attempt and storage/recovery state are independent pressure
sources. Configurable warnings remain useful when the journal cannot append a
warning record because the calculation is read-only. There is no new guest
observer, tenant-labelled metric, timer or collector.

The stopped-owner `status` command below gives verified active-epoch facts, but
is not a live reservation. A complete live renewal preflight integration and
real-node sustained-renewal qualification remain separate delivery checks for
issue #990; this guide does not claim those checks have passed.

## Executable stopped-owner workflow

The examples use explicit paths. Replace them with the installation's actual
private directories and execute as its owning service UID. Stop the service and
its automatic restart supervision using the installation's service manager.
Do not stop only a CLI while leaving the node running.

```sh
umask 077
JOURNAL=/srv/latent-data/audit
ARCHIVES=/srv/latent-audit-archives
OPS=/srv/latent-operator
install -d -m 700 "$OPS"

latent --output json audit maintenance status \
  --local-operator --journal "$JOURNAL" > "$OPS/audit-status.json"

EPOCH=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["data"]["epoch"])' \
  "$OPS/audit-status.json")
OPERATION=$(python3 -c 'import secrets; print(secrets.token_hex(16))')
printf '%s\n' "$EPOCH" > "$OPS/rollover.epoch"
printf '%s\n' "$OPERATION" > "$OPS/rollover.operation"

latent --output json audit maintenance rollover --local-operator \
  --journal "$JOURNAL" --archives "$ARCHIVES" \
  --expected-epoch "$EPOCH" --operation-id "$OPERATION" \
  --deadline-seconds 120 > "$OPS/rollover-result.json"

latent --output json audit archive verify --local-operator \
  --archive "$ARCHIVES/$EPOCH" --epoch "$EPOCH" \
  > "$OPS/archive-verification.json"
```

Record the original paths, epoch and operation identity before invocation. A
successful result reports `durability: confirmed`, the successor epoch, unchanged
global next sequence and archive seal digest. After an interrupted command, reuse
those same inputs; do not generate another identity as a retry mechanism.

Restart the node with durable audit still configured. Recover any application
operation through its actual owner's retained receipt and current state. A
historical receipt or archive does not prove present eligibility and never
authorizes repeating a possibly committed mutation.

## Inspecting an archive or the local suffix

```sh
latent --output json audit archive query --local-operator \
  --archive "$ARCHIVES/$EPOCH" --epoch "$EPOCH" \
  --scope tenant --tenant tests --page-size 32 --maximum-bytes 65536

latent --output json audit maintenance custody --local-operator \
  --archives "$ARCHIVES" --journal-id ORIGINAL_JOURNAL_ID
```

Copy `nextPageToken` unchanged into `--page-token` to request another page of the
same epoch, scope and filters. `--actor`, `--from-unix-millis` and
`--to-unix-millis` filter durable acceptance timestamps. Node-scope offline queries
must omit `--tenant`. No page is drained automatically.

An old cursor cannot silently continue into the successor epoch. Pagination keeps
its frozen horizon, independent count/byte/scan stops and original scope. The
active epoch's retained floor can exceed one; an empty new epoch correctly has a
high watermark immediately below that floor.

Offline records use the explicitly named
`latent.audit.stored-record.decimal-counters.v1` JSON format. Every unsigned
numeric field, including `formatVersion`, is a decimal string. The archive itself
retains the original canonical bytes; this presentation is not a byte-for-byte
export or a new mutation API.

Coverage identifies exactly one epoch or the verified local suffix. It reports
cumulative unknown outcomes through that head and prior-session loss uncertainty.
Zero current dropped-observation count does not prove that earlier sessions lost
nothing. Custody inspection explicitly labels transferred history availability
`not-observed`; missing external storage is not complete local history.

## Verified transfer and local-capacity release

Before a fifth local archive would be needed, transfer the **oldest** retained
epoch to one explicitly chosen, independently provisioned private destination.
The destination must not be nested inside the journal or local custody root.

```sh
latent --output json audit maintenance transfer --local-operator \
  --journal "$JOURNAL" --archives "$ARCHIVES" \
  --destination /mnt/operator-history/EXACT_EPOCH \
  --epoch EXACT_EPOCH --expected-seal EXACT_SEAL_DIGEST \
  --operation-id ORIGINAL_TRANSFER_OPERATION --deadline-seconds 120
```

Use the epoch and seal from verified custody inspection and a new 32-character
lowercase hexadecimal operation identity for this **new** transfer. Retain all
selectors for recovery. This command durably copies and verifies the destination,
records the finite transferred boundary, and only then releases the matching
local copy. An unavailable/full destination cannot authorize local deletion.
Every incomplete transfer resume re-verifies the actual destination before
releasing more local capacity.

External retention, backup, available space and eventual disposal are the
operator's custody responsibility. The node does not accumulate an unbounded
archive catalog or claim to verify external history indefinitely. A completed
transfer receipt is historical evidence of transfer, not a promise that its
external destination remains mounted or intact later.

## Interruption and full-capacity recovery

| Observation | Required action |
| --- | --- |
| `audit-critical-pending` | Restart the original node to reconcile the original operation with its owner's retained receipt. Missing/evicted receipts remain unknown. Do not invent a rejection or replay. |
| `audit-maintenance-reopen-required` | Allow ordinary append-intent recovery in the original node before maintenance. Do not delete its staged record or intent. |
| `audit-maintenance-resume-required` | Keep the node stopped and repeat the original rollover/transfer command with unchanged identities and paths. |
| `audit-archive-capacity` | Perform an explicit verified oldest-archive transfer; increasing active-record limits only postpones exhaustion. |
| Identity/epoch mismatch | Inspect the retained original command and receipt. Do not overwrite a marker or substitute another archive. |
| Corrupt/missing/foreign/symlinked history | Preserve all files and diagnose integrity. No destructive cleanup or automatic archive repair is performed. |
| Deadline or lost response | Outcome is not established by the missing reply. Wait for the physical owner to exit, then resume the original operation. |

The implementation qualifies interruption after marker publication, record copy,
seal, archive publication, custody-index sync, partial record release, new head,
new mode and final marker removal. Restart either reopens the valid completed
epoch or refuses admission until the original exclusive transition resumes.
A sealed copy with missing bytes is corruption, not an opportunity to reconstruct
history silently from whichever other copy happens to be available.

## Qualification boundary

The library regression suite covers multiple epochs, preserved acknowledged
bytes, full-record capacity, finite custody, verified transfer, corruption,
pending/unknown attempts, live ownership, original-operation recovery and
cross-epoch cursors. Native CLI regressions exercise the local grammar and
explicit history workflow. These are bounded executed fixtures, not a multi-day
production soak.

Issue #990 is not complete until the maintained live preflight, signed static
renewal/GET/HEAD sequence, real Linux node plus CLI multi-epoch fixture, negative
freshness-expiry denial and repository-wide CI are also qualified. Reported
alpha.4/alpha.5 incident facts must remain separate from new execution evidence.
