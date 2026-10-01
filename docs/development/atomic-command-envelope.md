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

Command/attempt `LCM` and terminal result `LCR` use closed binary format 2.
Both retain the original incarnation and namespace generation installed by
that terminal physical envelope. A later command, rollout or lookup cannot
substitute its current namespace version. The result digest includes this
original version, and startup checks exact command/result version linkage.
Pending records have no committed version; committed, rejected and technical
abort metadata retain their own original durable envelope version.

Historic `LCM`/`LCR` format 1 is explicitly unsupported because it did not retain
that original version. Readiness and inspection refuse these rows; this change
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

## Validation and remaining integration

The source milestone has 14 actual engine tests plus 24 transaction-model
schedules. The engine cases exercise reopened success/rejection, exact result and
effect links, duplicate claim/retry CAS, OCC/revocation, physical retirement,
quota pressure, full-row rejection, exact 1 MiB result with 128 intents, compatible
rollout, clock regression and malformed/orphan startup records. The combined
Linux storage/effect/commit targets passed 103/35/38 tests and strict Clippy.
Windows passed the 38 commit cases; these are distinct declared environments.

This library milestone does not complete the node activation path, RPC waiter
coalescing, interrupted-attempt recovery, complete process/fault campaign,
retention sweeping, provider delivery or six-language standalone qualification.
Those consumers must use the same physical owner and complete envelope. The
Phase 4 issues remain open until their full acceptance evidence is reconciled.
