# Call-graph fusion

Investigate runtime-derived composite artifacts for stable local call chains,
while services remain independently authored and released. Fusion keys must
include every relevant release, binding, policy, runtime, compiler and
resource-accounting input. Logical tracing and failure semantics must remain
visible after fusion.

**Status: specification and source/literature review only.** LSF has no
call-graph fusion implementation or measured fusion speedup. The benchmark
remains [`specified`](../../benchmarks/fusion/benchmark.toml).
[ADR-0016](../../adr/0016-keep-paging-continuation-eviction-and-fusion-optional.md)
keeps this optimization optional and requires later decisions and conformance
evidence before promotion. The roadmap's research phase is a classification,
not a prohibition on bounded experiments.

This track now contains an [upstream/composition review](upstream-review.md),
a [semantic evaluation plan](evaluation-plan.md), and an updated
[benchmark protocol](../../benchmarks/fusion/README.md). None is an executed
experiment. The [website guide](../../docs/runtime/call-graph-fusion-research.md)
summarizes current availability and the distinction from native-SFI.

## Reviewed source

Reviewed on 2026-10-15 against documentation-stack parent
[`7661a60955daff6505165e78541433ca35f7cf71`](https://github.com/KirilsTurkins/latent-service-fabric/tree/7661a60955daff6505165e78541433ca35f7cf71).
The supplied development snapshot
[`90cf1f4c87ca24e9a64b077dc2eb501dcef22441`](https://github.com/KirilsTurkins/latent-service-fabric/tree/90cf1f4c87ca24e9a64b077dc2eb501dcef22441)
was checked separately. The reviewed local-call manager, broker-plan and
Wasmtime service-adapter files are unchanged between those revisions. This does
not make the full revisions interchangeable: the stack selects Wasmtime 48.0.6
and wasmparser 0.261.0; the supplied development snapshot selects Wasmtime
48.0.5. Native artifact and execution evidence retain their original identities.

| Existing mechanism | Evidence and limit |
| --- | --- |
| A fusion eligibility declaration | [`ExecutionRequirements`](../../crates/latent-manifest/src/lib.rs) includes `fusion_eligible`; this is not an optimizer, execution mode or safety proof. The [Angular SSR compatibility check](../../crates/latent-manifest/src/runtime_compatibility/profile.rs) rejects it. |
| Compiled bindings and currentness | [`CompiledCapabilityPlan`](../../crates/latent-capabilities/src/broker/plan.rs) retains checked target/binding/policy/publication dependencies and bounded metadata. It has no live guest instance or provider connection. It is authorization/binding preparation, not fused code. |
| In-process local invocation | The [Wasmtime adapter](../../crates/latent-wasmtime/src/host/service.rs) enters the broker and [local activation manager](../../crates/latent-node/src/activation_manager/local_service.rs), without an inter-service network hop. |
| Distinct child lifecycles | The [local-call contract](../../docs/runtime/local-service-invocation.md) supplies a fresh Store and activation identity, a derived service principal, ordinary admission, delegated resources, an absolute deadline and owned cleanup. It explicitly performs no inline execution or fusion. |
| Fixed-capacity admission | A waiting parent retains its cell; `try_enqueue` assigns an existing child cell or rejects promptly before child preparation. A one-cell composite would change this admission behavior. |
| Observable service bytes | The [canonical import](../../wit/platform/invocation/package.wit) takes opaque payload bytes and returns bounded byte-bearing outcomes. The [WIT-value codec](../../docs/protocol/wit-values.md) and [existing acceptance test](../../crates/latent-wasmtime/tests/local_service/acceptance.rs) make their representation observable. |

No current runtime feature is being enabled by this review.

## Three levels with different claims

Consider `Quote@A -> Pricing@B -> Tax@C`. A derived artifact can pin that exact
chain without making its members one heap, one activation, one authority or one
transaction. The research must identify which physical work it changes.

| Level | Candidate optimization | Boundary and claim |
| --- | --- | --- |
| A: joint preparation and plan specialization | Prepare exact member code and checked connections together, building on existing capability plans. | Preserve child Stores, start checks, cells, admission, failures and accounting. Measure incremental savings over today's caches/plans. This is not yet a fused guest artifact. |
| B: component composition with guarded adapters | Derive and compile an actual component graph with explicit internal adapters. | Type matching alone cannot preserve service-call semantics. Demonstrate fresh logical callee state, typed failure handling, member-specific host authority and accounting. Distinct component memories do not settle these obligations. |
| C: reduced activation machinery | Elide or virtualize separate Stores, cells or lifecycle work. | A new execution/capacity model requiring its own decision and conformance evidence. Do not label changed overload outcomes or shared mutable state as transparent optimization. |

Begin with A and measure whether any avoidable work remains. Attempt B only as
an isolated experiment. C is a separate research question, not a compiler flag
that can be assumed to follow from successful composition.

## Meaning of a preserved service call

The semantic comparison is between logical call traces, not just final answers.
For the initial candidate, retain the same selected publications, allowed
effects, start/currentness decisions, per-call outcomes, authority, reservation
owners and cleanup obligations. Fresh opaque IDs and elapsed times naturally
differ between runs; compare their relationships and ordering constraints rather
than literal identifiers or identical timestamps. Nondeterministic inputs need
controlled clocks/providers or an explicitly stated allowed-result relation.

Several small counterexamples are decisive:

- **Repeated callee:** B initializes a mutable counter to zero and increments it
  once. Two fresh B calls return `1, 1`; reusing B's instance may return `1, 2`.
  A stateless manifest does not prove absence of mutable globals or constructors.
- **Authority:** A can call B, while only B can read a secret. A composite may not
  give A B's grant or a host context containing the union of member permissions.
  Same tenant does not mean same authority.
- **Failure:** the parent can inspect a child's platform failure and continue.
  A trap propagated directly through a composed call may instead terminate the
  root. Matching successful outputs is insufficient.
- **Capacity:** with one free cell assigned to A, the ordinary nested child may
  be rejected. Running B inside A's cell changes the admission contract even if
  the application happens to succeed.
- **Bytes:** a caller may inspect the exact returned JSON bytes, media type and
  error envelope. Removing an internal copy is different from replacing that
  observable interface with a typed business-function call.
- **Effects:** combining artifacts cannot authorize an immediate child call
  inside a strict transaction command or merge independent command identities.

Current [descendant budgets](../../docs/runtime/descendant-budgets.md),
[required capability audit](../../docs/runtime/capability-audit.md),
[execution-cell ownership](../../docs/architecture/execution-cells.md) and
[transaction authoring](../../docs/component-development/transactional-authoring.md)
remain constraints. Fuel, deadlines and resource exhaustion require particular
care: physical optimizations may change instruction counts or timing. A different
metering model needs an explicit contract; it cannot silently drop logical
reservation ownership or promise identical exhaustion outcomes.

## Candidate selection and disposition

Initial hypotheses favor small, repeated, same-tenant serial chains with exact
stable bindings and measurable boundary costs. Exclude cycles, cross-tenant
fusion, transaction-bearing graphs, Angular SSR, uncontrolled dynamic targets,
fan-out/join and six-runtime generalization from the first prototype. The
ordinary path remains available for workloads outside the research scope.

Observed edges suggest candidates; they neither authorize calls nor prove that
unseen branches are impossible. Retain current checks at each logical start,
bound optimization and cache churn, and forbid replay-based fallback after work
has been accepted. The [evaluation plan](evaluation-plan.md) specifies these
rules and the promotion decision. A useful result may be a negative finding
that existing preparation/caching already removes most of the available cost.
