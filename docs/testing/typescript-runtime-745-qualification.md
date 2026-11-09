# TypeScript runtime #745: integration qualification ledger

Status observed on **2026-11-09: blocked; not merge-ready**. This ledger supports
[PR #1928](https://github.com/KirilsTurkins/latent-service-fabric/pull/1928), targeting
`feat/typescript-runtime-745`, and the still-draft
[PR #1852](https://github.com/KirilsTurkins/latent-service-fabric/pull/1852).
It neither closes [#745](https://github.com/KirilsTurkins/latent-service-fabric/issues/745)
nor promotes a compiler candidate or authorizes a release.

The starting head is `83c339673b87afabfa06f3a8e818324f46c1ae6f`.
The inspected historical CI checkout is **synthetic merge**
`6ab3da5364ac3e7db57c7154f894bc6223ad728b`, not the integration head.
The [audit record](evidence/typescript-runtime-745-audit-2026-11-09.json)
binds the downloaded archives, engine/patch/compiler/component/native identities,
provider bindings and local attempts. Reusing those bytes does not rebuild them.
A later integration must record its own exact head and tested merge separately.

## Staged review integration — 2026-11-09

**Reviewed source tree:** `615766e5e10564a9b6503ae93d21742cfce71a6a`
(code-stage head before this evidence-only ledger revision). Agent file blobs were
staged on isolated #1928 through single-parent commits; no source branch was
force-updated or merged into the parent PR. This is **source integration**, not
an executed signed qualification of the new tuple.

| Agent | Reviewed delivery | Staged scope | Status still open |
| --- | --- | --- | --- |
| 1 | [#1932](https://github.com/KirilsTurkins/latent-service-fabric/pull/1932), `d483b31a1141df962edcc4eb71bb54270445ef4a` | Three-file signed probe checkpoint/refusal assertion and negative controls; no experimental workflow history | **Explicit final blocker:** real `abort-fanout-refusal` unreachable-code trap remains unexplained, with no post-failure cleanup sample. Not a runtime fix. |
| 2 | [#1934](https://github.com/KirilsTurkins/latent-service-fabric/pull/1934), `9636f2c26112be311c4bee3353d68688ee1b524c` | Eleven-file root LIFO, EventTarget failure propagation and guarded default DOMException factory + fixtures/docs | 101 GCC/Clang finite controls, 27 focused sanitizer controls and Node wasm trap witness are source/host evidence, **not** patched SpiderMonkey, signed guest or Store custody. |
| 3 | [#1931](https://github.com/KirilsTurkins/latent-service-fabric/pull/1931), `835def07622ff9405138c974c286017ff7d637a4` | Eight-file ACK token retention/retry, cancelled import fencing, pre-effect timer capture, reservation-slot rejection, tests/docs | 23 GCC/Clang/ASan controls per compiler variant (12 old-source failures) are finite. Aggregate byte accounting and Store/pooled memory physical retirement remain incomplete. |
| 4 | [#1929](https://github.com/KirilsTurkins/latent-service-fabric/pull/1929), `a11228373ecd403e30f71ac1a1cb9ede2e2bc57e` | Three-file module-family diagnostics, boundary controls, network compatibility matrix | 33/35 host checks passed with **two skips**; no fresh pinned compiler/signed net result. #738/#739 stay open and no public DNS/TLS/general streams are enabled. |

Agent 5's original fixture pairing `ddae8e8799f182c2839a83a9e548b615f9267380`
remains a test-only sanitizer correction. Agent 1 diagnostic workflow commits are
**not** accepted fixes; none of the above counts becomes signed acceptance.
The historical engine digest `sha256:149b58b73d4dab8539e62c5ae4392a582637d9969588df6f490ba35a2d123d5b`,
component digest `sha256:7ea905f38f6cd241760cc7b0d8fa18408a094a03b5ad7491a182cb872ceb080b`,
compiler and provider IDs in the JSON audit belong exclusively to the
historical `6ab3da5364ac3e7db57c7154f894bc6223ad728b` merge.
**No selected new engine, patch/component/native/provider tuple has yet passed
for the staged integration head.**

GitHub launched head-`615766e` workflows: runtime ownership controls
42704632350, TypeScript guest qualification 42704632832, CI 42704632374,
developer tools 42704632343 and IntelliJ project 42704632778. At observation
they were queued/pending; each must be rechecked for the final, documentation-
updated checkout SHA. A later commit may cancel superseded runs, not pass them.


## Status vocabulary

**Implemented** means source exists, not that every behavior is qualified.
**Signed-qualified** applies only to a named case, component, runtime tuple and
limits in a successful signed observation. **Unqualified** includes failed,
unreached, untested and historical-only coverage for a changed engine.
**Dependency-blocked** means an upstream approved contract/provider or its
required evidence is still missing. Existing issue checkmarks below are recorded
as issue state; they are not fresh qualification of this branch.

## Parent acceptance criteria

| # | Requirement and issue state | Implementation/evidence | Integration status and remaining obligation |
| --- | --- | --- | --- |
| 1 | Actual compiler/engine export/import continuation, genuinely suspended Promise, thenables/errors/WIT results; checked | Source splicer/import engine; [scheduling](typescript-runtime-semantics.md) and [retirement](typescript-runtime-retirement.md) retain historical signed evidence. Historical run 42516280360 built the selected compiler and engine. | Implemented; final-head signed qualification pending. `promise-ready` alone does not prove every suspended-export/error path. |
| 2 | Bounded microtasks/jobs, ordering/reentrancy/readiness, run-to-completion and CPU containment; checked | Native job/readiness implementation, emitted controls and historical scheduling programme. | Implemented within the declared profile; selected-head ordering, host wakeup and containment programme still required. No worker-context claim. |
| 3 | Timer subset, AbortSignal, recurrence/catch-up/overlap, callback errors and cancellation races; checked | [Timer-race programme](typescript-timer-races.md); [fan-out implementation](typescript-abort-fanout.md). Nine-dependent fan-out passed in the inspected signed run. | Partial signed coverage only. Fan-out refusal failed; subsequent default-factory reentry and fresh fan-out were not reached. Broader timer races need the integrated engine. |
| 4 | Root settlement versus accepted work, unhandled rejection, drain and opaque callbacks; checked | [Root lifecycle](typescript-root-lifecycle.md) and retirement programmes retain their original product identities. | Implemented finite lifecycle; no final-head signed drain/late-callback/quarantine claim. Missing post-refusal cleanup cannot be inferred from CLI exit. |
| 5 | Original-budget accounting for jobs/reactions/captures/results/GC/native stack and heap/host lowering; cancellation/trap cleanup; **open** | Count/model admissions, tracking retirement and source-owned AbortSignal vector custody exist. Host C++ controls exercise selected transitions. | **Unqualified and incomplete.** The 64-native-owner ceiling is not aggregate byte accounting. Agent 3 owns allocation/physical-owner coverage; actual traps, Store destruction and quarantine need runtime evidence. |
| 6 | Package-independent, named/versioned automatic runtime modules; concrete unsupported-operation diagnostics; checked | [Import candidate](../component-development/typescript-import-runtime-candidate.md), [Fetch profiles](../component-development/typescript-fetch-profiles.md), captured source/lock and diagnostics. | Implemented selected APIs, not full Node/browser support. Unchanged published/transitive library execution on the integrated tuple remains unqualified. |
| 7 | Approved stream/DNS/readiness and node:net/node:tls mappings; **open** | Existing [finite node:net candidate](../component-development/typescript-node-net.md) is not full stream/DNS/TLS support. #737 is a design gate; #738/#739 remain upstream implementation/qualification dependencies. | **Dependency-blocked** for unapproved/unimplemented mappings. Agent 4 owns the exact compatibility matrix. Typed HTTP success neither grants sockets nor proves this criterion. |
| 8 | Snapshot isolation and fresh activation/module/Promise/timer state; checked | Capture/effect-denial controls and historical fresh-state programmes; earlier clone/any/default fresh cases passed in the inspected run. | Implemented source boundary; integrated fan-out fresh case and cross-tenant state/late-completion barriers remain unqualified. Immutable image reuse is not persistent guest-worker support. |
| 9 | Builder/runtime profiles, automatic patch provenance, diagnostics/toolkit, direct SDK and synchronous regressions; checked | Historical compiler/library/component jobs passed; local source/adapter/profile regression controls pass. Exact input envelope stays `qualification: unknown`, `apiSupport: not-evaluated`. | Implemented provenance path; final-head toolkit/native/direct-SDK/synchronous and signed CI still required. Do not rewrite historical receipts to a new source. |

## Changed-behavior coverage

| Required behavior | Evidence inspected or executed | What is not established |
| --- | --- | --- |
| Nine-dependent fan-out and order | Historical signed `abort-fanout` returned `abort-fanout:9:ordered`; emitted C++ controls pass. | A new integrated-engine run is still needed. |
| Refusal before mutation and retry | Emitted controls pass. Actual signed `abort-fanout-refusal` failed with `guest-trap` / `unreachable-code`. | Refusal/retry is **not** signed-qualified. No root cause follows from the trap kind alone. |
| Default DOMException factory reentry | Emitted controls model the pinned factory. The selected-engine case exists after the failing case. | Signed reentry was not reached. Node's primordial factory is not a substitute and must not turn a native-only failure into a passing skip. |
| First exception, saved stack, nested/independent callbacks | Emitted bodies execute against serialized JS/vector/broker doubles, including first-error and no-pending failure controls. | Real SpiderMonkey root-stack/GC behavior and actual trapping frame custody require Agent 2's audit and selected-engine runs. |
| Timer and Promise interaction; resource exhaustion | Source/adapter controls plus separately scoped historical scheduling/timer/limit receipts. | Those receipts are not rebound to this changed engine; timer storms, complete heap/stack accounting and all races are not proven. |
| Cancellation, actual traps, late completion, quarantine | A genuine guest trap is retained, unlike a C++ false/no-pending simulation. Earlier retirement receipts have finite scope. | The failing Fetch runner stops before its `retire` call. There is no `after-abort-fanout-refusal.json`; Store destruction or quarantine success is not established. |
| Fresh activation and tenant isolation | Earlier fresh clone/any/default cases passed; historical tenant programmes remain separate. | Fan-out fresh was not reached; same-node cross-tenant cleanup for the integrated engine is outstanding. |
| Unchanged published npm libraries and transitive async/timers | [Published Fetch](typescript-published-fetch.md), [published delay](../component-development/typescript-published-delay.md) and their original receipts describe finite ordinary-path evidence. | The inspected new Fetch attempt explicitly records `unchangedPublishedClients: not-run` and `privateConsumer: not-run`. No injected transport, fork or manual pump may substitute for the required rerun. |

## Inspected CI and failure attribution

[TypeScript run 42516280360](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/42516280360)
used the historical synthetic merge above. These are job conclusions, not an
assertion that every optional step in a successful job executed.

| Job ID | Job | Result |
| --- | --- | --- |
| 128839888530 | Source-owned asynchronous import compiler | Passed |
| 128839888691 | TypeScript guest value and ownership boundary | Passed |
| 128861884917 | Patched SpiderMonkey intrinsic Promise library | Passed |
| 128883085538 | Actual source-owned Fetch component construction | Passed |
| 128915932731 | Finite signed default Fetch and one-shot JSON bodies | **Failed**, build/sign/invoke step |
| 128839889446 | Same-component signed Math.random policy and fresh-state programme | Skipped |
| 128839889597 | Private numeric frames for the authenticated failed Fetch component | Skipped |
| 128839889645 | Actual signed pending Promise cancellation deadline and physical retirement | Skipped |
| 128839889649 | Captured outside node:fs open create and temp refusal | Skipped |
| 128839890031 | Same-SDK signed Promise and Request-copy boundaries | Skipped |
| 128839911129 | Ordinary Date and performance signed authority and fresh-state programme | Skipped |

The Fetch failure follows 15 completed cases. Its actual control row has exit 4,
known outcome, 36,681,652 fuel, 10,342,432 peak memory bytes, and zero outbound,
child-call and effect use. `processReaped` describes the invoking CLI, not a
proof that every guest/native owner retired. Agent 1 owns this regression.

[General CI run 42516280482](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/42516280482)
has separate failures:

| Job ID | Result and diagnosis |
| --- | --- |
| 128858212162 | **Failed**, Repository contracts (python): AOT feature closure, composition `resource-budget` source binding, embedded-resource runner AST preservation, and Java-resource runner selector preservation. |
| 128858212190 | **Failed**, Rust 1.97.1 (tests): authenticated AOT preparation failed the same feature-closure control. Workspace compilation/discovery and a separate exact-case control passed; the full `Run tests` step was skipped. |
| 128892639564 | **Failed**, CI result: selected validation jobs did not all succeed. This is an aggregate failure, not an additional runtime defect. |
| 128891871961 | Skipped, OCI registry TLS integration. |

The remaining jobs passed: Select CI profile (128839889132), Documentation and
SVGs (128858212013), Rust MSRV 1.95.0 (128858212057), Durable catalog acceptance
(128858212081), Rust checks (128858212113), Fast host correctness (128858212114),
Rust qualification (128858212122), renderer-angular (128858212123), Cross-language
SDK surfaces (128858212145), publications (128858212149), runtime contracts
(128858212157), bindings contracts (128858212176), renderer-public (128858212196),
provider (128858212208), angular-t1 (128858212238), sdk-provider contracts
(128858212264), optimization contracts (128858212285), measurements contracts
(128858212315), standalone contracts (128858212349), and Documentation website /
Static site, examples and browser journeys (128858212577).

The AOT discrepancy is the existing `development-go-network-read-witness` Cargo
feature missing from `tools/aot_test_inputs.py`'s producer list. The archived
Cargo manifest and producer match development base
`8ea98eba85a4afa644d67654cb838ec302565c1d` exactly (Git blobs
`8ed2f53eb782d934ab14c05c1517198942d1b68c` and
`0b3d89deb0da6671990e6ce67f1b3955d40e71b7`). This is not introduced by the
six-file AbortSignal diff, but it remains a real integration blocker.
The AST failures also reproduce in the archived source outside that diff.
The composition failure was inspected in CI; its local reproduction stops
instead at a missing contract omitted from the selected source archive.
A complete development/base replay is still needed before blanket attribution
of those other failures. None is suppressed or relabelled as success here.

## Local validation and its limits

The available source is the retained selected-source archive, not a complete Git
checkout. The retirement fixture's pre-edit Git blob was checked against the
starting head; all engine-envelope SDK inputs match the retained source bytes.
The following outcomes are observations, **not fixed test-count CI contracts**.

| Attempt | Result |
| --- | --- |
| Initial focused source/ownership/profile tests | 92 passed |
| Initial Clang ASan+UBSan ownership run | 38 run; nine failed with test-harness new/free mismatch |
| Corrected fixture, GCC 14.2.0 | 38 passed, no skips |
| Corrected fixture, Clang 17.0.0 | 38 passed, no skips |
| Corrected fixture, ASan+UBSan with leak detection | 38 passed, no skips or suppressions |
| Broader source/adapter/profile/Fetch regression set | 176 passed |
| Unpinned standalone TypeScript 5.8.3 invocation | Failed: missing generated WIT interface and wrong ambient AbortSignal.any signature. Not the maintained TypeScript 7.0.2 compiler pipeline. |
| Historical package reconstruction | Passed using the original native packager; restored WIT files match every recorded package-input hash/size. |
| Local signed replay of the historical component/native binaries | Failed at node readiness, before any guest case. No new engine/native build or signed pass. |

The allocator correction supplies paired throwing/nothrow scalar new and delete,
keeps allocation watching active, and throws `bad_alloc` for failed throwing
allocation. Production owner logic and every existing assertion are unchanged.
The new `typescript-runtime-controls.yml` runs GCC, Clang and sanitizer variants
without fail-fast cancellation between variants or sanitizer recovery.

Run the sanitizer variant from the repository root:

```sh
LSF_TYPESCRIPT_RECORD_CXX=./tools/typescript_runtime_sanitizer_cxx.sh \
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
python3 -B -m unittest tools.tests.test_typescript_event_ownership \
  tools.tests.test_typescript_record_retirement \
  tools.tests.test_typescript_abort_any_ownership -v
```

Use `LSF_TYPESCRIPT_SANITIZER_CXX` to select an explicit installed Clang compiler.
The adapter is test-only; it does not build SpiderMonkey or validate Wasm trap
unwinding. Compiler and Python versions are recorded by the CI job.

## Authority, budgets and completion gate

The Fetch runner retains Task16, Executor2, Queue16, Wait8, Timer8, Result8 and
Native64. The node ceiling remains 128 MiB, the original wall-time ceiling is
120 seconds, and outbound requests are capped at one per invocation. Fan-out
cases require **zero** outbound/child/effect usage. Runtime policies retain
4,096 operations, zero input bytes, 32,768 output bytes and five seconds; HTTP
remains bound to the original publication, service, GET origin and two exact
paths. Missing runtime/HTTP grants must still deny before guest work.

Successful cases still require physical-idle counters and stable native metadata
with no dropped accounting. Final node/peer shutdown and exact wire-contact
checks remain mandatory; they were not reached in the failed signed programme.
This integration changes no policy, profile, resource ceiling, deadline or
post-invocation oracle. A count-model reservation cannot stand in for the
aggregate ownership requirement.

Before promotion, retain these reviewed staged source/test blobs, resolve the
parent development conflict without discarding either side, and record the
exact final integrated checkout and source/compiled-product identities. Run the normal source-splicer, patched-library, selected engine,
component build, signed Fetch, runtime scheduling/retirement/limits, ordinary
published-library and applicable dependency-approved networking programmes.
Historical-product replay workflows must remain labelled historical; opting
into one is not a fresh integrated-engine build. Check every selected CI job,
including general failures, then bind the final receipts to source/compiler/
patch/component/native/provider identities and unchanged authority/limits.

The four partial deliveries are staged, but none constitutes whole-criterion
qualification. Agent 1 has explicitly reported the unresolved signed refusal;
Agent 2's source fix still needs pinned-engine execution; Agent 3's Store custody
and byte accounting remain blocked; Agent 4's provider/operator gates remain
open. Keep #1928/#1852 draft and both open #745 criteria unchanged.
