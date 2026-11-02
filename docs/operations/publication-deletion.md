# Delete retired publication payloads explicitly

Use this workflow for an exact tenant-scoped capsule or componentless-web
publication that is already retired or revoked, no longer referenced by any
retained deployment, HTTP trigger or rollout, and not held by a reader,
preparation source or rollback-retention pin. It is not orphan cleanup, an
age-based collector, or permission to delete business state, independent
publication evidence, trust/revocation history or audit records.

## Preconditions and capacity

Use a tenant operator/admin profile with the same authenticated identity for
both deletion and reclamation. Possession of an ID or a fence is not authority.
The node must have durable administrative audit configured, for example:

```json
"audit": {
  "mode": "durable",
  "records": 4096,
  "diskBytes": 67108864,
  "queuedOperations": 64,
  "queryOwners": 4
}
```

These are example finite limits, not additional automatic capacity. Read the
[standalone audit configuration](../reference/standalone-node.md) and
[capacity guide](publication-retention.md). A missing, unavailable or full audit
journal blocks maintenance mutations, including confirmed receipt replay; there
is no unaudited emergency exception. A response-size failure is also refused
before journal admission or catalog mutation. Each admitted attempt reserves
both an attempt and its outcome. Snapshot, assessment and original-operation
lookup are read-only and do not consume mutation audit records.

Stop competing release automation and explicitly remove retained control
references through their existing management APIs. Retirement alone does not
remove a deployment/trigger/rollout reference, and a denied route is still a
reference. Do not remove rows or files manually. Preserve a complete stopped
backup before destructive maintenance, including the coupled publication,
control, audit and protected policy roots, ownership, modes and hard links.

## Snapshot and rollback pins

The commands below use one publication. Repeat `--publication` or `--target`
for a batch of at most 32. The CLI orders targets canonically and rejects
duplicates; the wire contract requires that order. All generations are positive
canonical decimal integers, and fences are exactly 64 lowercase hex digits.

```sh
latent --config "$ClientConfig" --profile operator --output json \
  release retention snapshot --publication "$Publication" > retention.json
```

The response's `data.catalogFence` is the current fence. Each
`data.entries[].target` contains the exact publication and expected generation.
Copy the selected generation and fence into retained request variables before
mutation; an observation does not reserve authority for a later call.

```sh
latent --config "$ClientConfig" --profile operator --output json \
  release retention pin --operation-id "$PinOperation" \
  --catalog-fence "$PinFence" --target "$Publication=$Generation"
```

A pin prevents deletion but grants no execution, serving or rollback eligibility.
To release an intentional rollback pin, obtain a fresh snapshot and explicitly
use `unpin` with a new retained operation ID and that snapshot's fence. Do not
reuse the pin request as an unpin. Clearing a pin never deletes content.

## Remove visibility, then assess and reclaim

After removing all references/pins and quiescing readers, take another snapshot.
Persist the exact deletion operation ID, original fence and all targets. Do not
silently replace these values after a timeout or failed response.

```sh
latent --config "$ClientConfig" --profile operator --output json \
  release retention delete --operation-id "$DeletionOperation" \
  --catalog-fence "$DeletionFence" --target "$Publication=$Generation" \
  --maximum-wait-ms 10000 > deletion.json
```

A confirmed `visibility-removed` receipt means that public selection and
eligibility were durably removed. It does **not** mean that any payload capacity
was refunded. Next reproduce the **original** deletion selection for assessment:

```sh
latent --config "$ClientConfig" --profile operator --output json \
  release retention assess --operation-id "$DeletionOperation" \
  --catalog-fence "$DeletionFence" --target "$Publication=$Generation" \
  --maximum-files 1024 --maximum-bytes-hashed 67108864 \
  --maximum-wait-ms 10000 > assessment.json
```

`data.potential` describes verified logical namespace accounting, not disk blocks
freed and not permission to perform a later unlink. Save its current
`data.catalogFence` as `ReclamationFence`. Cleanup retains both distinct fences:

```sh
latent --config "$ClientConfig" --profile operator --output json \
  release retention reclaim --operation-id "$DeletionOperation" \
  --catalog-fence "$DeletionFence" --target "$Publication=$Generation" \
  --reclamation-fence "$ReclamationFence" \
  --maximum-files 1024 --maximum-bytes-hashed 67108864 \
  --maximum-wait-ms 10000 > reclamation.json
```

Reclamation uses the same operation ID and original actor/selection as deletion,
under a separate operation kind. A `namespaces-reclaimed` receipt records
synchronized publication-file removal and last-reference blob refunds. Shared
blobs remain while another capsule or web publication references them, including
another tenant's reference. Logical publication-link and blob charges must not
be added together as physical allocated bytes; the output leaves
`physicalDiskBlocksFreed` unmeasured. Measure actual storage independently.

A fresh mutation hashes content before and after audit/response preflight; both
passes share the selected work budget. Assessment hashes once. Thus a successful
assessment can still require a larger finite work limit for cleanup. The ceiling
is 1,024 file observations and 1 GiB of hashed bytes, with a 64 MiB byte default.
Each request's deadline is 1–30,000 ms and also respects the transport deadline.
An in-flight kernel operation cannot be forcibly cancelled; its ownership is
retained until physical completion. There is no automatic continuation loop.

## Recover the original operation, never guess a retry

```sh
latent --config "$ClientConfig" --profile operator --output json \
  release retention operation --kind delete --operation-id "$DeletionOperation"
latent --config "$ClientConfig" --profile operator --output json \
  release retention operation --kind reclaim --operation-id "$DeletionOperation"
```

For pins use `--kind pin` or `--kind unpin`. A lookup is scoped to the authenticated
tenant. `RELEASE_OPERATION_LOOKUP_DISPOSITION_FOUND` returns historical facts only,
not current eligibility. `RELEASE_OPERATION_LOOKUP_DISPOSITION_UNKNOWN`
includes finite receipt eviction and proves neither nonexecution nor permission
to issue a replacement mutation. `RELEASE_OPERATION_LOOKUP_DISPOSITION_UNCERTAIN` requires preserving the installation,
reopening its compatible native owners and querying the same ID. The CLI never
automatically retries a maintenance mutation or invents a new operation ID.

The catalog outcome and audit acknowledgement are separate. A committed receipt
with `outcome-unknown`/`audit-unavailable`, a lost RPC response or failed local
output must not be interpreted as proof that deletion did not occur. Retain the
CLI recovery context and query the original kind/ID; inspect the scoped audit
journal as well. Successful responses carry matching body/metadata audit
acknowledgements. An explicit replay of a retained exact request also needs audit
capacity and records its replay flag.

Startup reconciles unresolved publication audit attempts after native catalog
recovery and before generic release reconciliation. Only an exact matching
original request and preview-receipt digest establishes a committed outcome.
Missing/evicted/mismatched receipts remain unknown, uncertain catalog health
blocks reconciliation, and reconciliation never invokes a mutation. An audit
outcome already recorded as unknown is not rewritten later merely because the
catalog subsequently recovers a receipt.

## Retained history and qualification limits

Payload cleanup does not compact the independently charged lifecycle/web HEAD,
selected evidence, trust/revocations, audit, or compact negative identities.
Retention pins, tombstones/negative identities and operation rings retain their
[finite limits and recovery contracts](../reference/publication-retention-pins.md).
Plan headroom for those owners; a larger payload refund does not imply infinite
release history. Do not remove protected markers to force an older reader to open.

Tests cover native catalog/audit files, authenticated management requests, and
actual CLI subprocesses through reclamation, audit exhaustion and original lookup
after native reopen, alongside grammar/projection/recovery validation. Injected failures are not physical power-loss
proof, and trusted-local publication fixtures are not signed-site qualification.
Full signed public release/deletion/restore qualification and independent history
compaction remain separate issue #662 work. A complete stopped installation is
the restore unit; never combine an old control snapshot with newer reclaimed
publication state.
