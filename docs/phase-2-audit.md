# Phase 2 audit

`latent-audit` provides a bounded durable journal for security and administrative
history. An optional node configuration opens one filesystem owner and one
worker, shared by management, admission verification and native-cache producers.
It creates no worker per tenant, release or service. See
[standalone node configuration](reference/standalone-node.md#optional-durable-audit)
and the closed [configuration schema](../schemas/node-audit.schema.json).

The standalone node stores the journal at `dataDirectory/audit`. Omission permits
unaudited operation only while that reserved path is absent; existing history,
partial initialization or a symlink prevents silent downgrade. Linux is the
supported standalone configuration. The native journal requires Unix filesystem
semantics and explicitly rejects unsupported platforms before mutation.

The earlier `BoundedPhase2AuditJournal` remains an explicit volatile embedding
API. It starts no worker and loses its records on restart. Its bounded metadata
maps and secret-bearing-key checks do not provide the durable guarantees below.
The production implementation evolves the event vocabulary and memory journal
contributed in PR165.

## Typed records and identity

Each `AuditStoredRecord` has a version, journal epoch, monotonically increasing
sequence, previous-record digest, durable acceptance timestamp, scope and actor.
Its closed payload is one of three forms:

| Payload | Meaning |
| --- | --- |
| `AuditObservation` | A diagnostic result with a fixed event kind, outcome, reason and optional cache kind. Acceptance queues it; it does not acknowledge durability. |
| `AuditOperationAttempt` | An attributed control operation with operation ID, exact request digest, action, expected generations and explicit replay flag. |
| `AuditOperationConclusion` | A terminal result linked to its attempt sequence: `Committed`, `Rejected`, `NotStarted` or `Unknown`, with a receipt digest only where established and an optional typed canary decision summary. |

Tenant and node scope are distinct. Management actors come from the authenticated
principal; internal producers use fixed host actors. Identifiers remain separate:
validated package manifest, component release, digest of received manifest bytes,
selected evidence revision, policy role/scope/generation/digest, deployment and
deployment generation, rollout, revision, route generation and lifecycle
generation. Absent identities stay absent. A digest of rejected manifest bytes
does not assert a valid package, and trusted-local content has no invented
package identity.

Release attempts also require the digest of the entire validated canonical
prospective lifecycle receipt. This binds the exact preview while preserving its
status as a preview. Expected lifecycle and deployment generations use separate
fields. These records, copied receipts and diagnostic successes grant no
admission, execution or promotion authority.

The durable model has no arbitrary attribute map or free-form reason text.
Strings, policy rows, digests and complete encoded record envelopes are checked
before queue admission; unknown fields, duplicate fields and explicit null
options are rejected. Raw envelopes, credentials, private paths, signing keys,
payloads and external error bodies are not audit fields. Event kinds and reasons
are suitable fixed metric dimensions; identities and digests are not.

## Mutation durability and ambiguous outcomes

The release adapter validates the complete prospective success or rejection
response before beginning the critical audit protocol. `ReleaseAuditGuard`
reserves both an attempt record and its terminal record, then waits for the
attempt to become durable on the existing bounded control worker. Only afterward
does it mark the mutation started and enter the catalog operation. Audit waits
occur outside lifecycle, signing-authority and catalog commit fences; the audit
worker never calls back into those owners.

The guard accepts a known conclusion only from the actual matching lifecycle
receipt, or an exact scoped retained operation lookup after an error. The request
identity and full preview receipt digest must match. Exact retries record the
original receipt and replay flag; they do not claim a second state transition or
fresh eligibility. A prospective receipt alone cannot prove a commit.

With audit configured, publication, retirement, evidence renewal and deployment
apply/delete fail before mutation when their required audit begin cannot be
accepted. **Revoke alone** may continue on audit capacity or availability failure:
its ordinary durable lifecycle transaction is still mandatory, and the response
reports `AuditUnavailable` while a fixed counter records the gap. This exception
does not bypass authentication, validation or the lifecycle ledger.

Mutation disposition and audit acknowledgement are independent. A committed
catalog operation stays committed if terminal audit storage fails. Its
acknowledgement is `OutcomeUnknown`, not a fabricated rejection or rollback.
Likewise, a durably recorded `Unknown` conclusion does not become a known outcome
merely because its record was written successfully. Responses expose `Durable`,
`OutcomeUnknown`, `AuditUnavailable` or `Disabled`, with the attempt sequence when
one exists. Direct host embeddings must explicitly compose the same adapters;
the directory catalog is also usable without them.

Dropping an accepted attempt before `mutation_started` produces `NotStarted`;
dropping it afterward produces `Unknown`. Its prepaid terminal capacity remains
owned by the worker. Deployment adapters bind the normalized request and actual
returned deployment/catalog generation. The deployment catalog has no retained
idempotency receipt for crash reconciliation, so an unresolved deployment
attempt recovers as unknown.

## Storage, recovery and retention

The journal uses private current-UID directories (`0700`) and ordinary files
(`0600`), one root lock, an immutable record file per sequence, a durable head and
one bounded intent. Ancestor inspection rejects symlinks, foreign ownership and
unsafe writable parents, except root-owned sticky system temporary directories.
Missing ancestors are created privately and synced after bounded lexical path
validation. Unknown files, links and malformed retained history are preserved and
cause failure rather than being silently removed or adopted.

An append syncs its staged record and intent, publishes the exact record, then
syncs the new head before acknowledging durability. Recovery validates hashes,
lengths, canonical records and the old/new head relationship before rolling a
single interrupted transaction forward. It never resets the sequence behind a
missing acknowledged record. The mode marker distinguishes interrupted first
initialization from disappearance of a previously initialized head. Per-append
write work is bounded independently of retained history; startup scans are
bounded by the configured count and byte ceilings.

The SHA-256 chain detects inconsistent or missing content within the trusted
private-filesystem boundary. It is not a MAC, signature, external witness or
protection against the node owner rewriting the whole journal and head.

Startup opens the journal before catalog recovery and reconciles its at most one
pending critical attempt before serving management requests. A matching retained
release receipt establishes the outcome. An absent or evicted lifecycle-ring
receipt means `Unknown`; an uncertain lifecycle transaction must first recover.
Recovery never reexecutes the mutation. Durable unknown outcomes remain counted
after restart. Volatile loss counters cannot establish prior-session completeness,
so `previousSessionLossUnknown` is explicitly true after reopening.

Retention rejects new records when full. There is no hidden pruning, overwrite,
rotation or remote exporter. Operators must provision finite capacity; reducing
limits cannot discard existing history to make it fit.

| Resource | Default | Hard ceiling |
| --- | ---: | ---: |
| Retained records | 4,096 | 16,384 |
| Encoded record | 16 KiB | 16 KiB |
| Retained record bytes | 64 MiB | 256 MiB |
| Metadata allowance | 8 MiB | 32 MiB |
| Queued operations / bytes | 64 / 256 KiB | 256 / 1 MiB |
| Records per query page | 128 | 256 |
| Encoded page allowance | 256 KiB | 1 MiB |
| Retained query owners | 4 | 16 |
| Aggregate page allowance | 1 MiB | 4 MiB |
| Entries scanned per page | 1,024 | 4,096 |

These are independent limits with validated minimums and dependent metadata
bounds. A page reserves four times its requested encoded allowance for decoded
and response ownership, so aggregate bytes may reject it before owner count.
Critical terminal reservations cannot be consumed by diagnostic or query traffic.
Snapshots expose retained and reserved records/bytes, queued work, page owners,
pending attempts and fixed loss counters. `stage_bytes` is a conservative 68 KiB
reconciliation reservation while unhealthy, not a measurement of filesystem
allocation or process RSS.

## Query authorization and ownership

`AuditService.QueryPhase2Audit` returns typed records. Tenant queries require an
administrator bound to exactly the authenticated tenant. Node queries additionally
require the trusted `latent.node.operator` claim; it grants no cross-tenant query
access. The existing `QueryAudit` method provides a limited tenant projection;
unsupported resource-prefix filters are rejected.

Cursors bind the journal epoch, exact scope and filters, position and frozen high
watermark. They grant no authorization. Later appends are excluded from the same
pagination sequence. Filters select event kind, actor and an inclusive time range
over **durable acceptance timestamps**, not caller-supplied occurrence timestamps.
Scan work counts nonmatching entries too: a valid empty `ScanLimit` page can have
a continuation. Coverage reports retained floor, high watermark, scanned count,
stop reason, dropped observations, durable unknown outcomes and prior-session
loss uncertainty. Reaching the end does not prove complete observation coverage.

Queries have an absolute deadline checked before work, during scanning and after
the final read/decode, including empty pages. Count, byte, scan and transport
limits apply independently. An `AuditPage` owns its decoded allowance; conversion
transfers the cloneable `AuditResponseLease` through response-body consumption
and retained transport frames. Dropping the request future cannot refund bytes
still owned by a queued read or response. A page lease retains its compact budget,
not the journal root lock.

Shutdown first quiesces control producers, closes new audit admission and then
observes the same worker's completion within a finite deadline. Already started
attempts can still deliver their prepaid conclusion after close. A live attempt
keeps the worker and root owned until completion or abandonment. A timed-out join
retains ownership and prevents a clean shutdown report; dropping the handle does
not synchronously perform filesystem cleanup or pretend the thread stopped.

## Integrated producers and verification

`AuditedAdmissionAuthority` captures accepted/rejected explicit verification and
recovery, including publisher, provenance and SBOM checks performed by the
underlying authority. It captures only available checked identities and policy
identity. These are lossy diagnostics after the authority call, not separate
records for every cryptographic subcheck. Verification can finish and queue a
diagnostic **before publication response preflight**; such a record does not
claim publication began or committed.

The configured native-cache preparation path captures persistent hit, miss and
corruption decisions with identities from its sealed catalog input. Capture
cannot change loading or preparation success. Resident prepared hits and raw
cache operations retain their aggregate counters rather than creating an audit
record for every access. Managed release operations and existing deployment
apply/delete use the critical protocol above. No durable audit enqueue, disk I/O
or worker is added to Invoke or the final activation-start gate.

[Canary outcome observation](phase-2-canary-observation.md) separately collects
bounded, attributable activation outcomes. It does not emit one durable record
per invocation. The [rollout coordinator](phase-2-rollouts.md) uses exact retained
receipts for progression and startup reconciliation. [Canary promotion](phase-2-canary-promotion.md)
records its declared thresholds, selected/admitted-terminal and success/failure/slow
counts, fixed verdict and reason. Its typed identities retain the policy digest,
window epoch and evidence digest where available. Healthy evaluation alone never
emits a committed promotion result. Rollback integration remains ticket #155.

Focused tests exercise transaction cutpoints, missing acknowledged history,
private paths, full-record capacity, exact replay, post-commit sink failure,
scope/cursor/deadline behavior, response leases and shutdown with live attempts.
These tests and the canary tests are part of the implementation evidence; final
ticket completion and release readiness still depend on the required CI gates.
