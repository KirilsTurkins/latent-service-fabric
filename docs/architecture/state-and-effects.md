# State and effect architecture

[ADR-0062](../../adr/0062-host-own-serializable-transactions-and-durable-outcomes.md)
defines host-owned serializable commands, durable outcomes and independent bounded
queries. Its [executable reference model](../../crates/latent-commit/src/model/mod.rs)
and schedules establish decision consistency, not storage/power-loss, authenticated
runtime or physical cleanup proof. Runtime enablement belongs to the implementation
owners below. Current supported activations retain the stateless capability profile;
management receipts/audit/provider cleanup are operational records, not application
state transactions. See the [activation lifecycle](../activation-lifecycle.md).

Phase 3 gate #240, all six guest SDKs (#544–#549) and the packaged developer workflow
#559 are completed foundations. The [Phase 4 roadmap](../roadmap.md#phase-4-state-and-effects)
contains the complete epic #379 / gate #407 map. Guest SDKs and external clients
are separate six-language obligations; one matrix cannot substitute for the other.

## Execution modes and scope

| Mode | State and authority |
| --- | --- |
| Stateless | Consume input and return output under current capability grants. No application state transaction or durable command row is created. |
| Transactional command | One host-created transaction, one authenticated tenant/granted namespace and at most one entity scope. Bounded multi-key operations and intents stage under sealed handles; only the host submits the immutable commit plan. |
| Read-only query | Acquire a bounded consistent fresh view under current read authority, without a mandatory durable business-command/result/outbox row. Audit remains. |
| Entity command | The same transaction path with an active-only ownership lane. Lane state exists while work is queued/active, then disappears; it is not a persistent actor or outbox dispatcher. |
| Durable workflow | Phase 6 explicit continuation/state-machine work. An invocation-local wait or dispatcher retry does not provide it. |

Namespace identity is independent of executable/package/publication deduplication.
No key, entity ID, historical receipt or same-tenant identity grants namespace or
result authority. Cross-namespace/service and distributed atomic transactions are
unsupported. Guest handles carry activation/transaction generation, namespace
incarnation, current authority and finite budgets; stale/foreign/closed handles reject.

## Serializable completion and fresh queries

Commands acquire one consistent engine snapshot and persisted namespace
incarnation/generation, then read their own staged writes/deletes. Missing-key
observations, blind writes, deletes/recreation and bounded prefix scans all
participate in conservative namespace generation validation. The final writer
fence compares the acquired generation; every accepted envelope advances it.
This deliberately permits unrelated writes to conflict while preventing ABA and
scan phantoms, including beyond a returned page. Snapshot consistency alone is
not serializability. Generations never wrap/reuse, and conflicts never rerun guests.

A fresh query acquired after an acknowledged commit on the same node/incarnation
observes at least that generation, including after ordinary restart. Pinned views
can be older; unsupported historical/cross-request cursors fail explicitly.
Older-history restore changes incarnation and starts recovery paused, breaking
the old read-after-acknowledgement continuity. Application stale-edit preconditions
use opaque incarnation-aware versions and are distinct from activation OCC.
Clients and recovery never silently refresh the original expected version.

## Host-owned transaction lifecycle

```text
authenticate/admit stable command and acquire one view
  -> execute/initialize within narrow authority and finite budgets
  -> settle required accepted logical work and validate output
  -> preflight all record/result/payload limits and seal staging
  -> final current authorization/cancellation/OCC/inbox fence
  -> one physical durable state + outbox + command outcome + inbox envelope
  -> current-authorized response publication / original-result recovery
  -> separately report physical cleanup or quarantine
```

Only an eligible successful guest outcome commits business writes/effects.
Ordinary declared errors, traps, initialization failure, panic, exhaustion and
pre-fence cancellation discard them. An explicit terminal business rejection
uses a durable metadata-only path: retain its bounded approved rejection/result
and applicable terminal inbox disposition, while discarding all business
mutations/intents. That rejection remains replayable after later state changes;
re-evaluation requires a deliberate new command. Malformed/unauthenticated input
does not become a retained admitted command.

For an installed logical-runtime profile, root method/Promise/Task return alone
is insufficient. Required accepted work/continuations settle under the original
authority, budget, deadline and language-specific error rules before staging
closes. The owned plan has no mutable guest references; late staging/wakeups cannot
change it. #388 proves any newly advertised composition. Separate SDK runtime
ports #736/#741–#746 are not prerequisites of core Phase 4.

Cancellation winning before the final fence prevents commitment. Once irreversible
I/O may have started, timeout/disconnect/dropped waiters are not abort proof. Keep
actual owners and resource charges until completion or authoritative recovery.
Known durable commitment remains committed despite response/audit/cleanup failure.
Possible commitment without confirmation is recovery-required/unknown, with the
original identity. Cleanup/quarantine, durable disposition and effect delivery
are independently observable.

## Stable command recovery and explicit attempts

Command identity consists of tenant, namespace/incarnation, host-derived recovery
scope, versioned operation, optional entity and caller-retained key. The default
scope is a stable authenticated caller; shared/service/delegated scopes need
explicit grants. Route/revision, activation and session/security credentials are
separate identities. Capture exact execution/source pins in receipts/audit, without
allowing compatible route changes to regenerate a command or its effects.

Versioned canonical fingerprints include application body, selectors and original
expected-version/processed-input data. Changed bytes or preconditions under a
retained key conflict. Initial result delivery and replay require current
application/result-read authority, including the approved policy for any original
business visibility check. An ID, historical permission or tenant equality is
insufficient. Replay cannot bypass a check performed only inside the original
guest; deny full replay or use an independently authorized receipt when the check
cannot safely be evaluated outside it. HTTP security headers are regenerated under
current policy rather than treated as historical application output.

In-progress attempts exclude concurrent duplicate execution. Recover committed
or rejected outcomes from the original bounded result/receipt. Unknown/expired
lookup is not proof of noncommit. A deliberate technical-abort retry requires
affirmative zero-business-state/effect commitment and retired physical owners,
then atomically compares a command/fingerprint/aborted-attempt/owner `AbortFence`
and advances the attempt once. Concurrent retries have one winner; stale
completions cannot overwrite receipts or reopen staging. No SDK/runtime replay
occurs on conflict, timeout or restart. Trusted incoming retries are configured
finite caller actions under the same proof; changed preconditions need a deliberate
new command rather than silent replacement.

## Immediate calls and deferred durable intents

Current stateless [HTTP](../runtime/outbound-http.md), [S3 blob](../runtime/s3-blobs.md)
and [NATS event](../runtime/nats-events.md) providers perform immediate capability
operations. They retain [ADR-0025](../../adr/0025-separate-immediate-capability-operations-from-transactional-effect-intents.md)
outcome classes: rejection before dispatch, protocol-specific provider acknowledgement,
known provider failure and uncertainty after possible dispatch. Acknowledgement
does not prove consumer processing, recipient delivery, application commitment or
universal exactly-once execution. Local cancellation/lost acknowledgement cannot
roll back remote work or justify automatic uncertain mutation replay.

Strict transactional execution denies immediate irreversible/unsupported
application operations and unsupported synchronous child calls at preparation and
operation time. Read-only provider use needs reviewed semantic classification;
an HTTP method or application purity claim is insufficient. External observations
do not become the embedded state's serializable read set. Standard sockets or
database clients do not become LSF transactions/intents.

Runtime clocks, entropy, logging, GC and suspension have separate explicit narrow
authority and accounting, including initialization. They do not authorize
application mutations or persistent work. The six profiles are maintained compiled
Rust, C, TypeScript, Go/TinyGo, Java/TeaVM and C#/.NET NativeAOT components, with
their own exception/panic/Promise/goroutine/Task/owned-handle semantics. Do not infer
JVM/CLR/Node or OS-thread behavior. Host suspension retains actual activation
ownership under [ADR-0028](../../adr/0028-retain-activation-ownership-across-asynchronous-waits.md).
Time/entropy support does not make nondeterministic observations replay-safe.

Deferred intents commit in the same physical envelope as business state,
command outcome/fingerprint/result and optional processed-input identity. There is
no production state-commit-then-effect-append path. Guest staging chooses a granted
logical binding and bounded payload; the host captures independent approved
dispatch authority, expiry and finite attempt/resource budgets. Invocation
deadline expiry does not silently expire committed work or extend its limits.

Phase 4 effects are explicitly unordered, including within an entity. The
transaction/sequence allocates effect identity, not provider completion order or
a global/per-entity head-of-line guarantee. Dead-letter/expiry/policy-blocked and
uncertain dispositions stay explicit. A future stronger ordering profile needs
reviewed group/sequence, head-of-line/dead-letter rules and its own proof.

Durable intent means local commitment, not remote completion. Real JetStream
and qualified HTTP adapters retain acknowledgement/uncertainty/reconciliation
boundaries from [ADR-0014](../../adr/0014-do-not-promise-universal-exactly-once-external-effects.md).
Internal dispatcher retry is bounded maintenance; awaited workflows, compensation
orchestration and durable application timers remain Phase 6.

## Incoming identity, formats and linked retention

Incoming identity binds tenant/namespace/incarnation, granted source binding and
canonical immutable message identity, under an explicit finite deduplication
window. Broker session/delivery counters/activation IDs are not identity. Commit
or durable terminal rejection atomically persists the terminal inbox disposition;
acknowledge only afterward. Redelivery/lost acknowledgement and explicit
technical-abort retries preserve the original identities and policy. Broker
deduplication windows do not create permanent LSF deduplication.

Version state schema independently of result, intent, inbox, ordering, checkpoint
and payload-reference formats. Retain required decoders, source/publication/schema
associations and pending work across compatible upgrade/retirement, or refuse
the transition. Canary/code rollback does not rewind durable state or external
actions. [Versioning/deployment](versioning-and-deployment.md#phase-4-retained-state-and-outcome-compatibility)
records the migration/backup/restore handoff.

Retention links command/fingerprint/attempt/commit identity, unresolved effects,
payloads, inbox protection and required schema/binding/publication metadata.
Application result bytes can expire while receipt-only recovery and deduplication
identity remain. Unresolved dependent work prevents unsafe GC. Unknown/expired
identity is no abort proof. Qualified conservative elapsed-time anchors survive
ordinary restart; unqualified clock jumps cannot erase protection. Older-history
restore changes incarnation, discards historical grants and starts command/effect/
inbox processing paused for explicit reconciliation.

Reserve physically usable finite operator inspection/recovery/cleanup capacity
under declared business storage/queue saturation; refuse admission before that
reserve is exhausted. Pending work retains bounded durable bytes/shared metadata,
not a guest Store/cell, process, heap, per-entity worker/listener/timer or
application provider pool. Dropped waiters never refund live physical I/O.

The [implemented response-retention and recovery-reserve profile](transaction-retention.md)
uses the same physical store, preserves linked protective identities and records
bounded generation-safe maintenance progress. Its focused engine evidence is
separate from public node/Java/HTTP qualification.

## Implementation and evidence owners

| Required work | Owners |
| --- | --- |
| Decision/model and engine/contracts | #380/#381/#382: this ADR/model, one qualified embedded store, exact WIT/RPC and six-compiler/boundary vectors. |
| Shared state and command lifecycle | #383/#384/#385/#386/#387/#388: protected owner, sealed namespace authority, bounded serializable OCC, physical atomic envelope, recovery/rejection/attempt fences and shared activation/cleanup. |
| Independent query and shared HTTP | #408/#409: fresh views/stale edits and reusable application command/query/authorized result recovery. |
| Six guest integrations | #389/#718: Rust, C, TypeScript, Go, Java and C#/.NET actual components/templates; #718 is the Java slice. |
| External work and entities | #390/#391/#392/#393/#394/#395: authority/independent lifetime, bounded dispatcher/claims/uncertainty, real JetStream/qualified HTTP, active entity lanes and transactional inbox/acknowledgement. |
| Durable lifecycle and operations | #396/#397/#398/#399/#400: immutable payloads, linked quotas/retention/GC/recovery reserve, schema/format migration/rollback, backup/paused restore and scoped CLI/management/audit. |
| Clients and application | #401/#402: six existing external transports separately from guests, and one maintained stateful/browser product over shared query/HTTP with six-language examples. |
| Integrated acceptance | #403/#404/#405/#406/#407: crash/adversarial and separate language maps, measurements, native/developer distribution/upgrades, versioned published guides and complete collective decision for epic #379. |

The [ADR threat/failure table](../../adr/0062-host-own-serializable-transactions-and-durable-outcomes.md#threat-and-failure-handoff)
assigns storage, authority, cancellation, retry, restore, migration, clock and future
cluster fences. Each child owns focused positive/negative/physical-cleanup proof;
#403 aggregates it without becoming an implementation prerequisite. The first
public recovery slice lands incrementally through #400/#401, without replacing
the all-six guest/client, provider, operations, browser and guide gates.

Model schedules do not authorize production storage, unsupported platforms,
clustering or a release. Phase 5 owns replication/failover; Phase 6 owns durable
cross-invocation workflows/continuations/compensation. The separate SDK Libraries
milestone is not a completion prerequisite. Historical evidence/ADRs retain their
original identities, supported stateless APIs stay valid, and final public release
requires separate authorization.
