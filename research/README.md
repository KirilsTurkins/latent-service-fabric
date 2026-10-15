# Research tracks

Research code must not become a required production dependency. Each track needs an explicit semantic model, portability statement, security analysis, benchmark, and promotion ADR.

Research promotion follows its own evidence and architecture review, separately
from the [implemented runtime and planned phases](../docs/roadmap.md). A
prototype, source inspection or historical measurement does not establish a
delivered standalone capability.

Concrete proposed contracts are now collected in the
[draft RFC index](../rfcs/README.md#draft-research-proposals): durable segments,
boundary-preserving call specialization, native guest admission shared by SFI
and hardware compartments, and optional mapped state. The
[review guide](../docs/runtime/research-proposals.md) explains the choices and
remaining questions. These drafts do not promote the research or supersede ADRs.

## Call-graph fusion

The [fusion investigation](call-graph-fusion/README.md) distinguishes joint
preparation, guarded component composition and deeper activation merging.
It includes [primary-source and tooling research](call-graph-fusion/upstream-review.md),
[semantic evaluation gates](call-graph-fusion/evaluation-plan.md) and the
[benchmark protocol](../benchmarks/fusion/README.md). Existing local calls already
use in-process dispatch and compiled bindings. No fused artifact, optimizer or
measured LSF speedup is delivered; fresh state, authority, admission, failure,
accounting and cleanup remain obligations at logical call boundaries.

## User-space state paging

The [userfault-pager investigation](userfault-pager/README.md) reviews optional
state materialization and dirty tracking against existing selective reads,
kernel-managed mappings and prefetch. Its [primary-source review](userfault-pager/upstream-review.md),
[mapping/transaction model](userfault-pager/mapping-model.md) and
[evaluation gates](userfault-pager/evaluation-plan.md) cover blocked-worker
recovery, authority/view lifetime, integrity, tracking epochs and stale resolution
after address reuse. No pager or mapped-state guest profile is implemented.
Explicit capability calls remain portable; paging does not evict a complete Store.

## Continuation eviction

The [continuation-eviction investigation](continuation-eviction/README.md)
separates retained asynchronous waits, explicit durable workflows, compiler
capture and history replay. It adds a [primary-source review](continuation-eviction/upstream-review.md),
[durable handoff model](continuation-eviction/handoff-model.md) and
[evaluation gates](continuation-eviction/evaluation-plan.md) for complete Store
retirement, wakeup delivery, exclusive resume, current authority and recovery.
The workflow crate supplies interfaces, not a durable engine. No capture/restore
compiler, checkpoint experiment or measured eviction benefit is delivered.

## Native software fault isolation

The [native-SFI investigation](native-sfi/README.md) reviews restricted native
code as an optional execution backend, distinct from existing Wasmtime AOT.
It records [pinned upstream findings](native-sfi/upstream-review.md) and an
[adversarial evaluation plan](native-sfi/evaluation-plan.md), including native
artifact admission, capabilities, interruption, fault recovery and physical
cleanup. There is no LSF native-SFI prototype or qualified backend. Candidate
artifacts remain outside the node until the research and promotion gates pass.

## Hardware capabilities

The [hardware-capability investigation](hardware-capabilities/README.md)
distinguishes architectural memory references from LSF policy and affine owners.
It includes [primary-source/platform review](hardware-capabilities/upstream-review.md)
and [evaluation gates](hardware-capabilities/evaluation-plan.md) for bounded
compartments, safe retirement and sharing, plus a separate MPK study against the
current compact Wasmtime layout. There is no qualified LSF hardware backend.
The track remains optional and cannot define the portable capsule contract.

## Outbound streams and typed protocol boundaries

The [outbound streams investigation](outbound-streams/README.md) includes a
local-only SMTP/TLS prototype, source-bound ownership measurements, a six-language
compatibility review, candidate contracts and
[ADR-0059](../adr/0059-defer-general-outbound-streams.md). It proposes deferring
production sockets; it is not a dependency of ordinary libraries or HTTP adapters.

## Bounded invocation-scoped concurrency

The [invocation concurrency investigation](invocation-concurrency/README.md)
compares the six compiler profiles, includes an isolated actual-component Rust
experiment and records scope ownership, fairness, cancellation and timer limits.
The revised [ADR-0060](../adr/0060-bound-invocation-scoped-concurrency.md) targets
standard runtime compatibility beneath unchanged application and transitive
dependency code, without requiring developer-supplied executor/transport adapters.
Logical threads, pools and timers are implementation targets during an activation;
persistent guest work and fabricated execution remain forbidden. Separate runtime
and standard-I/O qualification must precede enablement and reconcile ADR-0059's
outbound recommendation. The original prototype and receipts are not evidence of
these new runtime facilities, nor a blocker for ordinary dependency ingestion.
