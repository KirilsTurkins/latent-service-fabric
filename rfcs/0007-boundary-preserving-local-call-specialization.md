# RFC-0007: Boundary-preserving local-call specialization

- **Status:** Draft
- **Authors:** LSF project contributors
- **Created:** 2026-10-15
- **Target milestone:** Phase 7 research promotion

## Summary

Propose joint preparation of exact local-call candidates while retaining ordinary
child activations, Stores, cells, authority and failure handling. This is the
first stage of [call-graph fusion research](../research/call-graph-fusion/README.md),
with actual component composition and reduced activation machinery left to later
separate decisions.

The decision requested is the reusable candidate identity, per-call start checks
and fallback contract below. This draft enables no optimizer or manifest switch
and supplies no measured speedup.

## Motivation

Current local calls already use in-process dispatch and compiled capability plans.
The opportunity is incremental preparation/dispatch work, not elimination of an
inter-service network hop. A composite must not silently replace a service call
with a different security, capacity or error contract. Define that boundary before
choosing composition tooling or publishing performance results.

## Detailed contract

### Candidate identity and selection

Start with short, exact-publication, same-tenant serial chains. Retain independently
authored/released members. Observe identifiers and timings under finite bounds;
observations suggest candidates and never authorize calls or prove unseen branches
impossible. Exclude cycles, fan-out/join, transaction-bearing graphs, cross-tenant
composition and unsupported language/application profiles initially.

Build on the existing `CompiledCapabilityPlan`, with explicit dependency ownership.
A reusable candidate binds graph/call-site structure and repeated edges; every
member's publication/release/revision/content; exact contracts and byte codec;
binding/policy assumptions; runtime/compiler/target/security identity; generated
adapter bytes where applicable; and the selected accounting model. Any specialized
limit belongs in the key and contributes to variant cost.

Do not retain live principals, sessions, credentials, mutable guest state, request
payloads, deadlines, ledger instances or provider connections in the candidate.
Preparation/currentness and memory reclamation are separate owners: retained
immutable code can outlive invalidation without permitting another logical start.

### Preserve each service boundary

Each child still receives a fresh activation/Store and host-derived principal,
current publication/grant/provider checks, required audit admission, ordinary
scheduler assignment, delegated budget, original deadline and owned cleanup.
Perform these at the actual logical call boundary, including when B is revoked
after A starts. Same tenant never implies a union of member permissions.

Keep the canonical opaque payload/media-type/outcome representation and validation
limits. A typed component connection is not automatically equivalent to those
observable bytes. Child platform failures remain inspectable by the parent;
they cannot become an unhandled root trap merely because code was prepared together.

Retain fixed-cell capacity policy: a waiting parent owns its cell, and a child
gets an existing cell or the ordinary prompt rejection. Preserve logical meter
charges/reservations and physical cleanup; an optimization cannot create capacity
by refunding live owners. Actual CPU/time may improve, but this stage does not
adopt a new fuel or capacity model.

### Misses and invalidation

Select specialized preparation or ordinary preparation before root execution.
On a preparation miss, discard provisional owners and use the ordinary path only
after its own current checks. The initial stage keeps ordinary call machinery:
an unoptimized edge can take its normal broker path without replaying earlier work.
It cannot silently choose a different publication or retry an uncertain effect.

Once work is accepted, no whole-chain replay or shadow business execution is
permitted for fallback/equivalence checking. A future composed executable cannot
inherit the initial stage's safe per-call behavior without its own proof.
Bound dependency invalidation, active pins and stale-code retention.

## Compatibility and migration

Existing callers, WIT, value codecs and failure semantics remain the baseline.
`fusionEligible` is not a working execution switch today; this proposal does not
enable it or remove Angular SSR's exclusion. An explicit reviewed selection and
observability contract is required before implementation is exposed.

Actual component composites need fresh repeated-callee state, member authority,
error adaptation and accounting evidence. Eliminating child Stores/cells or changing
overload behavior requires another execution/capacity decision. Service contracts
and independent release eligibility remain intact in every proposed stage.

## Resource-allocation impact

Candidate observations, graph size, compilation jobs, code bytes, variants,
dependency indexes and active pins have finite node-owned caps. Charge compilation,
cache churn and initialization as optimization costs. Dormant deployments acquire
no live instance or service-specific worker. Optimizer saturation selects the
ordinary allowed path before work starts rather than adding hidden capacity.

## Security and trust-boundary impact

The existing broker, admission and scheduler remain authority owners. Generated
code/adapters enter the trusted preparation surface and need exact provenance,
verification and compatible artifact identity. No new authority follows from
an observed edge, cache hit, same-tenant membership or manifest eligibility bit.
Retain logical member tracing, audit identity and outcomes without private payloads
in observation caches. Fusion does not authorize forbidden transactional effects.

## Failure semantics

Preparation failure can choose the independently valid ordinary path before
execution. Per-edge denial, stale publication, full required audit, admission
failure, declared error, trap, cancellation and budget exhaustion keep their
ordinary classification and owner. Failed cleanup retains quarantine/charges;
root completion cannot hide an outstanding child. No automatic business retries.

## Alternatives

Improve existing caches/binding plans without another candidate abstraction if
measurements show little remaining cost. WAC composition is a possible later
vehicle, with additional service-semantic adapters. A direct monolith is a useful
reference with a different authoring/execution contract. One-cell execution is
a different admission policy, not this proposal's initial optimization.

## Validation plan

Use the [semantic matrix](../research/call-graph-fusion/evaluation-plan.md) and
[benchmark protocol](../benchmarks/fusion/README.md). Compare controlled ordinary
and specialized runs using logical traces, fresh-state behavior, authority,
per-edge revocation, child-error handling, bytes, audit, budgets and physical
cleanup. Include repeated B calls returning fresh state and the all-cells-occupied
case. Measure incremental savings over current plans/caches, compilation/churn
amortization and no-benefit cases. No fusion or specialization run accompanies this RFC.

## Open questions

1. Which measured work remains after existing plans/caches, and does it justify
   a separate joint-preparation owner?
2. How should candidate eligibility, node selection and observability be exposed
   without turning the existing manifest field into an implicit guarantee?
3. Which exact dependency/currentness interface avoids duplicating broker plans
   while bounding invalidation and active-code pins?
4. What evidence would justify a later composite artifact, and which metering or
   admission changes would require a separate RFC/ADR?
