# Engineering roadmap

The latest published runtime and developer toolkit is **0.1.0-alpha.5**.
Development contains newer merged source and explicitly selected profiles. Use
[Changes since alpha.5](start/development-changes.md) to find their application
workflows and [the post-release audit](development/documentation-audit-2026-10-14.md)
for the source-bound inventory. A merged implementation slice does not complete
its collective acceptance gate or publish a new distribution.

## Completed foundations

| Phase | Delivered boundary | Acceptance record |
| --- | --- | --- |
| Phase 0: executable spike | Fixed cells, real echo execution, containment and single-host measurements | [Feasibility gate](phase-0-completion.md) |
| Phase 1: single-node stateless fabric | Durable publication/deployment, bounded routing, admission, scheduling, invocation, CLI and six client contracts | [Functional completion](phase-1-completion.md) and [performance extension](phase-1-extension-completion.md) |
| Phase 2: packaging and supply chain | Exact packages, OCI transfer, publisher/build trust, admission, isolated AOT, audit and controlled rollout/recovery | [Package delivery gate](phase-2-completion.md) |
| Phase 3: capabilities and application hosting | Declared standalone providers, HTTP/static/Angular delivery, six guest SDKs, packaged developer workflow and learning site | [Integration gate](phase-3-gate-review.md) |
| First integration feedback | Static/publication/container workflows, qualified developer selection and alpha.5 distribution | [Published alpha.5 evidence](development/native-release-gate.md#published-alpha5-evidence) |

These reports retain their original sources, measurements and limitations.
They do not establish production sizing, a universal latency SLO, arbitrary
library compatibility or acceptance for later source changes. Current
installation and operator instructions live in the task guides; reproduction
of an old result requires its recorded revision.

## Phase 3: capabilities and application hosting

The accepted standalone profiles are the published baseline. Later dependency,
activation-runtime and transaction work uses separate selected profiles and
acceptance owners; it does not broaden the original completion decision.

## SDK libraries and activation runtimes

[Epic #677](https://github.com/KirilsTurkins/latent-service-fabric/issues/677)
tracks ordinary application-library and runtime integration. Merged source now
captures closed dependency graphs, immutable resources, approved generators,
server declarations, final compatibility reports and authenticated build/watch
inputs. Start with [application libraries](how-to/add-application-libraries.md)
and [composition inspection](how-to/inspect-a-composition.md).

Selected Rust standard-clock, TypeScript Promise/clock/service/npm, Java server
revision/processor and .NET resource/wall-clock fixtures have executed evidence.
Each profile retains its narrower acceptance boundary in
[engineering records](development/engineering-records.md). Full standard
thread/executor/reactor behavior, ordinary HTTP clients, private/update/watch
lifecycle, broader exhaustion/cancellation and clean installed distributions
remain owned by their language tickets. No general runtime is inferred from a
captured package or one successful fixture. Outbound research remains separate
from enabled, explicitly authorized provider profiles.

## Phase 4: state and effects

**Status: implementation in progress; collective acceptance and a new public
release remain outstanding.**
[Epic #379](https://github.com/KirilsTurkins/latent-service-fabric/issues/379)
and [gate #407](https://github.com/KirilsTurkins/latent-service-fabric/issues/407)
own the complete state/effect delivery. The
[host-owned transaction decision](../adr/0062-host-own-serializable-transactions-and-durable-outcomes.md)
and [state/effect architecture](architecture/state-and-effects.md) define one
namespace transaction, conservative serializable conflict checks, atomic
state/outbox/result/inbox persistence and independent fresh queries.

| Merged implementation area | Maintained guide or contract |
| --- | --- |
| Protected embedded storage, namespace authority and bounded command/query sessions | [Shared store](development/shared-state-store-owner.md), [namespace authority](development/namespace-authority.md), [state sessions](development/optimistic-state-sessions.md) |
| Atomic command envelopes, completion and duplicate delivery | [Atomic envelope](development/atomic-command-envelope.md), [host runtime](development/phase4-runtime.md), [delivery notifications](development/command-delivery-notifications.md) |
| Durable claims, transitions and separately authorized deferred providers | [Dispatch storage](development/durable-dispatch-storage.md), [deferred HTTP installation](development/deferred-http-installation.md), [JetStream](development/deferred-jetstream.md) |
| Current caller-scoped management, installed RPCs and shared HTTP routes | [Installed RPCs](development/installed-transaction-rpc.md), [HTTP boundary](development/transaction-http-v1.md), [transaction recovery](operations/transaction-recovery.md) |
| Guest templates, six external transaction facades and reference application | [Transactional guest](component-development/transactional-authoring.md), [transaction clients](development/transaction-clients.md), [order drafts](../examples/stateful-reference/README.md) |
| Linked retention, command-floor retirement, checkpoint/restore and format custody | [Linked retention](architecture/state-and-effects.md#incoming-identity-formats-and-linked-retention), [retirement reconciliation](https://github.com/KirilsTurkins/latent-service-fabric/blob/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/development/phase4-handoffs/2026-10-12/pr974-reconciliation.md), [checkpoints](development/transaction-checkpoint.md) |

The pending [PR #970](https://github.com/KirilsTurkins/latent-service-fabric/pull/970)
is this documentation branch's source base for current installed recovery.
Complete terminal/pending native qualification remains required; historical Java
compiler captures are bound to their original sources. Ticket and packaged
acceptance must not be inferred from this branch or prior fixture receipts.

Strict commands stage business state and intents; the host decides commitment
only after accepted work retires and staging seals. Immediate irreversible calls
are denied. Result lookup needs current read authority and preserves the original
identity; local timeout or cancellation supplies no abort proof. Compatible
upgrades preserve pending formats and linked protection. Older-history restore
changes incarnation and starts dispatch paused. Code rollback cannot rewind
state or external actions.

Phase 4 does not add a production Windows node, Mac/ARM64 support, general SQL,
external database, cluster routing or durable workflows. Its remaining platform,
SDK, migration, restore and application matrices are acceptance work, not implied
support. The independent SDK library gates do not redefine the core transaction
model.

## Phase 5: cluster

Separate control plane, route watches, direct node invocation, mTLS identity,
artifact prefetch, state affinity and multi-zone placement remain planned.
Current service calls are isolated local calls. Carry
[RFC-0004](../rfcs/0004-route-and-authorization-freshness.md) and its
[conformance handoff](architecture/cluster-freshness-handoff.md) into implementation:
finite authorization, guarded start, clock/replay/restart/reconnect behavior and
partition availability need executed multi-node evidence.

## Phase 6: durable workflows

Explicit workflow state machines, durable timers, continuations, awaited effects,
replay and compensation remain planned. Invocation-local timers, provider retries
and consumer cursors do not supply workflow suspension or replay.

## Phase 7: research promotion candidates

User-space paging, continuation eviction, call-graph fusion, immutable shared
blobs, adaptive materialization,
[native software fault isolation](runtime/native-sfi-research.md) and hardware
capability backends remain [research](../research/README.md) candidates. Promotion
requires a separate accepted decision and qualification.
