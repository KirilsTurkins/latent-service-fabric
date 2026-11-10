# TypeScript runtime #745: combined integration follow-up, 2026-11-10

Status: **unqualified; keep #1928 and #1852 draft and #745 open**.
Review began at `66054bb04222068568e7af690119b1dcbb2c675e`. Concurrent source
staging `8ca825fef52deafaf0be4f2d324d054ca32fe51c` was preserved; this follow-up
adds only evidence, regression, workflow-contract and documentation changes.
The resulting Git commit and its Actions checkout SHA identify the candidate; none of the earlier component
receipts is relabelled as evidence for this combined source.

## Reviewed sources and conflict resolution

| Owner | Reviewed source | Integrated scope and limits |
| --- | --- | --- |
| Agent 1, #1932 | `57cfd22f0df9f611d67bba421b7b27be99e4c2b4` | Export metadata wrapper fusion, retained awaited refusal/retry assertions, separate completed-graph reentry lifetime, regression controls and [causal audit](typescript-abort-fanout-refusal.md). Exclude temporary acquisition and historical-product workflows; the normal all-agent workflow must rebuild the selected engine. |
| Agent 2, #1934 | `72a26d82c7a2e38b642e38cc1a26f264abe3a872` | Exact listener identity and native-reference custody, duplicate and re-registration semantics, emitted controls and [audit](typescript-abort-listener-identity-audit.md). Keep the prior missing-tool errors and replace the new identity-control skip with an error. Add the new class to prerequisite regression coverage. |
| Agent 3, #1931 | `835def07622ff9405138c974c286017ff7d637a4` | Existing original-token retry, stopped-import and capture-before-effect fixes remain unchanged. Newer `5b633b52b218908ea88d6905225a85715df4edf5` is acquisition-only and is not staged. Store/pool custody and aggregate accounting remain unresolved. |
| Agent 4, #1929 | `99d122fbce0b2dc55519686923558f54c9db7247` | Scoped pinned networking compiler workflow, its two owner contracts, compiler controls and compatibility guide. No provider, socket, TLS, DNS authority or grant enablement. |
| Agent 5 | Current integration delta | Preserve the original failure if writing FAILED.json fails; retain rejected inventory/usage before validation; add orchestration and AOT negative controls; register the ownership workflow and extend its commands. |

Agent 1's candidate addresses avoidable live export Promise/adoption ownership,
not a native-owner exemption. The same nine-dependent refusal graph remains
live through a real awaited checkpoint and retry. Agent 2's strong listener
reference intentionally retains that listener's original lease; it is not a
new token or a claim that all captured bytes are measured. Source-only/native
model results do not certify either candidate on the signed LSF host.

The failure observer still performs at most two read-only host queries within
three seconds and the original remaining campaign deadline. It does not retry
the guest or fabricate zero counters. Evidence-write errors remain secondary
type-only notes on the original exception, including cancellation. Rejected
`after-<case>.json` and `after-<case>-usage.json` samples are retained; their
presence does not convert a failed invocation or uncertain cleanup into success.

## Executed local validation

Tests used the authenticated source projection from artifact `13715893543`,
synthetic checkout `52ac8d24e5d294836467c2b90189120c47b0c4af`, overlaid with
verified current integration and reviewed agent blobs. This is not a complete
fresh Git checkout, pinned-engine build, native Rust build or signed execution.
Tool versions: Python 3.13.5, GCC 14.2.0, Clang 17.0.0 and Node 22.16.0.

| Command group | Observed result |
| --- | --- |
| Combined Python/source/adapter/profile/compiler-reference/native/AOT-boundary regressions | 231 passed, zero skips |
| Maintained ownership, prerequisite, failure, export metadata and AOT-boundary modules, GCC | 63 passed, zero skips |
| Same module selection, Clang | 63 passed, zero skips |
| Same module selection, ASan+UBSan with leak detection and halt-on-error | 63 passed, zero skips or suppressions |
| New failure-evidence tests against the unchanged b6d080f4 runner | 5 tests: 1 failure and 7 errors; negative regression witness, not a passing qualification |
| Same failure-evidence tests with the correction restored | 5 passed |
| Full AOT preparation and execution-control suites | 22 tests, 14 errors: test-prerequisite-unavailable; no process-accounting bypass |
| Networking host/reference suites | 37 tests: 35 passed, 2 existing frontend skips; not 37 passes |
| Strict pinned networking gate | Failed before compiler execution: network-boundary-pinned-node-required; zero success-output bytes |

Counts are observations, not fixed-count gates. Missing `/proc/pressure` and
Rust/Cargo prevent an ordinary local signed/native replay. Local Node 22 is not
the pinned Node 24.19.0. The hosted networking job must install the exact normal
frontend and rejects any skip or expected failure. No synthetic pressure data,
substitute provider, package fork or hand-pumped application task loop is added.

The ownership workflow runs the maintained modules with GCC, Clang and
ASan+UBSan. Its source/action identities are recorded by the job. Only its
ownership-local workflow/job contracts are added; unrelated contracts are not
refreshed. The new Python controls introduce no test suppression. The existing
v10 AOT profile and stale-profile refusal remain unchanged.

## Acceptance ledger

These rows supplement the historical [nine-criterion ledger](typescript-runtime-745-qualification.md).
Existing issue checkboxes are historical issue status, not new-head receipts.

| #745 criterion | Implementation / evidence status for this combined source |
| --- | --- |
| Export/import continuation and real suspension | Implemented selected path with new export-frame correction; source/reference tests pass; final combined signed continuation/thenable/error qualification pending. |
| Bounded jobs, ordering, reentrancy and host readiness | Existing implementation retained; local controls pass; changed-engine signed ordering/run-to-completion and host wakeup not yet established. |
| Timers, clear/recurrence and AbortSignal races | Existing timer implementation plus fan-out and exact-listener fixes; finite controls pass; signed new source, default factory and fresh recovery pending. |
| Root settlement, accepted work and rejection lifecycle | Existing contract retained; no Store destruction credited as successful completion; signed new-source lifecycle evidence pending. |
| Aggregate activation accounting and physical custody | **Incomplete.** Counts are not byte attribution; Store user-data ordering, pooled decommit/refusal/quarantine and generic captures/stack/host/lowering coverage remain open. |
| Named module/API profile, automatic source-bound shims and diagnostics | Existing profiles retained; generated-source identities change and must be rebuilt. Networking diagnostics remain narrower than a full Node environment. |
| Approved stream/DNS/readiness/net/TLS mappings | **Dependency-blocked / incomplete.** #738/#739, applicable #740, missing modules and authenticated fresh TCP producer remain open. Compiler-only checks are not provider qualification. |
| Build/snapshot and fresh cross-tenant isolation | Existing restrictions retained; no credentials/request state frozen or ambient network added. Changed-source signed fresh/tenant/trap evidence pending. |
| Builder profiles, provenance, diagnostics, toolkit and synchronous regressions | Source controls and maintained workflow extended; final source-bound compiler/component/native identities and CI remain required. |

## Historical evidence is not transferable

Source `183f1db349c29744cced7eb07813d829dd529473`, synthetic merge
`52ac8d24e5d294836467c2b90189120c47b0c4af`, TS run `42705015452`, signed job
`129601085022` failed after 15 cases through ordinary fan-out. The refusal case
was `guest-trap/unreachable-code`, with no post-failure cleanup sample.
Artifact `13737870869` ZIP SHA-256:
`783a6bcd15a947ac56eefb926ec215d6f56052007ddaa4201c631d2beee33733`.
Component SHA-256:
`37ac4a4f0bf6619d7de5953b94e0133cc4fd79817381fb5a5dd1bd658488838c`.
Exact historical compiler, engine/patch, runtime and provider identities remain
in [the immutable CI observation](evidence/typescript-runtime-745-ci-2026-11-10.json)
and [the original audit](evidence/typescript-runtime-745-audit-2026-11-09.json).

The reviewed Agent 1 audit reports actual retained SpiderMonkey diagnostic
execution, but its finite WIT ledger is not the signed LSF provider. Agent 2's
three compiled units and earlier-engine bug witnesses do not constitute a new
linked-engine pass. Agent 4's historical library/provider receipt stays bound
to its historical source; the missing producer cannot be replaced by a recent
Fetch engine or broader workflow-origin permissions.

Before readiness: rebuild the exact integrated source-owned engine and guests;
complete signed Fetch and unchanged published/transitive npm programmes; retain
original grants, ceilings, deadlines and cleanup oracles; record terminal job
IDs, source/checkout/product/provider identities and failure artifacts; address
Store/quarantine/byte attribution, approved networking and the parent conflict
with development. A successful host model, build, artifact upload or skipped
workflow is never enough to close a material acceptance criterion.

## Agent 5 continuation — 2026-11-10, after source 45e9b021

This follow-up incorporates only reviewed additive changes from Agent 2's
[cc2d67be](https://github.com/KirilsTurkins/latent-service-fabric/commit/cc2d67be0d3606da718fcc4669cc889256171001)
(parent `72a26d82`) and Agent 4's
[65fa26ed](https://github.com/KirilsTurkins/latent-service-fabric/commit/65fa26edc124a91a98a5c99d3b54d8a164142b47)
(parent `7e3817f`). The previous integration source was
`45e9b021dbc481147468260e21314bf18351bd71`. The final successor
commit, PR synthetic merge, actual product/engine/patch/compiler/component,
runtime and provider identities must be read from its own CI receipts, **not**
from this historical section.

- **Agent 2:** `AbortSignal.any()` deduplicates and stages its source graph,
  reserves all backlinks before any infallible publication, and refuses
  allocation without a published partial result. The distinct stable
  `onabort` listener preserves ordinary listener identity and correct
  invocation receiver. Abort algorithms drain independently through catchable
  failures while completed records physically retire and failed/unrun records
  remain owned. Exception reporting avoids side-effecting user conversion and
  fences native failure. The test-file preimage differs because Agent 5
  independently replaced a missing-compiler `SkipTest` with `RuntimeError`;
  this correction is retained through a verified patch merge. Agent 2's
  **105 GCC, 105 Clang and 31 focused ASan+UBSan** passes are its own emitted
  C++/host controls; actual derived WASI translation units compiled, but a
  complete native engine link failed due to missing Mozilla allocator/glue.
  No signed guest/physical Store or real weak-GC proof is claimed. See
  [transaction audit](typescript-abort-transaction-audit.md).
- **Agent 4:** Socket idle timeout starts before/during connect rather than
  only after success; `setTimeout(0, callback)` removes the newest matching
  callback, timer refusal precedes connect listener and native reservation,
  and stale timer identities cannot clear replacement slots. Notification
  never becomes automatic destruction or a resource refund. Eight focused
  host controls passed; seven fail on the old backend. Combined host suites
  **49 run / 47 passed / 2 pinned-frontend skips** are not pinned compiler or
  signed Component Model passes. No TLS, general stream, public DNS, grants,
  provider or accounting code was enabled. Signed TCP prerequisite producers
  `40077087832`/artifact `12553639081`, `39420914927`/artifact
  `12265176239`, and `40042939576`/artifact `12541695434`
  listed zero available artifacts; the original workflow-origin gate also
  excludes this branch. #738/#739 remain open.

**New failed strict signed attempt on Agent 1's separate source:**
[run 42788274731, job 129734901112](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/42788274731)
for `57cfd22f0df9f611d67bba421b7b27be99e4c2b4` ended in
`typescript-library-exact-prepared-source-required` while authenticating
reused prepared native inputs from historical run `42516280360`. It
never reached component execution or the refusal probe; therefore it neither
reproduces nor resolves the original `guest-trap/unreachable-code` on this
new compiler. Retained failure artifact `13759750093` has ZIP SHA-256
`9587067cff959bde4c56845870128fa23cb396035d8bbd290fc4aafaa8fb7c89`.
Do not weaken source comparison or substitute old receipts: the prepared
inputs must be regenerated and authenticated for the actual selected source
before any new signed qualification claim.

All nine #745 acceptance rows above retain their prior unqualified status
until the rebuilt final integration's CI finishes. Local source/host control
results are separate from signed source-owned engine, aggregate byte
attribution, Store/pool quarantine, published npm and real-network evidence.


## Agent 3 reentrant cancellation gate staged (2026-11-10)

Reviewed Agent 3 [#1931](https://github.com/KirilsTurkins/latent-service-fabric/pull/1931)
commit `1d41110ca404b833c8da4c46080646b9be0156fc` (parent
`bce274289ff775c52bbf7ff8c9e1e88c154a3ebc`). The production JobQueue
now closes admission before declining to retire an executing callback
requested by reentrant cancellation. The running frame, queued sibling,
callback roots and prepaid original owners remain held; late and prepaid
admission, nested draining and repeated cancellation are fenced. Four
success/false/exception/refused-ACK cases exercise the production header
with finite broker doubles; pinned JSAPI fixture cases are separate and
do not prove physical Store destruction or signed guest execution.

Agent 3 reports **17 retirement unittest methods passed under GCC and Clang**
on that agent source, not on the combined integration head. Its diagnostic
input-acquisition workflow `bce27428` is not staged. The previous Agent 5
native-owner fail-closed compiler selection is preserved; the new
QueueCancellationTests prerequisite also raises a RuntimeError on a missing
C++ compiler, including Windows, and the missing-tool guard is extended.
Full GCC/Clang/ASan+UBSan and pinned engine/signed-component qualification
must run on the new exact combined integration head. No original budget,
grant, deadline, accounting interface or network provider changes.
Physical Store/pool/quarantine custody and aggregate byte accounting
remain **unresolved**.

Agent 1's newer [#1932](https://github.com/KirilsTurkins/latent-service-fabric/pull/1932)
`be5c0d5f5d0caa731fc6e7c448cc9f669d4e1259` updates only its
temporary qualification workflow to rebuild current native products.
Its signed run `42820097517` / job `129843136088` was **queued** at
review; the temporary workflow is not staged. The prior Agent 1 signed
run `42788274731` / job `129734901112` failed source provenance
before guest execution. It does not qualify the integrated compiler fix.
