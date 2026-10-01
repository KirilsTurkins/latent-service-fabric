# Bounded invocation-scoped concurrency investigation

This is the isolated feasibility experiment for
[#695](https://github.com/KirilsTurkins/latent-service-fabric/issues/695) and
[ADR-0060](../../adr/0060-bound-invocation-scoped-concurrency.md). It adds no
production executor, SDK task API, host ABI, timer grant or persistent guest work.
The [six-language inventory](languages.md) distinguishes profile/source evidence
from this Rust-only actual-component experiment and unqualified library candidates.

## Revised compatibility direction

The 2026-09-30 usability review changes the proposed architecture, not this
experiment's implementation. ADR-0060 now targets standard language/runtime APIs
beneath unchanged application and transitive dependency code. Developers should
not need to inject an LSF executor or custom transport. LSF-owned runtime/compiler
ports must preserve real scheduling, synchronization, thread identity, per-thread
host waits, timers and API-specific completion behavior within the activation.

Java integration should first evaluate the pinned TeaVM fiber/event machinery
and LSF's currently trapping scheduling hooks. Other languages retain their own
runtime contracts over shared activation ownership. Standard outbound I/O needs
a separately qualified substrate and explicit reconciliation with ADR-0059;
this revision grants no sockets and does not infer protocols from arbitrary bytes.

Library helpers and recurring callbacks may be implementation targets while an
activation is active, but cannot survive its retirement. Idle managed workers
must be distinguished from unfinished work; an opaque waiting thread cannot be
silently discarded as harmless. The eight-task prototype is not the production
concurrency limit or the developer-facing compatibility API. Qualification must
use unchanged real libraries and default paths, not count adapter-assisted cases
as transparent compatibility. The ADR specifies the implementation and review gates.

## Run

Use the repository's pinned Rust 1.97.1 toolchain with `rustfmt` and
`wasm32-unknown-unknown`, wasm-tools 1.254.0, and Python 3.13 on Linux. The driver
uses the existing bounded process-group owner; it is a trusted build recipe,
not a sandbox for hostile builds. Run from the repository root:

```sh
python3 -m unittest discover -s research/invocation-concurrency -p 'test_*.py'
python3 tools/run_invocation_concurrency.py --output /tmp/lsf-concurrency-new-run
```

The output directory must be new, absolute and outside the checkout. The driver
builds four native scope tests, a real Rust core module, a validated component,
and the Wasmtime embedding. It uses the workspace lockfile without adding
runtime dependencies and records actual tool versions, source hashes, tested
commit/dirty status, component digest, bounded logs and a success/failure receipt.
It does not reuse a stale guest inventory or accept missing tools as a skipped
success. Build/runtime failures keep a failed receipt; a new directory is needed
for the next attempt.

The path-filtered `Invocation concurrency research` workflow runs the same recipe
with read-only repository permissions. Its workflow, job and delegated-owner
contracts are committed under `tools/ci/contracts/`; existing jobs and historical
coverage obligations are unchanged. The workflow retains the component, extracted
WIT, logs, receipt and formatting-diagnostic copies on success or failure.

## What is executed and measured

The private `research:concurrency@0.1.0` WIT world is deliberately absent from
production linkers. Generated guest async imports are invoked by real Wasmtime
components. A controlled host wait lets the test observe physical native owner
lifetimes deterministically without a public network, sleep-based readiness
assumptions, or a provider mock standing in for guest execution.

| Case | Required observation |
| --- | --- |
| Sequential host waits | Eight real waits, one outstanding owner at a time, sum 36. |
| Cooperative host fan-out | Eight distinct waits simultaneously pending in one Store, sum 36. |
| Cancel then drain | All eight host operations acknowledge cancellation while still owned; only a separate retirement gate releases them. |
| Denied authority / ninth task | Error results or closed task-limit result before any host dispatch, never fake success. |
| Empty scope / cooperative rendezvous | Empty completion without work; explicit yielding allows another task to initialize shared state. |
| Real `std::thread::spawn` | Unsupported target API traps in the compiled guest. |
| Inline-start rendezvous | Immediate worker execution prevents its caller's initialization; shared fuel terminates it. |
| Root epoch expiry | Controlled root interruption after pending-owner observation; any remaining host futures stay owned until actual Store destruction, never an early reuse proof. |
| Partial error | One error is retained while the other seven operations complete; result remains spawn-ordered and the scope drains. |
| Fresh Store after traps | A new invocation succeeds; the guest's single-entry static guard also checks fresh instance state. |

Each successful receipt records call and Store-drop nanoseconds, shared fuel used,
actual linear-memory reservations/peak, frame creation/poll/drop counters,
maximum simultaneous host-operation owners and ownership at pending/cancellation
checkpoints. CPU comparison uses the same 8 x 256 additions, with versus without
cooperative checkpoints, one discarded warmup pair and seven retained pairs.
The arithmetic result must be 9216 in both variants. Scheduling work is intentionally
extra; this is a descriptive cost experiment, not a production speedup claim.

Native scope tests check rotating poll order, spawn-order errors, all-child drop,
empty join and overflow-before-poll. Python receipt tests reject omitted cases,
serialization disguised as fan-out, early-refund claims, missing/unequal-work
samples and unsupported behavior disguised as success. Their synthetic fixtures
are parser tests, never measured evidence.

## Limitations and interpretation

The eight-task prototype is a stackless cooperative join, not a preemptive
scheduler. A non-returning poll can starve siblings until root fuel/deadline
containment stops it. The ten-second outer watchdog fails the experiment; it
is not cancellation success or a reusable-cell proof.

Linear memory is measured through Wasmtime's limiter, including rollback of failed
growth observations. The 256 KiB configured Wasm call-stack limit is not a measured
native stack/heap total. `hostOperationStructBytes` excludes the Arc allocation,
Wasmtime fibers and runtime internals. Native allocator peak, RSS attribution,
production admission/cell accounting, signed-node execution and real provider
uncertain-effect behavior are not qualified by this embedding. Those remain
explicit promotion gates in the ADR. The private allow/deny flag tests the fixture's
authority boundary, not the production broker's complete policy enforcement.

The experiment introduces no invocation timer API, recurring timer or detached
work. Go, Java, C, JavaScript and .NET are inventoried separately; this Rust
component cannot certify their continuation lowering or library compatibility.
The durable timer/workflow boundary remains outside this work.

## Evidence

Consult [retained evidence](evidence/README.md) for immutable run identities,
results and limitations. A `status: passed` receipt requires every component case
and complete comparison samples. Presence of the prototype, a build-only run,
a failed receipt or a native/Python test result alone does not meet that condition.

The usability revision leaves executable sources and original receipts unchanged.
The runner hashes selected Rust/WIT/Python and build inputs, not ADR prose, and
records the actual tested checkout. Historical passing execution does not qualify
the revised standard-runtime design, automatic checkpointing, timers or unchanged
third-party libraries. New runtime work needs its own source-bound execution evidence.

## Requirement map

| #695 requirement | Review location / executable coverage |
| --- | --- |
| Six runtimes and six distinct concurrency dimensions | `languages.md`, pinned baseline, upstream source findings and separate target labels. |
| Sequential, adapter, cooperative, component-task and provider alternatives | ADR alternatives table; standard-runtime ports are the revised default, adapters optional. |
| Scope ownership, task/stack/heap/queue/timer caps and shared limits | ADR resource-accounting contract; experiment-only numeric limits; `scope.rs`, `memory.rs`, root fuel/epoch tests. |
| Fairness, blocking, nested progress and no fake Thread.start | Existing native round-robin and component deadlock/trap cases; ADR separately requires compiler checkpoints, standard synchronization and real-node progress. |
| Identity, capability and detached-work boundary | Private linker checkpoints/denial; unchanged production linkers; ADR activation-local helpers, generation fencing and physical retirement. |
| Invocation timers versus durable work; no second budget ledger | ADR timer and lifecycle sections; no timer/worker production code in this PR. |
| Bounded actual-component proof and measurements | `guest.rs`, `host.rs`, source-bound runner, required-case receipt validation and retained evidence. |
| Per-language implement/defer/reject decision and narrow follow-ups | ADR implementation matrix and five conformance gates; unchanged published libraries and default paths are required for new compatibility claims. |
