# ADR-0025: Separate immediate capability operations from transactional effect intents

- Status: accepted
- Date: 2026-09-13
- Issue: #271
- Supersedes: the blanket external-effect requirement in ADR-0013

## Context

ADR-0013 established explicit state transactions and described external effects
as journaled intents. That remains the correct model when an application needs a
durable effect to commit atomically with application state, but Phase 3 also
introduces bounded capability providers such as outbound HTTP, immutable blob
storage and event publication. Requiring every ordinary provider call to create
a durable application effect intent would pull the Phase 4 transaction/outbox
system into Phase 3 and would blur the result of an immediate external call with
a later durable-dispatch receipt.

ADR-0014 already records the harder distributed-systems boundary: a remote
provider can perform an operation while its acknowledgement is lost, so LSF
cannot promise universal exactly-once external effects. Cancellation or local
deadline expiry cannot make that uncertainty disappear.

The provider contracts therefore need an explicit semantic mode before their ABI
and failure behavior are frozen.

## Decision

LSF has two distinct external-effect modes.

### Immediate capability operation

A Phase 3 provider call is an activation-scoped operation performed directly
through the capability broker after current authority, policy, budget and
resource ownership have been established. It is not an application transaction,
outbox entry or durable workflow step.

An immediate operation reports one of four semantic outcome classes where the
provider contract can distinguish them:

1. **Rejected before dispatch.** Authority, validation, admission or local
   resource checks reject the operation before it can reach the external system.
   LSF may state that this attempt was not dispatched.
2. **Provider acknowledgement.** The selected provider boundary acknowledges the
   operation according to that provider's documented protocol. The acknowledgement
   does not by itself prove downstream consumer processing, application state
   commit or end-to-end exactly-once execution.
3. **Known failure.** The provider protocol supplies enough evidence to classify
   the attempted operation as failed under its documented contract. LSF must not
   manufacture this classification from a local timeout or lost connection.
4. **Uncertain after possible dispatch.** Dispatch may have occurred but LSF
   cannot establish whether the external side effect completed. Cancellation,
   deadline expiry, disconnect, process interruption or a lost acknowledgement
   after possible dispatch belong here unless the provider has stronger evidence.

Provider implementations must preserve the distinction through their typed
results. Error strings or transport failures must not collapse an uncertain
mutation into a definite non-effect.

A local cancellation or deadline stops further work LSF still controls. It does
not roll back an operation already visible to the remote system. In particular,
LSF must not automatically replay an uncertain mutating operation merely because
an idempotency key exists. Any retry policy must be explicit, bounded, supported
by the provider contract and safe for the classified outcome.

Provider acceptance is separate from consumer processing, invocation status,
audit observation and future transactional effect receipts. For example, a
JetStream publish acknowledgement is a broker acknowledgement, not proof that a
consumer processed the event. A bounded multipart-upload cleanup/recovery journal
is provider-owned operational recovery state; it is not an application
transaction or durable outbox.

### Transactional durable effect intent

Phase 4 may create a durable effect intent as part of an explicit application
state transaction. State mutations and their effect intents commit together.
Only after that commit may a dispatcher own delivery/retry work under a defined
idempotency and retry policy. A commit receipt establishes durable local intent,
not remote completion.

ADR-0013 remains accepted for explicit transactional state and this Phase 4 mode;
ADR-0025 narrows only its blanket statement that all external effects are
journaled intents. ADR-0014 continues to apply to both modes: even a durable
intent plus stable idempotency identity does not create a universal exactly-once
external-effect guarantee.

## Contract and validation consequences

Phase 3 contract work in #202 must keep immediate provider results distinct from
future transactional effect-intent/commit receipts. Async ownership in #205 must
retain permits, buffers and cleanup ownership until actual provider work retires,
including when the caller has cancelled or timed out after possible dispatch.

The concrete provider tickets apply the same boundary:

- #211 must preserve outbound HTTP remote status/transport failure and uncertain
  mutating outcomes without implicit mutation replay.
- #214 may retain bounded upload-cleanup state for provider recovery, but that
  inventory cannot be presented as an application outbox or atomic state/effect
  transaction.
- #217 defines broker publication acknowledgement separately from consumer
  processing and must retain uncertain-after-send outcomes.

#205 and those provider tickets own focused deterministic cancellation/failure
coverage. #238 owns the integrated adversarial matrix that proves uncertainty,
cleanup and exact resource retirement across provider failures. #240 reviews that
mapped evidence before Phase 3 completion. This ADR introduces no second provider
implementation or Phase 4 persistence machinery.

## Phase 4 handoff

Phase 4 owns the application transaction/outbox design: durable effect-intent
records, atomic state/effect commit, dispatcher ownership, stable idempotency
identity, retry scheduling, reconciliation and receipt semantics. Those contracts
must continue to preserve uncertain external outcomes rather than interpreting a
local retry or committed intent as proof of remote exactly-once execution.

## Consequences

Phase 3 can deliver useful external capabilities without pretending that every
call is transactionally coupled to guest state. Applications that choose an
immediate operation must handle its documented acknowledgement and uncertainty
semantics directly.

Applications that require atomic state/effect intent creation must wait for the
Phase 4 transaction/outbox contract instead of inferring such guarantees from a
Phase 3 capability receipt, audit event or provider cleanup record.
