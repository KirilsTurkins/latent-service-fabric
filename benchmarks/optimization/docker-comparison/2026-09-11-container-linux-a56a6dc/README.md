# Docker comparison: native services and LSF

LSF reduced the memory charged to the application cohort at 8 and 32 services, and brought those cohorts to readiness sooner. Native returned requests faster: all seven pairs favored native for the measured p50, p99 and response throughput shown below. At one service, LSF also used more memory. These results describe the particular container topology, resource partition and workloads tested here.

The complete run returned **9,926 successful responses from 9,926 offers**, with zero semantic mismatches, undispatched offers or request-budget misses. It comprised 574 first-per-service calls, 2,576 warmup calls and 6,776 measured calls. The separate smoke run passed all 300 offers. No workload offers were omitted or retried. All **318 full-run containers** and **48 smoke containers** were stopped and removed, including clients and seed owners. The full aggregate's collection span was **389.788 s**, covering seed setup, paired clients, parent observations and cleanup; the outer collection command took **391.814 s**.

`D` is the number of services and `C` is client concurrency. Every arm value below is the **median of seven pair-level metrics**. Each `Δ` is the **median of the seven paired LSF-minus-native differences**, calculated before summarizing; it need not equal the difference between the displayed arm medians. Latency p50/p99 are conditional on successful responses. Percentiles are never pooled across pairs or phases. The CSV comparisons retain every pair, spread, sign count and execution-order stratum; seven pairs support descriptive comparisons, not confidence intervals or a universal deployment claim.

Both arms used actual Docker containers, the same pinned Debian base and TCP wrapper, and the same separate persistent client with up to 32 channels, one per service. One LSF container hosted D component services; native used D containers, each hosting one service. The application cohort had 4 CPU equivalents, 2 GiB memory and 512 PIDs in total. Native split these evenly: each D8 container had 0.5 CPU/256 MiB, and each D32 container 0.125 CPU/64 MiB. LSF shared its allocation across four cells. At C4, requests can use at most four native partitions concurrently: the aggregate resource budget is equal, but the usable CPU partition is different. The client had its own 2 CPU/256 MiB limit and two workers. Request budgets were 1 s, with a 5 s response timeout. LSF used four cells, queue capacity 64, prepared cache capacity 32 and catalog capacity 64.

This was Docker Desktop/WSL2 on an Intel Core i7-11850H host, with 16 CPUs and 33.23 GB visible to the Linux VM, Docker Engine 29.7.2 and cgroup v2. Other host activity was retained as context and was not subtracted. The native implementation supplies the matching workload function and transport; it does not supply LSF's component isolation, capability restrictions, admission accounting, catalog/control plane or retained activation status. Thus the measured latency difference includes different runtime responsibilities.

The warm workload results were:

| Workload | Native / LSF p50, ms | Paired Δ p50, ms | Native / LSF p99, ms | Paired Δ p99, ms | Native / LSF responses/s |
|---|---:|---:|---:|---:|---:|
| D1 Echo, C1 | 0.370 / 0.813 | +0.417 | 0.770 / 1.695 | +0.925 | 1,785 / 920 |
| D1 compute, C1 | 0.411 / 0.992 | +0.565 | 1.036 / 2.014 | +1.137 | 1,586 / 791 |
| D1 Echo, C4 | 0.417 / 1.032 | +0.586 | 1.052 / 2.326 | +1.274 | 6,274 / 3,184 |
| D8 density Echo, C4 | 0.386 / 1.043 | +0.647 | 0.578 / 2.461 | +1.791 | 7,285 / 2,990 |
| D32 density Echo, C4 | 0.425 / 1.018 | +0.586 | 0.903 / 2.265 | +1.385 | 6,560 / 3,136 |

Native had lower p50/p99 and higher throughput in **7/7 pairs for every row**. D1 measured Echo phases had 128 offers per arm/pair, compute had 64, and D8/D32 density phases had 32/128. The additional four-offer D1 density phase remains in the tables. Throughput uses first scheduled offer through last completion; the separate phase-span metric includes validation/output work. [Phase observations](phase-rows.csv) and [paired comparisons](phase-comparisons.csv) also retain warmups, all-dispatched latency, all-offered elapsed time and dispatch lag.

First-per-service calls occurred before warmup. They are separate from container startup and from the warm distributions:

| D | Native / LSF first-call p50, ms | Paired Δ p50, ms | Native / LSF first-call p99, ms | Paired Δ p99, ms |
|---|---:|---:|---:|---:|
| 1 | 1.019 / 47.813 | +47.016 | 1.019 / 47.813 | +47.016 |
| 8 | 0.554 / 42.493 | +41.893 | 0.955 / 49.729 | +48.774 |
| 32 | 0.615 / 39.766 | +39.192 | 1.191 / 57.517 | +56.445 |

Native was faster in all seven pairs. D1 has only one first call per arm/pair, so its within-pair p50 and p99 are the same observation. These measurements alone do not isolate compilation, instantiation or transport costs.

The parent-clock lifecycle measurements instead show the cost of bringing the entire cohort into service:

| D | Native / LSF first start → last ready, s | Paired Δ, s | Native / LSF first start → first response observed, s | Paired Δ, s |
|---|---:|---:|---:|---:|
| 1 | 0.278 / 0.287 | +0.025 | 0.636 / 0.692 | +0.075 |
| 8 | 2.733 / 0.295 | −2.438 | 3.583 / 0.704 | −2.884 |
| 32 | 14.467 / 0.310 | −14.154 | 17.172 / 0.737 | −16.399 |

These are **observed upper bounds with images already present**, not image-pull times or ideal cold-invocation latency. Native containers were provisioned sequentially. Channel connection, parent observation and the intentional 250 ms ready barrier remain inside the applicable spans. LSF's D8/D32 bounds were lower in 7/7 pairs; D1 readiness was higher in 6/7 and first-response observation higher in 7/7. See [owner lifecycle observations](lifecycle-owners.csv), [cohort observations](lifecycle-cohorts.csv) and [paired lifecycle comparisons](lifecycle-comparisons.csv).

Memory was observed after three requested 250 ms idle windows: **ready** before any call, **served** after first-per-service calls, and **final** after all warmup/measured phases. The following values sum each application's leaf cgroup exactly once, covering its child and wrapper. Cells show **native / LSF (paired Δ)** in MiB:

| D | Ready cgroup memory | Served cgroup memory | Final cgroup memory |
|---|---:|---:|---:|
| 1 | 1.844 / 3.086 (+1.250) | 1.879 / 5.391 (+3.574) | 2.219 / 8.496 (+6.207) |
| 8 | 14.484 / 3.742 (−10.898) | 15.074 / 7.738 (−7.348) | 15.230 / 8.816 (−6.375) |
| 32 | 57.969 / 5.449 (−52.570) | 59.609 / 13.031 (−46.656) | 61.098 / 14.625 (−46.641) |

The direction holds in all seven pairs at every stage: LSF was higher at D1 and lower at D8/D32. Final process RSS shows the separate application and wrapper footprints, again in MiB:

| D | Child RSS: native / LSF (paired Δ) | Wrapper RSS: native / LSF (paired Δ) |
|---|---:|---:|
| 1 | 4.500 / 23.855 (+19.375) | 3.750 / 3.625 (0.000) |
| 8 | 35.625 / 23.777 (−11.977) | 29.125 / 3.750 (−25.250) |
| 32 | 142.625 / 28.211 (−114.359) | 116.500 / 4.250 (−112.250) |

RSS sums can count shared pages repeatedly and are not PSS. They must not be added to cgroup memory or interpreted as unique physical memory. The resource CSVs also retain sums of leaf lifetime peaks; these are not simultaneous cohort peaks, and no within-invocation memory maximum was sampled. [Resource points](resource-points.csv) and [paired resource comparisons](resource-comparisons.csv) preserve all six snapshots, availability and owner identities.

**Warm interval CPU per offered call** is the cohort's cumulative `cgroup.cpu.usage_usec` at `final.after` minus `served.after`, divided by all remaining warmup and measured offers. Every pair has both endpoints for the same complete cohort. Values below are **µs per offer**, using the same arm-median and paired-difference convention:

| D | Offers per arm/pair | Native | LSF | Paired Δ | Paired Δ range, all seven |
|---|---:|---:|---:|---:|---:|
| 1 | 348 | 298.905 | 842.072 | +529.741 | +482.483 to +631.063 |
| 8 | 64 | 2,878.750 | 1,107.531 | −1,806.156 | −1,951.844 to −1,392.922 |
| 32 | 256 | 2,783.277 | 801.664 | −1,988.184 | −2,234.320 to −1,873.695 |

LSF was higher in 7/7 D1 pairs and lower in 7/7 D8/D32 pairs. This interval includes warmup and measured work, final inventory, snapshots, barrier and idle overhead. Native D8/D32 includes D wrappers, the final requested 250 ms idle window and snapshot reads for all D containers; this observation and idle work can dominate the small 64/256-offer populations. The higher-density reduction therefore does not establish production CPU efficiency or isolate handler cost. **No idle CPU is subtracted**: the separate idle brackets have different observation boundaries. All seven cumulative endpoints remain in [resource-points.csv](resource-points.csv), with the offer denominators in [phase-rows.csv](phase-rows.csv).

Final idle-window application-plus-wrapper cgroup CPU was 12.165 / 11.023 ms at D1 (paired Δ −0.962 ms, mixed signs), 81.945 / 13.049 ms at D8 (−69.845 ms), and 319.756 / 13.230 ms at D32 (−306.330 ms). Both density reductions held in 7/7 pairs. These brackets include snapshot activity around the requested sleep; they are not exact 250 ms utilization or workload-only CPU measurements. [Idle windows](idle-windows.csv) and [paired idle comparisons](idle-window-comparisons.csv) retain durations and throttling counters.

Client CPU from ready to final was higher for LSF in all seven pairs: 116.522 / 146.650 ms at D1 (paired Δ +25.429 ms), 21.263 / 32.116 ms at D8 (+10.243 ms), and 84.982 / 118.417 ms at D32 (+35.961 ms). This includes client validation, output and barriers, including served/final `GetNode` RPCs in the LSF arm; native barriers issue no corresponding RPCs. Separate child/wrapper CPU, exact controller cost and shared-VM background attribution are unavailable. The client's reported lifetime memory maximum is also unavailable; it is not zero. See [client resource points](client-resource-points.csv), [intervals](client-intervals.csv) and [paired CPU comparisons](client-cpu-comparisons.csv). These observations do not establish a client-unlimited saturation ceiling.

The executable/image build used clean source `e68c47ab9e9e69e8d28b3f8e2077ea45fa4776ee`; the full collector used `a56a6dc2a80064657bb953f03d9b9129d300ec9f`, and the successful smoke collector used `1718a7eddd5d17c2ff5005db099ead6f8a15d996`. Build and collector identities are separate and retained. Three pristine LSF templates were seeded through **88 real management RPCs and zero Invokes**, then sealed only after clean shutdown. The full population contained 21 measured LSF owners, 287 native owners, seven clients and three seed owners.

The archive retains complete earlier smoke attempts and `attempts/index.json`. Smoke 01 stopped at a Docker log-start HTTP 500; smoke 02 stopped when the client CLI rejected non-loopback targets. Both offered zero workload requests. Their originals remain distinct from the successful 300-offer smoke and 9,926-offer full run; neither failure was silently removed or qualified as a successful campaign.

[aggregate.json](aggregate.json) and all 12 CSV files are bound by [tables.manifest.json](tables.manifest.json). The [raw manifest](raw-evidence.manifest.json) lists **5,015 files / 811,119,663 expanded bytes**, including the failed attempts. The split archive represents **169,803,211 compressed bytes**, SHA-256 `b51441c7d23eb9569f77d00026533e9a5395c7732b1109b38cfbc3defeca43fd`; [parts and hashes](raw-evidence.parts.json) bind its four fragments. Packaging used an explicit Docker-only 6,000-file archive limit for this combined publication; retained byte limits remain unchanged. [Linux package verification](validation/package-linux.json) passed mandatory semantic replay in 108.208 s.

The current checkout retains this report and its original tables, manifests and
replay receipts. The four raw parts are retained in the fixed storage commit below
to leave room for the Kubernetes comparison under the 600 MiB benchmark budget.
Follow the [retention policy](../../../../docs/testing/benchmark-retention.md);
from the repository root, restore this exact package into a fresh external
directory before replaying it:

```sh
storage_commit=a432c51f9ed0a4eaf55473d80122bbb8e5a419cf
docker_package=benchmarks/optimization/docker-comparison/2026-09-11-container-linux-a56a6dc
restored_root=../benchmark-docker-raw
mkdir -- "$restored_root"
git archive --format=tar "$storage_commit" "$docker_package" | tar -xf - -C "$restored_root"
python tools/validate_phase1_archive.py "$restored_root/$docker_package"
```

Independent [Windows archive replay](validation/issue111-windows-replay-02.log.receipt.json) also passed all 5,015 files in 96.947 s. Its [first attempt](validation/issue111-windows-replay-01.log.receipt.json) exposed a Windows path-separator issue in the validator; that source fix changed neither workload evidence nor archive bytes.

Merge readiness is determined by the required checks on the associated pull request's final commit; measurement qualification and merge readiness are separate.
