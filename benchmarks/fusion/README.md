# Call-graph fusion benchmark specification

**Status: specified, not implemented or measured.** The
[configuration](benchmark.toml) remains design metadata; there is no fusion
runner or execution receipt here. Read the [research track](../../research/call-graph-fusion/README.md),
its [semantic gates](../../research/call-graph-fusion/evaluation-plan.md) and
[primary-source review](../../research/call-graph-fusion/upstream-review.md).
This document does not authorize a load or soak run.

## Compared execution paths

Use real Wasmtime components, current catalog/bindings, broker, required audit,
admission, scheduler and node-owned cleanup. The ordinary baseline already has
local in-process calls, compiled capability plans and prepared-code reuse.
Do not substitute an HTTP/container chain or repeatedly uncached generic lookup.

| Path | Required interpretation |
| --- | --- |
| Ordinary local calls | Separate fresh child activations and Stores with normal cells, policy/currentness, budgets, results and cleanup. |
| Joint preparation / plan specialization | Preserve those boundaries and compare incremental preparation/dispatch savings. Label as specialization, not measured guest fusion. |
| Actual composite candidate | Record generated artifact/adapters and exactly which boundaries are retained, virtualized or changed. Run the semantic matrix before reporting equivalent performance. |
| Direct monolithic reference | Optional reference with fewer logical boundaries and a different service-call contract; cannot establish an equivalent fusion speedup. |

Start with two- and three-member serial chains and a small fixed computation.
Vary boundary/compute ratio and bounded payload size separately. Include repeated
callee calls, handled failures and an untaken branch. Transaction graphs,
cross-tenant fusion, fan-out/join and language-runtime generalization are outside
the initial candidate; add them only through separately defined semantics.

## Required metrics and definitions

Retain the original metric names, with explicit populations and units:

| Metric | Definition and qualification |
| --- | --- |
| `unfused_p99_micros` | End-to-end per-request latency quantile for the declared ordinary-path population, arrival model and outcome class. Include queue/preparation time in the declared boundary. |
| `fused_p99_micros` | Same measurement for an actual semantically qualified composite. Leave unavailable for an unimplemented path; do not copy specialization or monolith results into this field. |
| `serialization_bytes_saved` | Measured difference in bytes actually encoded/decoded at named boundaries. Report copied bytes separately. Preserve guest-observable payloads, codec rules and audit inputs; a typed connection does not imply zero serialization. Negative savings are possible. |
| `compile_micros` | Measured candidate construction wall time, with composition/adapter generation, validation and native compilation broken out. Report CPU separately for amortization; an immutable-cache hit is not compilation. |

Additionally record per-phase preparation/linking, fresh Store/instance creation,
broker/currentness/audit, child admission, value conversion, guest work, waits,
result lowering and physical teardown. Record counters without double-counting
nested spans: root wall time and summed guest/host CPU are different measures.
Do not add component p99 values to derive end-to-end p99.

Report throughput, full request/outcome counts, admission rejection and error
rates, queue/wait distributions, CPU, cells/active Stores, retained result and
ledger ownership, image/index bytes, committed memory, RSS and post-retirement
residency. Successful latency alone can hide a candidate that rejects more work.
Report all attempts and successful/error cohorts explicitly rather than dropping
failures as outliers.

## Cache states and workload variants

Keep cold artifact, warm raw artifact, warm authenticated AOT and warm prepared
code variants where supported. Treat the capability-plan cache and proposed
composite cache as separate dimensions. State exactly which member images,
plans and candidate are warm. An AOT/prepared hit never means a warm mutable
guest instance. Both paths receive equivalent cache preparation and controls.

Measure success, bounded rejection, cancellation and cleanup paths. Include
publication/policy/binding changes, member-version churn and forced cache/build
budget pressure. Count invalidated/abandoned builds, retained member images and
duplicate composite code. Later mixed-load campaigns must measure competing
tenant fairness and capacity effects; a one-cell candidate cannot borrow the
ordinary path's admission claim.

## Sampling and reproducibility

The existing `iterations = 30` and `warmup_iterations = 5` do not specify request
count, arrival process, quantile method or confidence. Before a campaign, declare
requests per run, duration, warm-up exclusion, open/closed-loop load, concurrency,
CPU placement and resource limits. Choose sample sizes suitable for the tail
being estimated and retain per-request samples or sufficient histograms.
Repeated batch count alone is not a p99 methodology.

Use paired, interleaved/repeated baseline and candidate trials with controlled
fixtures and the same functional/negative checks. Preserve per-run distributions
and describe uncertainty; do not average batch p99s into a purported global p99.
Report generator lag and coordinated-omission treatment for the arrival model.
Separate cold preparation, optimizer convergence and steady-state measurements.

Receipts must bind source, member/publication/binding/policy inputs, generated
artifact and adapter hashes, toolchain/runtime/target/security identities,
capacity/metering model, cache states, load configuration and raw result/log
digests. A source revision, registered case or successful build is not execution
evidence. Retain failed trials and resource owners through actual retirement.

## Amortization and decision

Compute total CPU saved over uses of the exact still-valid candidate, minus
observation, build and maintenance CPU. Candidate per-request CPU must already
include its guards; do not subtract those costs twice. Count churn and discarded
builds, and keep CPU and wall-time terms separate. Version/policy changes can
end the useful lifetime before a candidate breaks even.

Compare retained memory and capacity as well as latency. A larger artifact,
slower cold start, extra guard work or fairness regression can outweigh a warm
path gain. Publish the defined contract, gains, regressions and remaining gaps.
No LSF fusion performance result exists until the corresponding paths and
semantic controls have actually run.
