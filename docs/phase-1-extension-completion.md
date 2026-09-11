# Phase 1 extension: measured results and Phase 2 handoff

**Extension status: COMPLETE — September 11, 2026.**

The prioritized Phase 1 optimizations and Docker/Kubernetes comparisons are merged. This report records their measured results, remaining limits and handoff to Phase 2 packaging and supply-chain feature delivery. It supplements the original [functional Phase 1 completion](phase-1-completion.md), whose decision and receipts remain unchanged. The extension delivered useful-success, recovery, ownership and catalog improvements, with material latency and memory costs. It does not establish a universal service SLO.

Every comparison uses its report's actual control/candidate source, binaries, configuration and population. The [#98 reference](../benchmarks/optimization/reference/2026-09-08-container-linux-8bbc1fd/REPORT.md) retained 88,326 offers; its separate [rejected predecessor](../benchmarks/optimization/diagnostics/2026-09-08-container-linux-7857e6c/REPORT.md) remains failed evidence. Neither merged commit identities nor later medians replace measured sources. Percentages are not additive; campaigns are not pooled into synthetic repetitions.

| Delivered work and original evidence | Measured benefit | Cost or boundary retained |
| --- | --- | --- |
| [#99 artifact identity](../benchmarks/optimization/artifact-identity/2026-09-08-container-linux-95a53b1/REPORT.md) | 64 MiB artifact recovery: 309.282 → 53.012 ms; profiled heap peak: 128.114 → 0.120 MiB. | Padded component bytes and warm filesystem conditions; no cold-disk or invocation-tail claim. |
| [#100 warm acquisition](../benchmarks/optimization/warm-activation/2026-09-08-container-linux-56303c5/REPORT.md) | Echo p50/p99: 0.888/1.854 → 0.579/1.366 ms. | Five-component/four-slot refill p99: 41.936 → 54.783 ms. |
| [#101 cold preparation](../benchmarks/optimization/cold-preparation/2026-09-08-container-linux-368d621/REPORT.md) | Warm successful p99 during distinct cold work: 70.824 → 1.824 ms. | Bounded admission completed 28/35 distinct cold calls versus 35/35; fresh RPC and RSS increased. Less work is not faster matched compilation. |
| [#102 prepared cache](../benchmarks/optimization/prepared-cache/2026-09-09-container-linux-7e03a2f/report.md) | Hit allocation: one/14 B → zero; real-node warm p50: 0.725 → 0.709 ms. | Lookup is not a complete Invoke; churn timing and RSS remain mixed. |
| [#103 budgets](../benchmarks/optimization/precise-budgets/2026-09-09-container-linux-e25b609/README.md), [#119 transport cleanup](../benchmarks/optimization/transport-cleanup/2026-09-09-container-linux-ee10b02/README.md) | At 2 ms, useful success: 2,634/2,800 → 2,794/2,800. Disconnect-recovery follow-ups: 5/30 → 30/30 without restart. | No useful 1 ms service; native interruption still produces response overshoot. Failed diagnostics remain separate. |
| [#104 request ownership](../benchmarks/optimization/request-ownership/2026-09-09-container-linux-2bd2452/README.md) | Live pending Store retains zero raw-vector capacity versus 65,536 B; near-limit context setup: 53.5 → 33.5 µs. | Warm Echo paired p50 +37.451 µs; server batch CPU +5.7%. All 12 selected attributions unavailable. |
| [#105 typed codec](../benchmarks/optimization/typed-codec/2026-09-09-container-linux-9a2749f/README.md) | Warm Echo paired p50 −20.002 µs; six decode families reduced selected allocations. | 64 KiB p50 +13.713 µs; compute p99 +15.247 µs; higher RSS and slower near-limit/escaped decode. Encoder allocations unchanged. This does not erase #104's cost. |
| [#106 engine profiles](../benchmarks/optimization/engine-profiles/2026-09-09-container-linux-fbb6e26/README.md) | Pooling/speed setup p50 reduced 16–29 µs; separate default external paired p50 −13.0635 µs. | Pooling increased cold compilation, RSS and image charges. Default external p99 +28.086 µs; separate matrix Echo p50 +5.8935 µs. Keep on-demand/speed default. |
| [#107 catalog memory](../benchmarks/optimization/catalog-memory/2026-09-10-container-linux-96716c8/README.md) | Distinct 100k post-apply RSS: 2.718 → 1.117 decimal GB, **58.90% lower**. | Shared RSS fell only 14.19%, to 2.504 GB; shared resolver tails worsened and weight update +24.53%. Reopened/high-water RSS exceeds the idle target. |
| [#108 catalog mutations](../benchmarks/optimization/catalog-mutations/2026-09-11-container-linux-15f3fba/README.md) | All 24 mutation observations faster, 35.7–69.1% less elapsed; encoders two → one, preserving fresh integrity checks and full-file writes. | Shared 10k reopen +41.52%; distinct reopened idle RSS +18.75%. Selected reopen attribution and exact scratch peaks unavailable. |
| [#109 scheduler queues](../benchmarks/optimization/scheduler-queues/2026-09-11-container-linux-77c0715/README.md) | Observed cancellation scans/shifts eliminated; final cancellation owners retire outside the mutex. | Eight-tenant settlement p50: 30.0755 → 42.6785 µs, **about 42% worse**. Saturated T32 released p99: 165.815 → 179.116 ms. Selected allocations unchanged: 224 / 21,760 B / 20,992 B peak. |

The declared #103 resident Echo case met ≥99% useful success at 2 ms: **99.7857%**, with one outstanding request. Its successful p50/p99, 0.589/1.372 ms, also meet the ≤1/≤2 ms numerical latency thresholds. Six candidate offers missed useful success: two transport failures and four late successes. Both arms achieved 2,800/2,800 on-time successes at 5 and 10 ms; both achieved zero at 1 ms. Preserve deadline misses, late responses and overshoot separately. #107 met the ≥25% reduction and ≤1.75 decimal GB distinct-catalog target, not an all-shape or peak ceiling.

The [actual Docker comparison #111](../benchmarks/optimization/docker-comparison/2026-09-11-container-linux-a56a6dc/README.md) completed 300 smoke and 9,926 full offers, all successful; all 48/318 containers were removed. Native beat LSF in every headline warm latency/throughput pair. D1 Echo C1 native/LSF p50 was 0.370/0.813 ms, p99 0.770/1.695 ms; LSF compute p99 was 2.014 ms and C4 Echo p99 2.326 ms. Thus the latency thresholds do not hold across workloads/concurrency. One-second budgets do not retest the 2 ms useful-success target.

At D32, final native/LSF leaf-cgroup memory was 61.098/14.625 MiB; D1 favored native. LSF brought dense cohorts ready sooner, with cached images and sequential native creation. Equal aggregate 4-CPU/2-GiB budgets were partitioned across native containers but pooled by LSF. The native feature stack is smaller. Warm-interval CPU includes observation, idle and management work; it is not pure CPU per successful handler. RSS, cgroup charge and allocation peaks are distinct. This Docker Desktop/WSL2 experiment does not isolate orchestration overhead or establish cloud capacity.

## Kubernetes #112

The [actual Kubernetes comparison](../benchmarks/optimization/kubernetes-comparison/2026-09-11-container-linux-8b0441f/README.md) completed **9,926/9,926 successful full offers**, seven pairs, 42 groups, 308 application Pods and seven persistent clients. Revised-protocol smoke04 passed 300 separately. Full source `8b0441fb5b052c7b103f55a4f2ab2e72b5a4add5` reused the exact #111 image/executable build `e68c47ab9e9e69e8d28b3f8e2077ea45fa4776ee`. Full aggregate SHA256 is `f27538c151edb685722a645764861ab1254e68fec1f6c1f96057563cbff921d6`; complete full-run offline replay passed in 56.178434576 s with original suite/API hashes unchanged. The initially failed offline comparison receipt remains retained; correcting its timing-metadata equality did not rerun the workload.

Native had lower warm p50/p99 and higher response throughput in **7/7 pairs for all five headline workloads**. D1 Echo C1 native/LSF p50 was 0.356/0.738 ms and p99 was 0.801/1.458 ms. LSF traded slower calls for less dense-cohort leaf memory: final D32 native/LSF was 57.711/14.098 MiB, while D1 was 1.918/8.168 MiB and favored native. D32 create-to-forwarding-ready bounds were 9.975/3.217 s and first-response upper bounds 29.849/4.244 s; dense LSF cohorts were lower in 7/7 pairs, but D1 forwarding/first-response was higher in 6/7. Startup/route checks, connections, cohort provisioning and 250 ms barriers remain in those lifecycle costs.

Cross-platform directions were mixed. LSF generally had lower warm latency and higher throughput than its original Docker campaign, but native D1 Echo p99 rose by paired 0.063 ms (5/7 higher). Native D8 p50 rose by paired 0.004 ms (4/7 higher) even though its displayed Kubernetes arm median was lower. Same-index observations come from separate campaigns, not randomized platform pairs; their differences do not isolate ClusterIP or orchestration cost.

Requested application budgets matched 4 CPU / 2 GiB, but every native D32 cohort actually enforced **4.16 CPUs versus LSF 4.0**, reflecting 130m per Pod versus 125m requested. This is permitted capacity, not measured usage, and the report does not claim exact effective CPU parity. Native partitions resources while LSF pools them; native also has fewer runtime responsibilities. Warm-interval CPU includes wrapper, management, observation and idle work, so its dense-cohort reduction is not pure CPU per successful handler. Child/wrapper RSS, leaf charge and outer-node memory are separate; CRI client working set differs from Docker usage.

The earlier TCP-probe smoke03 completed all 300 offers with its original cleanup warning and explicit seven-call zero-Invoke cleanup completion; it remains a completed prior smoke. Failed smoke01/02 and full01 remain separate, including the five-group/1,130-offer incomplete full prefix and its recovery. Revised exec-ready-record startup used unchanged images. All measured full02 ownership/namespace/data cleanup passed; the owned cluster and both private credential copies were physically removed with original receipts. This ordinary local kind/containerd/WSL2 benchmark does not implement HA, production cluster control or future-phase supply-chain features.

The Kubernetes warm arm medians fall below the 1 ms p50/2 ms p99 numerical thresholds in these five cases, but under 1 s request budgets. This does not qualify 99% useful success with an actual 2 ms deadline, every-pair tail compliance or a universal SLO. The 128,227,164 B Kubernetes archive has SHA256 `30b81cef5129286510e8994b5bcb3c6ec8236c50b1eebb0686ffc25afb9dfc1e`; Linux packaging and complete semantic replay passed in 160.162756058 s, including compression, using publication validator `10d50e61c5632ea2361a16dffc3b4819987f4dc4`. Independent Windows package replay passed in 439.2165928 s, with unchanged package bytes and exact Linux/public copy equality. The separate original Docker dependency remains required and is restored as described below. [PR133](https://github.com/KirilsTurkins/latent-service-fabric/pull/133) merged on September 11, 2026 at 19:39:58 UTC as `5e00d53d28aa417aabd4e70a311e52b3d0ad936f`, after all six required CI checks passed on reviewed head `a3df4ef8612abb955c2d6282a8ee8bd0be13ec18`. These delivery revisions are separate from the measured collector, image build and publication validator above.

## Retention and replay

The [compact retention policy](testing/benchmark-retention.md) preserves reports, paired results, provenance and historical replay receipts. Its publication update records 24 compacted packages or diagnostic bundles in the [ledger](../benchmarks/optimization/retention.json): 60 removed payload files totaling 2,438,191,603 B. This includes only the four raw #111 parts (169,803,211 B); the Docker report, tables and manifests remain. The complete #112 package is retained within the 600 MiB benchmark budget. Complete historical packages remain restorable from storage commit `a432c51f9ed0a4eaf55473d80122bbb8e5a419cf`; those storage bytes do not change any measured source. A historical replay PASS is not a fresh replay of this compact checkout. Restore only the exact Docker dependency before replaying #112; no wholesale historical restoration is needed:

```sh
set -euo pipefail
storage_commit=a432c51f9ed0a4eaf55473d80122bbb8e5a419cf
docker_package=benchmarks/optimization/docker-comparison/2026-09-11-container-linux-a56a6dc
restored_root=../issue112-docker-reference
git cat-file -e "$storage_commit^{commit}" 2>/dev/null || \
  git fetch --filter=blob:none --depth=1 origin "$storage_commit"
mkdir -- "$restored_root"
git archive --format=tar "$storage_commit" "$docker_package" | tar -xf - -C "$restored_root"
python3 tools/validate_phase1_archive.py \
  benchmarks/optimization/kubernetes-comparison/2026-09-11-container-linux-8b0441f \
  --docker-package "$restored_root/$docker_package"
```

## Tuning and closure

Use the following measured limits when choosing a configuration:

- Keep the on-demand/speed default unless repeated fresh instantiation justifies the measured pooling costs in cold compilation, RSS and image charge. Speed-and-size did not reduce these fixtures' image charge.
- Size bounded prepared caches for the active component working set. Dormant deployment count does not determine code-cache capacity; evicted entries can remain owned by in-flight work, and old catalog pins extend generation lifetime. A larger cache is not a larger cell pool.
- Keep finite cell and queue admission. Cold preparation, queued work, transport/admission and cleanup need separate headroom inside the caller's original budget. Fast rejection is not useful success; neither 1 s benchmark budgets nor warm percentiles establish a 2 ms completion guarantee.
- Preserve caller activation identity for status and explicit cancellation. Cancellation acceptance, a dropped local wait and completed native cleanup are different observations. Do not automatically retry an unknown outcome; no SDK transport or retry policy is added by the benchmark client.

The scheduler retains its within-tenant winner scan and bounded arena high water; catalog idle reductions do not establish an all-shape or peak memory ceiling. Keep these rules consistent in [architecture](architecture/execution-cells.md), [operations](operations/topology.md), [CLI](reference/operator-cli.md), [SDK identity/cancellation semantics](../sdk/README.md) and [client/measurement guidance](testing/phase-1-measurements.md).

The linked reports retain exact denominators, working sets, fairness curves, CPU boundaries, unavailable fields, failed attempts and archive replay commands. Process medians differ from pooled samples; #107–109 single-pair cases are descriptive. Delivery and closure status are recorded in [extension gate #113](https://github.com/KirilsTurkins/latent-service-fabric/issues/113), [epic #97](https://github.com/KirilsTurkins/latent-service-fabric/issues/97) and the [Phase 1 extension milestone](https://github.com/KirilsTurkins/latent-service-fabric/milestone/5). The already-met #103/#107 targets remain scoped to their historical matched populations; no integrated post-extension 2 ms budget campaign is implied. Unmet 1 ms useful work, all-shape RSS and adverse tails remain explicit limitations under the revised gate. #110 is **closed/not planned**. The next work is Phase 2 packaging and supply-chain feature delivery, following the [ROADMAP](roadmap.md). A benchmark cluster does not implement later-phase cluster control. No further optimization cycle is required to remove every regression.

The final report [PR #134](https://github.com/KirilsTurkins/latent-service-fabric/pull/134)
merged into `development` on September 11 as
`57742511d8db6a1a3491d3c5253140b933ae8ea6`, after all five required CI checks passed
on reviewed head `96a5217656bdffb431caa11cb5d6514ef4a1fe5f`. Tickets #112/#113 and epic
#97 are closed as completed; the extension milestone is closed with zero open
issues. This delivery receipt does not change any campaign's measured source or
performance qualification.
