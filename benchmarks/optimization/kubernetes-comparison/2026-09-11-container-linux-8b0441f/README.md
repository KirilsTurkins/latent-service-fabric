# Kubernetes comparison: native services and LSF

Native returned requests faster in every headline warm workload: all seven pairs favored native for successful p50, p99 and response throughput. LSF used less application-cohort memory at eight and 32 services and reached dense-cohort forwarding readiness sooner. At one service, LSF used more memory and its first-response lifecycle bound was usually longer. These are results for the tested deployment topology and workloads, with an explicit resource difference: the native D32 cohort had a **4.16 CPU effective ceiling**, versus **4.0 CPUs for LSF**, despite matching requested resources.

The full run returned **9,926 successful responses from 9,926 offers**, with zero semantic mismatches, undispatched offers or request-budget misses. It comprised **574 first-per-service, 2,576 warmup and 6,776 measured calls**, across seven pairs, 42 groups, 308 application Pods and seven persistent client Pods. The separate revised-protocol smoke04 passed all 300 offers. Full collection covered **1,544.443047972 s** from the suite's own boundaries; the outer command took **1,546.5409368 s**. These spans include setup, observations and cleanup, not just request execution.

D is service density and C is client concurrency. Unless the Docker/Kubernetes contrast says otherwise, tables show **native / LSF**. Each arm value is the **median of seven pair-level metrics**. Parentheses contain the **median of the seven paired LSF-minus-native differences**, formed before summarizing; it need not equal the difference between displayed arm medians. Successful p50/p99 exclude no successful outliers, but remain conditional on success. First calls, warmup and measurement stay separate. Every headline/resource comparison shown has all seven pairs available. The [aggregate](aggregate.json) and [16 CSV tables](tables.manifest.json) retain individual pairs, signs, spread, execution order and unavailable fields. Seven pairs are descriptive, not a universal capacity or latency guarantee.

Both arms used the exact original [Docker comparison](../../docker-comparison/2026-09-11-container-linux-a56a6dc/README.md) images, shared business functions, authentication, protobuf/payload framing and persistent client. One LSF Pod hosted D component services; native used D Pods with one service each. Each arm exposed D ordinary IPv4 ClusterIP Services, reaching one actual ready endpoint per Service on the owned worker. The wrapper remained PID1 in each application container and forwarded to its loopback child; it was not another sidecar. Client traffic used the Service path, without port-forward, NodePort or a Windows request hop.

Requested application resources totaled **4 CPUs and 2 GiB**, including wrappers. Native partitioned these across D Pods; LSF pooled them across four cells. At global C4, requests cannot borrow idle native partitions. D1/D8 actual CPU totals matched 4.0; every full D32 native cohort enforced 130m per Pod rather than 125m requested, totaling 4.16 (+4%). This is a cap difference, not measured CPU usage or a generic rounding tolerance. Ordinary runc was retained. Pod PID limits, runtime-default FD limits and tmpfs mount flags are recorded separately from Docker's controls; only declared CPU/memory budgets were matched. The client had its own 2 CPU / 256 MiB allocation and two workers. LSF kept queue 64, prepared cache 32 and catalog 64, with 1 s request budgets and 5 s connect/outer response bounds.

Native implements the same workload function and transport, but lacks LSF's Wasm isolation, fuel/guest-memory enforcement, catalog/routing, preparation and retained activation lifecycle. The difference is therefore not pure Kubernetes overhead. The pinned cluster had one control-plane node and one worker, Kubernetes/kubelet **v1.36.4**, containerd **2.3.4**, Debian13 and WSL2 kernel **6.6.87.2-microsoft-standard-WSL2**, inside Docker Engine **29.7.2**. Its node image was `sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed`. The control-plane outer container was bounded to 2 CPU / 4 GiB, worker 8 CPU / 12 GiB, both without added swap allowance. This single-host Docker Desktop/WSL2 deployment is not cloud, HA, multi-host or production Kubernetes validation.

The warm measurements were:

| Workload | p50 ms | p99 ms | responses/s |
| --- | --- | --- | --- |
| D1 Echo C1 | 0.356 / 0.738 (+0.384) | 0.801 / 1.458 (+0.716) | 1,831.938 / 1,017.142 (-807.972) |
| D1 compute C1 | 0.378 / 0.834 (+0.454) | 0.948 / 1.582 (+0.634) | 1,731.857 / 929.031 (-807.776) |
| D1 Echo C4 | 0.419 / 0.913 (+0.496) | 0.841 / 1.841 (+1.117) | 7,044.444 / 3,568.764 (-3,390.044) |
| D8 density Echo C4 | 0.344 / 0.923 (+0.579) | 0.551 / 1.800 (+1.273) | 7,834.398 / 3,495.045 (-4,526.502) |
| D32 density Echo C4 | 0.366 / 0.921 (+0.559) | 0.591 / 1.895 (+1.301) | 7,434.522 / 3,462.133 (-3,906.800) |

Native had lower p50/p99 and higher throughput in **7/7 pairs for every row**. D1 measured Echo C1/C4 used 128 offers per arm/pair and compute 64; D8/D32 density used 32/128. The additional four-offer D1 density phase remains in [phase rows](phase-rows.csv). Throughput spans first scheduled offer through last completion; phase-span throughput, all-dispatched latency, all-offered elapsed and dispatch lag remain separately retained in [paired comparisons](phase-comparisons.csv).

First-per-service calls occurred before warmup:

| D | p50 ms | p99 ms |
| --- | --- | --- |
| 1 | 0.885 / 38.619 (+37.778) | 0.885 / 38.619 (+37.778) |
| 8 | 0.575 / 37.593 (+37.080) | 0.929 / 43.616 (+42.548) |
| 32 | 0.541 / 34.922 (+34.357) | 0.962 / 53.105 (+52.143) |

Native was faster in all seven pairs. D1 has one first call per arm/pair, so its within-pair p50 and p99 are the same observation. These calls do not isolate compiler, instantiation or transport cost.

The parent-clock lifecycle bounds begin at the first application Pod create request:

| D | create -> graph ready s | create -> forwarding ready s | create -> first response observed s |
| --- | --- | --- | --- |
| 1 | 2.371 / 2.090 (-0.196) | 2.474 / 2.647 (+0.172) | 3.518 / 3.676 (+0.192) |
| 8 | 3.505 / 1.931 (-1.615) | 3.622 / 2.498 (-1.091) | 8.866 / 3.642 (-5.395) |
| 32 | 9.843 / 2.849 (-6.992) | 9.975 / 3.217 (-6.747) | 29.849 / 4.244 (-25.333) |

LSF's D8/D32 graph readiness, forwarding readiness and first-response bounds were lower in 7/7 pairs. D1 was mixed: graph readiness lower 4/7, but forwarding readiness and first-response observation higher 6/7. Graph readiness and the worker's observed forwarding rules are different boundaries. The successful protocol used a bounded exec startup check of the wrapper's original ready record, with no TCP startup connection or guest Invoke; read-only iptables observations checked Service-to-Pod routing before the client connected. There was no ongoing readiness/liveness probe.

These are **image-present observed upper bounds**, including cohort submission/scheduling, startup checks, route observation, client channel setup and applicable 250 ms barriers. Kubernetes submitted a cohort before waiting, while original Docker provisioned native containers sequentially. The bounds are not image pull time, ideal cold invocation or isolated orchestration delay. All owner/Pod associations and timing boundaries remain in [lifecycle owners](lifecycle-owners.csv), [cohorts](lifecycle-cohorts.csv) and [paired comparisons](lifecycle-comparisons.csv).

Memory followed three requested 250 ms idle windows: ready before any call, served after first-per-service calls, and final after warmup/measured phases. Each application leaf cgroup is counted once, including child and wrapper:

| D | ready MiB | served MiB | final MiB |
| --- | --- | --- | --- |
| 1 | 1.691 / 2.723 (+1.035) | 1.750 / 5.215 (+3.449) | 1.918 / 8.168 (+6.227) |
| 8 | 13.562 / 3.348 (-10.219) | 14.070 / 7.312 (-6.758) | 14.418 / 8.633 (-5.785) |
| 32 | 54.238 / 5.090 (-49.145) | 56.480 / 12.680 (-43.684) | 57.711 / 14.098 (-43.652) |

LSF was higher at D1 and lower at D8/D32 in all seven pairs at every stage. The separate final process RSS observations were:

| D | application children MiB | wrappers MiB |
| --- | --- | --- |
| 1 | 4.500 / 23.801 (+19.227) | 3.750 / 3.750 (+0.000) |
| 8 | 35.375 / 23.809 (-11.543) | 29.125 / 3.875 (-25.125) |
| 32 | 141.875 / 28.043 (-113.914) | 116.250 / 4.250 (-111.875) |

RSS can double-count shared pages and is not PSS. Process RSS, leaf cgroup usage, Pod ancestors and outer node memory must not be added as unique physical memory. Summed leaf lifetime peaks are not simultaneous cohort peaks; exact within-request memory peaks were not measured. [Resource points](resource-points.csv) retain all six snapshots per owner and availability; [resource comparisons](resource-comparisons.csv) retain all paired results.

Warm-interval application-plus-wrapper CPU was derived within each actual cohort: final.after minus served.after cumulative `cgroup.cpu.usage_usec`, divided by all warmup and measured offers:

| D | offers/arm/pair | native / LSF us/offer (paired delta) | paired delta range us/offer |
| --- | --- | --- | --- |
| 1 | 348 | 269.876 / 735.687 (+470.060) | +419.158 to +510.149 |
| 8 | 64 | 2,505.141 / 983.719 (-1,530.953) | -1,682.609 to -1,145.016 |
| 32 | 256 | 2,706.082 / 710.480 (-1,991.453) | -2,040.457 to -1,894.664 |

LSF was higher at D1 and lower at D8/D32 in all seven pairs. This interval includes wrappers, warmup, measured work, final inventory, snapshots and idle/barrier overhead. Native density cohorts include D wrappers and observations; this can dominate the small 64/256-offer populations. No idle CPU is subtracted, and this is not isolated CPU per successful handler. [Idle-window observations](idle-windows.csv) and [comparisons](idle-window-comparisons.csv) retain their own actual brackets.

Client CPU, which includes its validation/output and barriers, was higher for LSF in every pair:

| D | ready -> final ms | served -> final ms |
| --- | --- | --- |
| 1 | 111.597 / 129.798 (+20.462) | 110.101 / 127.293 (+19.249) |
| 8 | 20.649 / 29.396 (+8.240) | 15.327 / 20.449 (+5.246) |
| 32 | 76.881 / 104.811 (+25.908) | 59.470 / 76.221 (+16.393) |

LSF barriers include the prescribed GetNode RPCs; native barriers issue none. CRI counters can be cached and CPU/memory timestamps can differ or repeat. The exited client's final sample is unavailable, not zero. Its reported working set is not the same metric as Docker's memory usage. [Client points](client-resource-points.csv), [intervals](client-intervals.csv) and [paired CPU](client-cpu-comparisons.csv) preserve those boundaries. Separate child-versus-wrapper CPU and exact controller-attributed cost are unavailable.

The fixed cluster has its own substantial footprint. These individual before/after idle observations are shown separately from the application cohorts:

| window | node role | actual parent span s | observed CPU delta ms | memory before / after MiB |
| --- | --- | --- | --- | --- |
| before | control-plane | 0.268 | 75.215 | 1,288.438 / 1,287.160 |
| before | worker | 0.267 | 7.554 | 744.852 / 744.820 |
| after | control-plane | 0.266 | 27.025 | 1,358.020 / 1,358.758 |
| after | worker | 0.267 | 2.482 | 860.074 / 859.816 |

Outer-node usage includes inner Pods and shared node/control-plane services. It is not additive with leaf usage, and these brackets are not seven-pair application comparisons or background-subtracted overhead. [Node points](node-resource-points.csv) and [intervals](node-resource-intervals.csv) retain observations throughout the campaign. [CPU-cap cohorts](cpu-limit-cohorts.csv) separately retain requested 4.0 CPU and actual 4.16 CPU native D32 limits.

The next table compares each arm with its original Docker campaign. Here cells read **Docker / Kubernetes (median Kubernetes-minus-Docker paired difference; lower/equal/higher counts)**:

| arm / workload | p50 ms | p99 ms | responses/s |
| --- | --- | --- | --- |
| native / D1 Echo C1 | 0.370 / 0.356 (-0.029; 6/0/1) | 0.770 / 0.801 (+0.063; 2/0/5) | 1,784.726 / 1,831.938 (+113.288; 1/0/6) |
| native / D1 compute C1 | 0.411 / 0.378 (-0.041; 6/0/1) | 1.036 / 0.948 (-0.034; 4/0/3) | 1,586.402 / 1,731.857 (+131.373; 1/0/6) |
| native / D1 Echo C4 | 0.417 / 0.419 (-0.002; 4/0/3) | 1.052 / 0.841 (-0.288; 6/0/1) | 6,273.583 / 7,044.444 (+217.970; 1/0/6) |
| native / D8 density Echo C4 | 0.386 / 0.344 (+0.004; 3/0/4) | 0.578 / 0.551 (-0.098; 5/0/2) | 7,284.875 / 7,834.398 (+441.167; 3/0/4) |
| native / D32 density Echo C4 | 0.425 / 0.366 (-0.059; 6/0/1) | 0.903 / 0.591 (-0.307; 6/0/1) | 6,559.785 / 7,434.522 (+946.752; 1/0/6) |
| lsf / D1 Echo C1 | 0.813 / 0.738 (-0.068; 6/0/1) | 1.695 / 1.458 (-0.192; 7/0/0) | 919.865 / 1,017.142 (+95.628; 0/0/7) |
| lsf / D1 compute C1 | 0.992 / 0.834 (-0.131; 7/0/0) | 2.014 / 1.582 (-0.550; 6/0/1) | 790.804 / 929.031 (+119.674; 0/0/7) |
| lsf / D1 Echo C4 | 1.032 / 0.913 (-0.078; 7/0/0) | 2.326 / 1.841 (-0.331; 7/0/0) | 3,184.139 / 3,568.764 (+335.678; 0/0/7) |
| lsf / D8 density Echo C4 | 1.043 / 0.923 (-0.184; 7/0/0) | 2.461 / 1.800 (-0.323; 6/0/1) | 2,990.390 / 3,495.045 (+760.440; 0/0/7) |
| lsf / D32 density Echo C4 | 1.018 / 0.921 (-0.135; 7/0/0) | 2.265 / 1.895 (-0.473; 5/0/2) | 3,136.457 / 3,462.133 (+427.162; 0/0/7) |

LSF's p50 decreased in 6/7 or 7/7 pairs, p99 in 5/7 to 7/7, and throughput increased in 7/7 for every headline workload. Native was mixed: D1 Echo p99 increased in 5/7 pairs, with a paired +0.063 ms change; D8 p50 increased in 4/7, with paired +0.004 ms, despite the lower displayed Kubernetes arm median. Retain those adverse comparisons. Matching pair indices across separate campaigns is descriptive; it is not a randomized platform treatment. Scheduler/runtime/CNI, startup/observation, native partitioning and the effective D32 CPU difference remain in the contrast. [Platform comparisons](platform-comparisons.csv) retain all other shared metrics and every pair.

The displayed Kubernetes LSF warm arm medians fall below 1 ms p50 and 2 ms p99 in these five cases. These are medians of conditional successful per-pair quantiles under 1 s budgets; they do not establish 99% success with an actual 2 ms request budget, every-pair tail compliance, or a universal service SLO.

The measurement/build identities were separate and clean:

- Collector source: `8b0441fb5b052c7b103f55a4f2ab2e72b5a4add5`, tree `53763907750d7637474685c25c4d5740f5a8ba41`.
- Shared original image/executable build: `e68c47ab9e9e69e8d28b3f8e2077ea45fa4776ee`, tree `830864d99f1d5685f2643767182af859b28c1f61`. No application or client image was rebuilt for Kubernetes.
- Original image manifest IDs: LSF `sha256:ae339a3194de7528217ba6352d28391425d71b584d89546808de4bd40e5b5eb3`; native `sha256:2d42cbc8194c46ce1c9614ac3bac94dd9e8c44df77ce75db692081cd610154b4`; client `sha256:a0b4d53de03366327b428e80b3e071abbe87b5519717c58839f954cb038d77d7`. Imported manifest/config/layer identities and Pod/CRI bindings remain separate; live extracted image layers were not independently rehashed during the campaign.
- Full suite SHA256: `c25e81cb839752d8bf42666200a6d8b2a21dcee309009104a7f60f85bf2276aa`; original 251,787,570B API journal SHA256: `abe7db60ed0bb752462cf052409f36bad8d3644f428cecfa9ba1f8f4d873eda7`.
- Full aggregate: 5,782,942B, SHA256 `f27538c151edb685722a645764861ab1254e68fec1f6c1f96057563cbff921d6`. The original [Docker aggregate](docker-aggregate.json) stays unchanged, bound to suite `sha256:d70b659d93fd8956029fb91dcac4c1e0bfa542b35fe4fa938ba1a2b7e80b64dd`.

The stopped pristine Docker catalogs were reused with their original hashes: **zero new seed starts, seed management RPCs or seed Invokes**. The measured LSF client made 63 GetNode calls across the seven pairs, over existing channels; native made none. The standard namespace/Pod/Service/API and bounded source observation work remain recorded; no extra workload calls were used for readiness.

Earlier outcomes remain distinct from the qualified full population:

| Attempt | Retained scope and disposition |
| --- | --- |
| smoke01 | Zero workload offers; original startup/session failure, original cleanup failure and separate explicit recovery retained. Never a qualified comparison. |
| smoke02 | 30 successful LSF offers; first native Service connection failed despite an available EndpointSlice. No native Invoke; inline cleanup retained. Subsequent protocol added the worker forwarding-rule gate. |
| smoke03 | All 300 offers completed under the original TCP startup probe. Original cleanup stopped on a missing-log stderr warning after successful CRI removal; an explicit seven-call, zero-Invoke completion took 0.562649599 s. Retained as a completed prior smoke, not a failed workload or a replacement for smoke04. |
| full01 | Five completed groups and 1,130 retained offers before one native D32 Pod failed. Original incomplete client, forwarding failure, cleanup error and separate recovery remain. Forwarding error detail/partial-byte accounting do not identify a proven TCP-probe cause. |
| smoke04 / full02 | Bounded exec-ready-record startup check, unchanged images. Smoke 300 and full 9,926 passed their own semantic/schema/provenance checks. No earlier observations are added to these denominators. |
| First full02 offline replay | Failed because cross-platform aggregation mistakenly compared timing-bearing count metadata for equality. Replay source `090818475cf2205bb65ffa722c3d85d83d651a8f` corrected only that comparison boundary; original source/suite/API bytes were unchanged and no workload was rerun. |

[Full offline replay](validation/issue112-full-02-replay.json) then passed in **56.178434576 s**, preserving the [initial failed receipt](validation/issue112-full-02-replay-initial.json). [Smoke04 replay](validation/issue112-smoke-04-replay.json) passed separately. The final publication validator source is `10d50e61c5632ea2361a16dffc3b4819987f4dc4`, including the relative Windows credential-reference fix; that publication validation is separate from the recorded source09 full-run replay. Offline validation ran after collection in a separate 3 GiB verifier; its 1,420,180 KiB process high-water RSS is verifier cost, not an application measurement.

All measured application/client ownership, namespace and mutable-data cleanup passed for full02. The final owned control-plane/worker containers and created network were physically removed, the controller disconnected, and both Linux and original Windows private credential copies removed with hash/absence receipts. Public evidence, imported images and output volumes were intentionally retained at that cleanup boundary. The archive's `cluster-cleanup/` records those actions, checked by the [final cleanup validator](validation/cleanup-linux.json); credential contents and even an empty `bootstrap/private/` tree are excluded. Prior smokes and failed attempts retain their original error clocks and recovery records.

The publication inventory contains **7,652 files / 848,006,375 payload bytes**; the canonical tar stream is **853,575,680 B**. The Kubernetes-specific 8,000-file cap retains full, revised smoke, prior completed smoke, failed attempts and cleanup together, under the unchanged 1 GiB expanded bound. The archive depends explicitly on the separately supplied original Docker package, SHA256 `b51441c7d23eb9569f77d00026533e9a5395c7732b1109b38cfbc3defeca43fd`; its 811,119,663 expanded bytes are not duplicated inside Kubernetes evidence. The [retention policy](../../../../docs/testing/benchmark-retention.md) governs current-checkout versus restored payload availability.

The compressed stream is **128,227,164 B**, SHA256 `30b81cef5129286510e8994b5bcb3c6ec8236c50b1eebb0686ffc25afb9dfc1e`, split into **50,000,000 / 50,000,000 / 28,227,164 B** parts. The [raw manifest](raw-evidence.manifest.json) and [split hashes](raw-evidence.parts.json) bind the published stream. [Linux packaging and complete semantic replay](validation/package-linux.json) passed in **160.162756058 s**, including compression and validation against the original Docker dependency. [Independent Windows complete-package replay](validation/windows-replay.json) passed in **439.2165928 s**, with the package unchanged and copied public bytes identical to Linux; the [original replay log](validation/windows-replay.log) is retained.

The complete Kubernetes package remains in this checkout. To stay within the 600 MiB repository benchmark budget, only the original Docker package's four raw parts (169,803,211 B) were retired; its report, tables and manifests remain. Restore that exact dependency directory from storage commit `a432c51f9ed0a4eaf55473d80122bbb8e5a419cf` into a fresh directory outside the checkout. This storage revision does not replace the measured build or collector sources. From the repository root in Bash, replay both packages without executing any retained binary:

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

Use the [fixed collection runbook](../../../../docs/testing/kubernetes-comparison.md) and exact measured source/image identities for a new reproduction; its output is a new campaign. Final-head CI and merge status are recorded in [PR133](https://github.com/KirilsTurkins/latent-service-fabric/pull/133); measurement qualification and merge readiness are separate.
