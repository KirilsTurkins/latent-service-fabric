# ADR-0062: Host-own serializable transactions and durable outcomes

- Status: Accepted architectural contract; runtime enablement and storage qualification are separate gates
- Date: 2026-09-30
- Decision issue: [#380](https://github.com/KirilsTurkins/latent-service-fabric/issues/380)
- Implementation epic: [#379](https://github.com/KirilsTurkins/latent-service-fabric/issues/379)
- Collective acceptance: [#407](https://github.com/KirilsTurkins/latent-service-fabric/issues/407)
- Supersedes: guest-controlled begin/commit in the unsupported original state declaration and the incomplete transaction/outcome model described by ADR-0013
- Retains: [ADR-0014](0014-do-not-promise-universal-exactly-once-external-effects.md), [ADR-0025](0025-separate-immediate-capability-operations-from-transactional-effect-intents.md), [ADR-0028](0028-retain-activation-ownership-across-asynchronous-waits.md) and current stateless contracts

## Context and availability

Phase 3 gate #240 is complete. The six maintained guest SDKs (#544–#549), six
external clients and packaged developer workflow #559 are the implementation
foundation. They do not establish application transactions. Management persistence,
immediate provider acknowledgements and provider cleanup journals are different
boundaries. This ADR decides the Phase 4 contract before its engine and runtime
are enabled. The [executable model](../crates/latent-commit/src/model/mod.rs) is a
specification, not an embedded engine, authenticated host, physical cleanup test or
power-loss receipt. The [roadmap](../docs/roadmap.md#phase-4-state-and-effects)
maps every finite implementation and acceptance owner.

## Scope and isolation

Each admitted transactional activation has exactly one host-created transaction
under one authenticated tenant, one granted stable namespace and at most one
entity ownership scope. Bounded multi-key reads, prefix scans, puts and deletes
are supported inside that scope. Keys, package deduplication, publication identity,
entity IDs and guest-supplied strings grant no authority. There is no
cross-namespace, cross-service or distributed atomic transaction. The host derives
the sealed binding, incarnation, budgets, deadline and activation/transaction
generation; forged, foreign, stale and closed handles reject before an operation.

Use serializable optimistic concurrency with conservative namespace generation
tracking. Acquire one consistent engine view and its persisted namespace
incarnation/generation. Reads observe that view plus staged writes/deletes; absence
is an observation. Every eligible command, including blind writers and commands
that only read/stage intents, compares that generation under the physical writer
fence. Every accepted envelope advances it; unrelated namespace writes may therefore
conflict. Prefix pages remain in the acquired view, have finite count/byte ceilings,
and are invalidated by any intervening generation, including a phantom outside the
returned page. Do not call snapshot reads alone serializable.

Persist generations monotonically without reuse. Deletes/recreation cannot restore
an earlier stamp, even when values or absence compare equal; exhaustion refuses
work rather than wrapping. Namespace deletion/recreation and older-history restore
use a new incarnation. Ordinary restart preserves both history and incarnation.
Later finer read/range conflict tracking requires equivalent serializable evidence.
An OCC conflict returns a technical disposition; it never reruns a guest.

## Commands, caller authority and queries

A stable command key contains tenant, namespace, incarnation, host-derived recovery
scope, versioned application operation, optional entity and caller-retained key.
Default recovery scope is a stable authenticated caller. A shared service or
delegated recovery scope requires an explicit grant. Authentication credential,
session/CSRF rotation, route, deployment revision and activation correlation ID
are not command identity. The admitted execution still captures exact source,
revision, binding and policy for receipts/audit. Compatible route changes cannot
make the same command execute again; incompatible operation semantics require an
explicit contract/operation decision.

Fingerprint a versioned canonical encoding of the application body, selectors,
original stale-edit preconditions, processed-input identity when applicable and
every other semantically relevant application option. Keep presence, bytes and
full-width integers exact. Changed body or preconditions under a retained key
conflict. Transport security headers are not replayable application data by
default; current credentials/security response policy are applied at delivery.
The authoritative encoding and common vectors belong to #382.

Both initial application-result delivery and replay require current application
and result-read authorization. Tenant equality, possession of an ID and historical
permission are insufficient. Retain an approved host-visible result policy/class
that preserves any business visibility check made during execution. Full replay
must perform that current policy check; it must not bypass a check that only ran
inside the original guest. If that check cannot be evaluated safely outside the
guest, deny full replay or expose only an independently authorized bounded receipt.
Replay does not rerun business logic or restore historical authority.

Queries are a separate read-only mode with a bounded consistent view and current
read authority. They require no command key, durable business-command row, result
row or outbox write. Audit still applies. A fresh acquisition after an acknowledged
commit on one node/namespace incarnation observes at least that commit's generation,
including after ordinary restart. Existing pinned views can be older; unsupported
historical/cross-request cursors reject rather than silently changing views.
Older-history restore explicitly breaks continuity with a new incarnation and a
paused recovery state. An application's expected-version token rejects a stale
screen edit before execution and is distinct from the activation's OCC fence.
Neither SDKs nor recovery replace the original precondition silently.

## Host-owned eligibility and physical commitment

The guest stages operations; it never begins a second transaction or commits.
The contract direction is host-acquired, generation-checked transaction/query
resources. #382 owns exact WIT/RPC versions and six-compiler shape qualification:
`latent:state/key-value@0.2.0` and `latent:intents/staging@0.1.0`, with bounded
resource pages that pull one entry at a time. Structural recognition does not
enable unsupported runtime imports or grant operation authority.

The host owns these distinct stages:

| Stage | Required boundary |
| --- | --- |
| Admission/view | Authenticate, derive namespace/recovery scope, deduplicate/fingerprint, check original caller preconditions and reserve finite resources before guest work. |
| Staging | Bind all handles and owned bytes to one activation/transaction; retain read-your-writes and current narrow capability checks. |
| Guest outcome | Require a successful application outcome and validated typed output for business commit. Ordinary declared errors, traps, initialization failure, panic, exhaustion and pre-fence cancellation discard business state/intents. An explicitly classified terminal business rejection uses the metadata path below. |
| Required-work settlement | The installed language profile settles required accepted work/continuations under the original authority, budget and deadline. Root method/Promise/Task return alone is insufficient. |
| Seal/preflight | Close staging, sever every guest reference and own an immutable complete plan. Validate output, payload references, receipt/record counts, encoded storage costs, result policy and recovery capacity before commitment. |
| Final fence | Under the same bounded store writer/authority fence, recheck current authorization, incarnation, generation, processed-input identity, lifecycle and cancellation immediately before admission to irreversible storage I/O. |
| Physical commit | Publish one atomic envelope and confirm the engine's qualified durability profile. Retain actual I/O ownership and charges through confirmation/recovery. |
| Response/recovery | Deliver the committed or rejected application result only after its required durability and current result-read checks. Transport loss cannot undo durable disposition. |
| Cleanup | Positively retire resources or conservatively quarantine; report this separately from durable outcome and effect delivery. |

Cancellation that wins before the final fence prevents commitment. Once the writer
may have crossed the irreversible boundary, cancellation/timeout/disconnect
requests cleanup and outcome recovery; it cannot assert abort. Failure after a
known durable commit never changes it to aborted, even when delivery, audit or
cell cleanup fails. If persistence may have occurred but confirmation is missing,
report recovery-required/unknown with the original identity. Do not publish a
success from uncertain I/O or prove noncommit from a dropped waiter.

For a composed SDK runtime, no queued/runnable accepted continuation may mutate
the plan after seal. The selected profile defines required error-disposition rules
while draining; there is no invented universal child-error rule. Idle managed
executor capacity is not unfinished business work, and a sleeping/daemon flag is
not proof that work is harmless. Core Phase 4 need not implement the separate
SDK #736/#741–#746 ports; enabling any composition requires #388's focused
root-return/drain/error/cancellation/late-staging/late-wake evidence. This adds no
second executor, budget ledger, transaction owner or cleanup path.

## One atomic envelope and durable terminal outcomes

One physical engine transaction contains all of:

- Business state mutations and immutable payload references.
- Durable outbox intent records, independently approved dispatch policy and IDs.
- Command key, canonical fingerprint, attempt/transaction/source identity, bounded
  result or receipt-only disposition, recovery policy and linked retention metadata.
- Optional processed-input identity and terminal inbox disposition.

There is no production state-commit-then-effect-append path. Preflight the full
encoded plan and all limits, including rejection/recovery metadata and physically
reserved recovery resources. A bounded full-result replay promise is explicit and
finite; receipt-only recovery preserves disposition/identity without promising
expired application bytes. Full results and payload references require validated
immutable ownership before the envelope can commit.

An admitted terminal business rejection discards all business writes/intents but
atomically retains its approved bounded rejection result and applicable terminal
inbox disposition for the promised window. This is durable recovery metadata,
not business-state commitment. A duplicate recovers the original rejection after
business state changes; re-evaluation requires a deliberate new command. Do not
persist arbitrary malformed or unauthenticated input as admitted commands.

| Durable disposition | Meaning and permitted caller behavior |
| --- | --- |
| In progress | One admitted attempt has an owner. Inspect/cancel within current authority; do not execute a concurrent duplicate. |
| Committed | The complete business envelope is durably known. Recover the same receipt/result subject to current authority and retention. |
| Terminal business rejection | Recovery metadata/inbox are durably known; business writes/effects did not commit. Recover that rejection, without automatic re-evaluation. |
| Confirmed technical abort | Affirmative absence of committed business state/effects; explicit retry additionally requires physical-owner retirement and an attempt fence. |
| Recovery required | Possible commitment or unresolved storage ownership requires authoritative recovery. Do not execute again. |
| Unknown/expired | No usable retained conclusion; absence/expiry cannot prove noncommit. Keep the original identity and preconditions while investigating. |

Commands, attempts, transactions, activations and effects have separate identities.
An explicit retry after technical abort compares an `AbortFence` binding command,
original fingerprint/preconditions, aborted attempt/transaction and retired
physical-owner generation. Atomically advance the attempt generation once before
another guest runs. Competing retries have one winner; stale completions cannot
commit, reopen staging or overwrite receipts. Keep original attempt history.
No implicit SDK/runtime retry occurs on conflict, timeout or restart. A trusted
event-trigger retry is an attributable, configured finite caller action under the
same proof/fence rules. Changed identity, a new route or an expired lookup is not
abort proof; changed preconditions require a deliberate new command.

## Strict capabilities and six runtime profiles

Strict transactional execution denies immediate irreversible or unsupported
application/provider operations and unsupported synchronous child calls at
preparation and operation time. A standard HTTP/socket/database client does not
become an LSF transaction or durable intent. Read-only capabilities require an
explicitly reviewed semantic classification and authority; HTTP `GET` or an
application's purity claim is insufficient. Read observations from an external
provider are not part of this embedded namespace's serializable state snapshot.
State-coupled external work uses staged intents, never an immediate mutation.

Required language-runtime imports are separately classified, narrowly authorized
and charged. Monotonic/wall clocks, entropy, logging, GC support and host suspension
can be required even during initialization. They confer no application network,
filesystem, external-write or durable-scheduler authority. Entropy/time/logging
are not deterministic replay guarantees, and no automatic guest re-execution is
allowed. Host suspension retains resources under ADR-0028. Initializers run only
inside the admitted profile's authority and budget; failure is a technical abort.

| Maintained guest | Required qualification boundary |
| --- | --- |
| Rust | Fresh compiled component, declared error versus panic/trap, affine generated handles, cancellation/drop and actual host suspension. |
| C | Fresh reactor, explicit status/trap, bounded linear memory/stack, ownership/disposal and the profile's closed runtime imports; no assumed host thread runtime. |
| TypeScript | Maintained compiled JavaScript component profile, actual Promise/suspension/error and disposal rules; no assumed Node.js, DOM, ambient timers or process. |
| Go | Maintained TinyGo component/runtime profile, explicitly granted clocks/entropy including initialization, goroutine/GC/panic semantics and owned handles; a goroutine is not a persistent host worker. |
| Java | Maintained TeaVM component profile, granted runtime clocks, managed heap/GC reservation, exception/trap and actual import/value lifting, including HTTP signatures; no JVM process or assumed OS-thread behavior. |
| C#/.NET | Maintained NativeAOT component profile, granted GC monotonic clock, Task/exception/disposal and actual suspension/retirement; GC collection is not host cleanup and no CLR process is retained. |

#389 and Java slice #718 prove all six actual guest integrations. #401 separately
extends the six existing external clients. Compiler checks, client tests and a
Rust component do not substitute for another guest's real execution. The separate
SDK Libraries epic #677 and runtime/network research are not Phase 4 prerequisites.
Supported stateless worlds retain their existing immediate-operation semantics,
including ADR-0025 uncertainty and its prohibition on implicit mutation replay.

## Effects and incoming messages

Effects are deferred durable work. The host derives effect identity from the
command's admitted attempt/transaction and allocated sequence. Compatible route
changes do not regenerate committed effects. Guest staging selects only a granted
logical binding and bounded application payload; the host captures an approved
provider/operation, independent expiry, finite attempt/resource budgets and durable
dispatch authority. The caller's invocation deadline neither silently expires
nor indefinitely extends committed work. Current dispatch policy cannot broaden
the committed scope, and restored historical grants cannot authorize delivery.

Phase 4 dispatch is explicitly unordered, including within one entity. Sequence
allocates identity; it does not promise provider completion, per-entity group
ordering or global ordering. There is no ordering head-of-line queue to unblock.
Dead-letter/expiry/policy-blocked/uncertain outcomes remain explicit retained
dispositions; an administrative resolution is attributable and does not manufacture
provider acknowledgement. A stronger order profile needs a separate reviewed
group/sequence, head-of-line/dead-letter policy and executable evidence.

Commit means local durable intent, not remote completion. Provider acknowledgement
means the provider's stated boundary, not consumer processing or recipient
delivery. IDs and retry policy do not supply universal exactly-once effects.
Possible dispatch with lost acknowledgement remains uncertain. No awaited
workflow, compensation orchestration or durable application timer is introduced.
Dispatcher retry is finite internal maintenance, not a public scheduler.

Incoming deduplication identity is tenant/namespace/incarnation plus a granted
source binding and its canonical immutable message identity. Delivery counters,
activation IDs and broker sessions are not deduplication keys. The binding's finite
retention/terminal-rejection/retry policy is explicit; broker deduplication windows
do not imply permanent LSF deduplication. Atomically record processed input with
commit or durable terminal rejection, then acknowledge. Before either boundary,
no success acknowledgement is permitted. Technical-abort retry and acknowledgement
loss retain the same input/command identity and proof rules.

Pending outbox/inbox records retain durable bytes and bounded shared metadata,
not a guest Store/cell, process, language heap, per-entity worker/listener/timer or
application provider pool. Active-only entity lanes hand off to the same commit
owner; durable dispatch starts from retained records after actual guest cleanup.

## Retained formats, lifecycle and recovery capacity

Version application state schema independently from result, intent, inbox,
ordering, checkpoint and payload-reference record formats. Deployment compatibility
checks the entire retained format set, not just the new state's schema. Compatible
upgrades preserve pending work, source/publication associations and required
decoders; refusing an incompatible upgrade/retirement is preferable to silently
dropping, reinterpreting or reauthorizing work. Canary/code rollback does not
rewind durable state or external actions. Explicit migrations are bounded,
authorized, restart-safe and inspectable before route transition.

Retention is a linked graph: command identity/fingerprint, attempt/commit receipt,
unresolved effects, payload references, inbox protection and required schema,
binding/publication metadata must survive as long as a dependent obligation needs
them. Application result payload expiry need not mean command identity expiry.
Do not collect an unresolved effect's referenced bytes or deduplication protection
merely because the result expired. Identity expiry makes lookup unknown; it never
asserts that historical work did not commit. Finite promises and their remaining
recovery windows are exposed by inspection.

Deduplication/GC use qualified conservative elapsed-time continuity. Persist the
needed retention anchors; ordinary restart cannot refresh windows indefinitely or
erase them from an unqualified wall-clock jump. When time continuity is unknown,
retain protection and surface the condition until qualified/operator resolution.
Older-history restore starts command/effect/inbox dispatch paused, changes
incarnation and requires explicit reconciliation of work that may already have
escaped the restored image. Restoring a backup does not roll back external reality.

Declare and physically reserve finite operator recovery capacity: read-only
inspection/result receipts, pause/reconciliation, cleanup and GC must remain usable
under the promised business-storage/queue saturation. Reserve memory, storage,
writer/response slots and owned I/O where required; a nominal quota number is not
proof. Business admission rejects before exhausting this reserve. #397/#400 prove
that capacity on the actual engine/host; the model only exercises the specification.

## Threat and failure handoff

| Threat/failure | Required outcome and owner |
| --- | --- |
| Unsupported filesystem/device sync, torn data or unqualified power loss | #381 qualifies one embedded engine and exact durable profile; #383/#386 fail closed/recover whole envelopes. Model success is no storage proof. |
| Competing store process, root substitution or forged storage metadata | #383 owns protected roots, exclusive shared store ownership and format/integrity validation; no guest opens that root. |
| Cross-tenant/namespace or same-tenant other-user replay | #384/#387 derive sealed namespace/recovery/result authority; IDs and historical permission never authorize. |
| Missing-key/blind-write/ABA/scan phantom | #385 checks conservative namespace generation and incarnation at the writer fence, with no implicit rerun. |
| Trap, initializer failure, exhaustion, invalid output or late task | #388 discards/seals through the shared owner; #389/#718 prove each actual language profile. |
| Cancellation before fence versus irreversible I/O | #386/#388 preserve the winning fence, actual charges and committed/uncertain disposition separately from cleanup. |
| Commit response lost or result expired | #387/#400/#401/#409 recover original authorized receipt/result within linked finite retention; absence is no abort proof. |
| Lost rejection followed by changed business state | #386/#387 retain rejection/inbox, discard business writes/intents, and recover the original result. |
| Concurrent explicit retries or stale owner completion | #387/#394/#395 compare the durable abort/attempt/physical-owner fence; one retry winner. |
| Immediate provider/standard library mutation attempted | #388 enforces reviewed narrow runtime/import policy at preparation and use; #390 stages approved durable intents. |
| Provider send succeeded but acknowledgement was lost | #391–#393 retain uncertainty and approved finite retry/reconciliation; no universal exactly-once or consumer-delivery claim. |
| Incoming redelivery or acknowledgement loss | #395 preserves atomic processed-input identity and post-disposition acknowledgement under finite retention. |
| Compatible schema upgrade with old pending intent/result | #398/#405 preserve independent decoders and publication metadata or safely refuse the transition. |
| Code rollback or older-history restore | #398/#399 do not rewind external work; restore changes incarnation, drops historical grants and begins paused for reconciliation. |
| Wall-clock jump/restart/GC under saturation | #397 preserves conservative time/linked protection and real recovery reserves; #400 exposes attributable resolution. |
| Future cluster failover/reused owner | Phase 5 must extend namespace incarnation, leader/owner fences and commit authority with replicated authoritative evidence; this single-node contract grants no multi-node atomicity. |

## Implementation map and executable schedules

| Phase 4 owner | Required handoff |
| --- | --- |
| #380 / this ADR | Host-owned isolation/outcome decision and finite executable schedules. |
| #381/#382 | Qualified embedded-engine profile; exact WIT/RPC/host contracts, six-compiler feasibility and separate guest/client boundary vectors. |
| #383/#384/#385 | Shared protected store owner; namespaces/sealed lifecycle authority; bounded serializable OCC/scans. |
| #386/#387/#388 | Atomic state/outbox/outcome/inbox envelope; recovery/deduplication/explicit retries; shared runtime, accepted-work settlement, seal and physical cancellation/cleanup. |
| #408/#409 | Independent bounded fresh queries/stale-edit preconditions; shared application HTTP command/query/recovery and current result-read authorization. |
| #389/#718 | All six guest SDKs/templates/components and actual common semantics; #718 is Java's focused slice, not a seventh SDK. |
| #390/#391/#392/#393 | Durable dispatch authority/lifetime; bounded dispatcher claim/retry/uncertainty; real JetStream and qualified idempotent HTTP. |
| #394/#395 | Active-only entity lanes; transactional incoming messages and post-disposition acknowledgement. |
| #396/#397/#398/#399/#400 | Immutable payload references; linked quotas/retention/GC/recovery reserve; schema/retained-format deployment/migration/rollback; consistent guarded backup/restore; scoped CLI/management/audit/recovery. |
| #401/#402 | Six existing external transports separately from guests; one maintained stateful/browser application with six-language examples over shared query/HTTP paths. |
| #403/#404/#405/#406 | Source-bound adversarial/crash evidence and distinct language maps; stateful density/latency/backlog/recovery measurements; native/developer distribution and compatible persistent-state upgrades; versioned six-guest/six-client guides and actual Pages publication. |
| #407 / epic #379 | Reconcile every required implementation/language/operation/evidence/guide criterion; final public release remains separately authorized. |

Implementation waves express dependencies, not mandatory serialization. Focused
ports and evidence can land incrementally without waiting for #403/#407 or all SDK
ports. The early public vertical slice is namespace setup → command → lost response
→ original-result recovery → effect inspection, followed by queries/HTTP/inbox and
all six guest/client schedules. One real capsule must commit state plus JetStream
intent, restart before send, recover the same result and reject duplicate execution.
This early proof does not replace the rest of the map. Clustering belongs to Phase 5;
durable cross-invocation schedules/continuations/compensation belong to Phase 6.

Run the [reference schedules](../crates/latent-commit/src/model/tests.rs) with:

```bash
cargo test -p latent-commit --lib --locked
```

The suite inventory registers every model case for CI. Schedules cover scope,
consistent/read-your-write/missing observations, blind-write/ABA/phantom conflicts,
all commit/cancel fence orders, lost commit/rejection responses, changed-body
duplicates, forbidden immediate effects, output/trap/exhaustion, required-work
settlement and late staging, same-tenant other-user/current-policy denial, stable
caller/shared grants, retired-owner CAS retries, unknown/uncertain/quarantine,
restart/stale completions, fresh queries/stale edits, older-history restore,
atomic inbox/acknowledgement, retained intent decoders, unresolved effects after
result expiry, conservative clock discontinuity and recovery under saturation.
Their in-memory snapshot replacement, injected host permissions, explicit cleanup
observations and qualified-time inputs are model assumptions. Real engine crash,
power-loss, physical-resource, authorization, six-guest/client and browser proof
remain with the implementation/acceptance owners above.

Historical ADRs, release bytes and evidence keep their original source identities.
This explicit supersession updates active design; it does not rewrite old receipts,
resurrect obsolete alpha APIs or reopen the completed Phase 3 gate.
