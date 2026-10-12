# Atomic command envelope

`latent-commit::atomic` owns bounded command admission, disposition, result
recovery and explicit proven-abort retries in the shared embedded engine. Its
operations borrow the native view/store on the protected owner's fixed workers.
It creates no executor, provider worker, native view owner or guest runtime.

The [transaction model](../protocol/transactions.md),
[namespace authority](namespace-authority.md),
[optimistic state sessions](optimistic-state-sessions.md) and
[durable dispatch storage](durable-dispatch-storage.md) provide the associated
authority, observation and effect contracts.

## Admission and identity

The canonical command key contains tenant, stable namespace/incarnation,
host-derived caller recovery scope, operation, optional entity and client key.
The fingerprint includes the canonical business input (bytes, media type and
metadata), original key preconditions and any selected input identity. Route,
credentials, activation ID and mutable delivery budgets do not identify a new
business command. Scope frames and distinct SHA-256 domains prevent ambiguous
concatenations. Digests are descriptive identifiers, never grants.

`PreparedAdmission` reads one view, validates the active namespace/schema and
prepares one CAS batch containing the command, immutable attempt identity,
pending result placeholder, accounting, namespace generation/pin and logical
capacity reservation. `publish` applies that complete plan before a guest may
be scheduled. An existing identical command returns its original source and
disposition; a changed fingerprint conflicts. No duplicate admission creates a
second executor claim.

The first accepted publication, revision, release/component/contract digests,
state schema and input/result formats remain immutable across compatible
deployment changes and explicit retries. Current authorization is checked
before lookup and again before returning a captured result-read policy.

## One disposition boundary

`CompleteEnvelope::success` consumes the affine claim, optional state plan,
bounded intent values and validated result. Its one physical batch installs
state observations/mutations, command/attempt disposition, exact result or
explicit receipt, immutable effect authority/payload/due rows, selected inbox
marker, namespace pins and retained accounting. State-only and intent-only
commands use this same boundary. There is no guest commit operation.

`rejection` records an admitted terminal business rejection and approved inbox
marker, with no application writes or intents. `technical_abort` requires the
private retired-attempt proof and creates no inbox acknowledgement. Admission
reserves both result bytes and a physical result row. The reservation's released
row provides room for a terminal input marker even when unrelated admissions
have filled the physical row limit.

The node supplies the current policy/namespace/effect/cancellation acceptance
fence to `publish`. The engine checks OCC and physical capacity before invoking
that short fence; it performs no flush while policy/effect locks are held. A
confirmed commit remains confirmed after a reply, audit or cleanup failure.
An uncertain engine return is recovery-required and cannot authorize a retry.

## Physical retirement and explicit retry

`PhysicalAttemptWork` guards move into actual executor, I/O or cleanup work.
They retire only after that physical work completes. Dropping an unretired
guard quarantines the attempt and retains its owner count. A timeout, cancelled
waiter, result expiry or missing lookup is not a nonexecution proof.

`AttemptRetirement::proven_noncommit` requires every physical owner to have
retired, an open acceptance phase and no quarantine. Only that private proof can
prepare a durable technical abort. A linked, attributable `RetryRequest` then
CASes the current aborted generation to one new pending attempt and preserves
all previous attempt/result rows. Concurrent requests have one writer; repeating
the same request returns the linked attempt. A stale completion cannot replace
the new attempt. There is no automatic guest retry.

## Retention and startup

Full replay retains the exact bounded Value. Receipt-only replay has an explicit
absent body and the original result digest. Result-body expiry and protective
identity expiry are separate. Existing linked identities are conservatively
retained until the maintenance owner can prove safe reclamation. Current read
permission and proven nonregressing clock continuity are required for inspection.

Command/attempt `LCM` and terminal result `LCR` use closed binary format 3.
Both retain the original incarnation and namespace generation installed by
that terminal physical envelope. A later command, rollout or lookup cannot
substitute its current namespace version. The result digest includes this
original version and the original opaque view token, and startup checks exact
command/result version and token linkage. The token includes the scope digest
and original schema/recovery epochs captured from the same state plan. No-state
rejection/abort envelopes capture and CAS the exact same history row. Initial
typed receipts and replay encode that original opaque token as canonical padded
base64; they never reconstruct it from the latest namespace history.
Pending records have no committed version; committed, rejected and technical
abort metadata retain their own original durable envelope version.

Historic `LCM`/`LCR` formats 1 and 2 are explicitly unsupported because neither
retained the complete original epoch-qualified token. Readiness and inspection
refuse these rows; this change
provides no backward reader, migration or version reconstruction. Operators must
retain the previous codec/profile and its protected data until an approved
migration or new store/incarnation is installed. Removing that codec cannot be
claimed as compatible retained-work recovery.

Pending result `LCP`, input `LIC`, usage `LCU` and retry `LCT` remain format 1.
Lengths, counts, discriminants, key identities, body digests and trailing bytes
are checked before acceptance. `validate_view` scans all ten families in coherent
pages of at most 128 rows/2 MiB and performs bounded point checks for every
command/attempt/result/input/reservation/effect/payload link. Foreign namespace,
state and dispatcher formats require their explicit installed codec callback;
unknown formats fail readiness without resetting data. Startup validation does
not mint execution authority or infer physical retirement from a decoded row.

## Persistence and recovery acceptance

[Issue #386](https://github.com/KirilsTurkins/latent-service-fabric/issues/386)
owns this persistence library and its focused failure schedules. The engine
fixtures in [atomic tests](../../crates/latent-commit/src/atomic/tests.rs),
[captured authority tests](../../crates/latent-commit/src/atomic/tests/captured.rs)
and [original view-token tests](../../crates/latent-commit/src/atomic/tests/view_tokens.rs)
exercise actual redb transactions and reopened records. The 24 transaction-model
cases separately check the shared semantics.

| Issue acceptance | Implementation and focused evidence |
| --- | --- |
| Complete host-validated command envelope | `PreparedAdmission` and `CompleteEnvelope` retain original command/fingerprint/attempt, publication/schema/formats, observations, intents, inbox, exact result policy and accounting; reopened success and captured-authority cases check their links. |
| Authority, OCC and quota at one durable writer boundary | `EmbeddedStore::apply_fenced` checks the complete batch and consumes final acceptance before one Immediate-durability commit; OCC/revocation, captured narrowing and full-capacity rejection cases leave business families untouched. |
| Stable identities and duplicate/conflicting attempts | Concurrent claims and explicit retry CAS have one winner; retained command, attempt, disposition and effect links survive reopening. Changed fingerprints and stale attempt completion reject. |
| Bounded success, error, receipt and record preflight | Oversized output/intent/quota cases reject; exact 1 MiB result plus 128 intents commits; receipt-only replay is explicit and malformed record lengths reject. |
| Known noncommit, confirmed commit and uncertainty | Writer-fence refusal returns the original pending owner; confirmed flush recovers the original result after process loss; backend storage-full returns recovery-required, preserving the original pending identity rather than authorizing replay. |
| Retain actual I/O, views, buffers and reservations | Private physical-retirement/quarantine cases reject premature abort/retry; the shared state owner tests retain accepted writes, read views and result buffers until native retirement and reserve finite recovery capacity. |
| Persistence-boundary and I/O schedules | Owned process cuts cover admission, success, state-only, intent-only, rejection, abort and explicit retry before acceptance and after confirmed flush. Backend storage-full and Linux kernel file-size failure reopen without partial state/outbox/inbox/result success. |
| Durable terminal rejection without business effects | Lost business rejection reopens after changed inventory; process cuts retain only approved rejection/inbox/result metadata and discard business mutations and intents. |
| Original rejection identity, read policy and reserved capacity | Exact source/result policy and bytes survive restart; full-row terminal rejection consumes its admission reservation, and original namespace/view-token receipts survive later commits. |
| Generation-checked proven-abort retry | Native retirement is required before durable abort; two explicit retries have one CAS winner, prior attempt rows remain and stale completion cannot commit the replacement attempt. |
| Linked formats and identity outlive result-body expiry | Expiry cases retain protected command/effect linkage; startup validates cross-family records and refuses unsupported formats, forged identities and orphan results. |
| Rejection/retry crash and linked-history refinement | The seven process schedules cover rejection persistence and explicit retry admission; lost rejection, concurrent retries, physical quarantine, retained view-token and unresolved-effect expiry cases check the refined outcomes. |

[Process schedules](../../crates/latent-commit/src/atomic/tests/process.rs)
positively observe the original child at the final writer fence or after a
confirmed flush, terminate and reap it, then reopen the same engine. There are
14 cuts across the seven dispositions. Child entry points invoked without the
owned protocol provide no durability evidence.

[I/O schedules](../../crates/latent-commit/src/atomic/tests/io_faults.rs)
exercise the production bounded backend's storage-full error at its 2 MiB file
ceiling and Linux `RLIMIT_FSIZE`/`SIGXFSZ` on the original descriptor. Logical
preflight passes before these failures. The backend case verifies an unchanged
pending record, no partial business families and no new executor admission.
These are bounded backend/kernel failures, not device ENOSPC or power-loss
qualification. Shared state tests separately inject an actual backend sync
failure and require original-identity recovery after uncertain persistence.

The 8 October 2026 PR #787 reconciliation passed all 54 commit, 143 state and
128 effects library cases on Linux x86-64 with pinned Rust 1.97.1. Test storage
used an ext4 Docker volume; the protected owner intentionally rejects the
container's overlay filesystem. Ordinary Clippy, formatting and repository/CI
contract checks are separate checks. Run the focused library selection with:

```sh
cargo test -p latent-commit -p latent-state -p latent-effects --lib --all-features --locked -- --test-threads=1
```

Node activation, RPC waiter coalescing, retention sweeping, provider delivery,
signed guest/client workflows and installed package qualification retain their
own Phase 4 tickets. They consume this same physical owner and complete envelope;
this persistence acceptance does not close those tickets or gate #407.
