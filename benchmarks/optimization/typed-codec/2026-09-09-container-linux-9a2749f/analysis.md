# Detailed paired codec and RPC analysis

Both fixed RPC and codec populations passed full semantic replay. The codec
result includes all 84 allocation profiles. See [the report](README.md) for
exact sources, limitations and the separate archive verification boundaries.

All deltas are candidate minus control. L/E/H means lower/equal/higher, without
implying that lower throughput is favorable. RPC arm values are medians of seven
process quantiles; codec arm values are medians of seven process batch averages.
Paired medians come from seven within-pair differences. The two definitions are
not interchangeable, and requests are never pooled across independent processes.
Values are rounded only for display. Odd repetitions run control first, even
repetitions candidate first. These small strata are descriptive, not causal.

RPC uses control `204439091142374a12870e88b2b9eac7ca133ccc` and candidate/harness
`c5dd2169a8db23fe9ac232f6394eb68e5e0b269e`. Its aggregate SHA-256 is
`07e3b083acd57062499c0da0da7239caf5012440fcf152176a4457c6b5085f26`, bound to suite
`1bfbfa65143944bb1b6aceea432753d10425fcce71d07580f48c10dc40317ea0`.
All 25,256 offers succeeded semantically and on time: 22,960 measured and 2,296
warmup. The 98 validated owners comprise 14 servers, 14 setup CLI owners and
70 clients. RPC latency tables below use us.

## Successful response latency

| Case | Quantile | Control | Candidate | Paired delta | L/E/H |
| --- | --- | ---: | ---: | ---: | --- |
| warm-echo | p50 | 531.364 | 511.362 | -20.002 | 6/0/1 |
| warm-echo | p95 | 979.532 | 977.019 | -26.102 | 4/0/3 |
| warm-echo | p99 | 1,318.834 | 1,283.657 | -12.664 | 4/0/3 |
| compute | p50 | 618.609 | 621.220 | -9.287 | 4/0/3 |
| compute | p95 | 1,147.575 | 1,113.780 | -46.004 | 4/0/3 |
| compute | p99 | 1,427.308 | 1,365.694 | 15.247 | 3/0/4 |
| transform | p50 | 895.380 | 736.792 | -146.641 | 7/0/0 |
| transform | p95 | 1,425.553 | 1,313.719 | -90.222 | 7/0/0 |
| transform | p99 | 1,942.311 | 1,725.201 | -153.821 | 6/0/1 |
| payload-64k | p50 | 913.112 | 929.890 | 13.713 | 2/0/5 |
| payload-64k | p95 | 1,537.316 | 1,553.054 | -47.983 | 4/0/3 |
| payload-64k | p99 | 2,048.295 | 1,927.019 | -165.067 | 6/0/1 |
| payload-near-limit | p50 | 1,321.994 | 1,275.638 | -97.941 | 5/0/2 |
| payload-near-limit | p95 | 2,066.808 | 1,938.164 | -156.354 | 5/0/2 |
| payload-near-limit | p99 | 2,332.584 | 2,230.939 | -358.117 | 5/0/2 |

## All-offered completion elapsed

| Case | Quantile | Control | Candidate | Paired delta | L/E/H |
| --- | --- | ---: | ---: | ---: | --- |
| warm-echo | p50 | 594.824 | 572.378 | -27.791 | 5/0/2 |
| warm-echo | p95 | 1,077.735 | 1,053.845 | -30.362 | 5/0/2 |
| warm-echo | p99 | 1,398.833 | 1,340.227 | -1.918 | 4/0/3 |
| compute | p50 | 680.256 | 687.210 | -6.448 | 5/0/2 |
| compute | p95 | 1,225.854 | 1,212.762 | -80.165 | 5/0/2 |
| compute | p99 | 1,517.011 | 1,467.209 | -12.058 | 4/0/3 |
| transform | p50 | 967.338 | 805.230 | -150.991 | 7/0/0 |
| transform | p95 | 1,507.570 | 1,393.019 | -63.045 | 6/0/1 |
| transform | p99 | 2,004.303 | 1,875.116 | -111.792 | 6/0/1 |
| payload-64k | p50 | 983.013 | 1,003.228 | 14.046 | 2/0/5 |
| payload-64k | p95 | 1,638.673 | 1,649.359 | -38.819 | 4/0/3 |
| payload-64k | p99 | 2,156.873 | 2,058.984 | -148.349 | 6/0/1 |
| payload-near-limit | p50 | 1,398.118 | 1,365.500 | -97.326 | 5/0/2 |
| payload-near-limit | p95 | 2,181.965 | 2,048.645 | -178.777 | 5/0/2 |
| payload-near-limit | p99 | 2,457.646 | 2,376.951 | -351.097 | 4/0/3 |

## Throughput and offered outcomes

| Case | Control successful/s | Candidate successful/s | Paired delta/s | L/E/H | Measured success control/candidate | Warmup success control/candidate |
| --- | ---: | ---: | ---: | --- | --- | --- |
| warm-echo | 1,350.260 | 1,417.376 | 67.115 | 0/0/7 | 2800/2800 / 2800/2800 | 280/280 / 280/280 |
| compute | 1,221.314 | 1,218.690 | 18.340 | 3/0/4 | 2800/2800 / 2800/2800 | 280/280 / 280/280 |
| transform | 899.363 | 1,035.562 | 129.053 | 0/0/7 | 2800/2800 / 2800/2800 | 280/280 / 280/280 |
| payload-64k | 836.761 | 826.043 | -4.055 | 4/0/3 | 2800/2800 / 2800/2800 | 280/280 / 280/280 |
| payload-near-limit | 592.620 | 612.007 | 21.872 | 2/0/5 | 280/280 / 280/280 | 28/28 / 28/28 |

Detailed outcome categories, budget misses, attempted throughput and exact unrounded statistics are retained in the [retained RPC aggregate](rpc/aggregate.json). Throughput spans first scheduled measured offer to final completion, including gaps. It is not a mean of per-call reciprocal latencies.

## Observed process resources

CPU is user+system ticks already differenced over each observed batch, including warmup and observation. The actual clock is 100 Hz; one tick is 10 ms. It is not per-call CPU. RSS is maximum sampled process RSS, not instantaneous peak, allocation volume or the codec selected heap.

| Case | Owner | Control/candidate CPU totals (s) | Paired CPU delta (ticks) | CPU L/E/H | Control/candidate median sampled RSS (B) | Paired RSS delta (B) | RSS L/E/H |
| --- | --- | ---: | ---: | --- | ---: | ---: | --- |
| warm-echo | server | 1.78 / 1.69 | -2 | 5/1/1 | 25,690,112 / 25,792,512 | 131,072 | 3/0/4 |
| warm-echo | client | 0.92 / 0.88 | -1 | 4/3/0 | 4,456,448 / 4,587,520 | 131,072 | 0/2/5 |
| compute | server | 2.01 / 2.02 | -1 | 4/0/3 | 27,103,232 / 27,181,056 | 98,304 | 3/0/4 |
| compute | client | 0.89 / 0.91 | 0 | 2/3/2 | 4,587,520 / 4,587,520 | 0 | 3/2/2 |
| transform | server | 2.75 / 2.31 | -7 | 7/0/0 | 28,405,760 / 28,536,832 | 131,072 | 2/0/5 |
| transform | client | 1.04 / 0.99 | -1 | 4/3/0 | 4,587,520 / 4,718,592 | 0 | 0/4/3 |
| payload-64k | server | 2.68 / 2.70 | 1 | 3/0/4 | 29,523,968 / 29,843,456 | 143,360 | 2/0/5 |
| payload-64k | client | 1.64 / 1.66 | 1 | 2/1/4 | 5,505,024 / 5,480,448 | -86,016 | 4/0/3 |
| payload-near-limit | server | 0.42 / 0.40 | 0 | 3/2/2 | 29,503,488 / 29,790,208 | 147,456 | 2/0/5 |
| payload-near-limit | client | 0.20 / 0.18 | -1 | 4/1/2 | 6,004,736 / 6,029,312 | -40,960 | 4/0/3 |

All five cases, server observed CPU: 9.64 -> 9.12 s; median paired per-run delta -6 ticks, L/E/H 7/0/0.

All five cases, client observed CPU: 4.69 -> 4.62 s; median paired per-run delta 0 ticks, L/E/H 3/2/2.

Maximum sampled server RSS across each run's five batches: arm medians 29,523,968 -> 29,843,456 B; paired median 143,360 B, L/E/H 2/0/5. Five batch RSS maxima were not summed. Last-live RSS and byte counters remain in the JSON.

## Order strata

Actual aggregate run order is control-first for repetitions 1/3/5/7 and candidate-first for 2/4/6. Each cell below is the median paired delta (L/E/H). Small strata are descriptive and do not identify causation.

| Case | Statistic | Control-first (4 pairs) | Candidate-first (3 pairs) |
| --- | --- | ---: | ---: |
| warm-echo | successful p50 us | -16.196 (3/0/1) | -20.002 (3/0/0) |
| warm-echo | successful p99 us | -48.286 (2/0/2) | -12.664 (2/0/1) |
| warm-echo | all-offered p99 us | -60.750 (2/0/2) | -1.918 (2/0/1) |
| warm-echo | successful/s | 48.802 (0/0/4) | 67.115 (0/0/3) |
| warm-echo | server CPU ticks | -1.500 (3/1/0) | -2.000 (2/0/1) |
| compute | successful p50 us | -13.348 (3/0/1) | 2.612 (1/0/2) |
| compute | successful p99 us | -25.136 (2/0/2) | 18.632 (1/0/2) |
| compute | all-offered p99 us | 21.530 (2/0/2) | -12.058 (2/0/1) |
| compute | successful/s | 22.773 (2/0/2) | 18.340 (1/0/2) |
| compute | server CPU ticks | -1.000 (2/0/2) | -1.000 (2/0/1) |
| transform | successful p50 us | -143.994 (4/0/0) | -146.641 (3/0/0) |
| transform | successful p99 us | -157.162 (4/0/0) | -74.813 (2/0/1) |
| transform | all-offered p99 us | -117.976 (4/0/0) | -111.792 (2/0/1) |
| transform | successful/s | 111.297 (0/0/4) | 129.053 (0/0/3) |
| transform | server CPU ticks | -6.000 (4/0/0) | -7.000 (3/0/0) |
| payload-64k | successful p50 us | 33.834 (0/0/4) | -60.972 (2/0/1) |
| payload-64k | successful p99 us | -113.840 (3/0/1) | -192.969 (3/0/0) |
| payload-64k | all-offered p99 us | -153.194 (3/0/1) | -148.349 (3/0/0) |
| payload-64k | successful/s | -17.188 (3/0/1) | 60.038 (1/0/2) |
| payload-64k | server CPU ticks | 1.500 (1/0/3) | -1.000 (2/0/1) |
| payload-near-limit | successful p50 us | -39.410 (2/0/2) | -114.661 (3/0/0) |
| payload-near-limit | successful p99 us | 90.923 (2/0/2) | -650.329 (3/0/0) |
| payload-near-limit | all-offered p99 us | 130.620 (1/0/3) | -605.959 (3/0/0) |
| payload-near-limit | successful/s | -2.851 (2/0/2) | 43.611 (0/0/3) |
| payload-near-limit | server CPU ticks | -1.000 (3/1/0) | 1.000 (0/1/2) |

## Scope and inherited #104 question

The historical #104 warm-only paired p50 +37.451 us (9/14 higher) and warm server CPU +5.7% are a separate two-campaign observation. Compare #105 only with its current matched control; do not subtract historical medians or claim restoration to an older binary. The present result cannot isolate codec CPU from scheduling, guest execution, manager/RPC work or host state. Compute includes actual compute work. Any improvements or regressions in standalone codec profiles remain a separate population.

The retained host is Docker/WSL2 on an i7-11850H with 16 logical CPUs, a 4-CPU quota and cpuset 0-15; the build reports Rust 1.97.1 and Wasmtime 47.0.3. This note does not infer per-batch throttling from the aggregate's initial cgroup snapshot. Per-batch raw cgroups, full owner receipts and detailed failure codes require their retained suite documents; no unsupported resource or cleanup proof is invented here.

All raw fixed calls remain represented; a valid complete aggregate is not a production SLO or a statistical significance/equivalence claim. The codec population below has its own source references and qualification boundary.

## Interpretation

All 25,256 offered calls, including warmup, succeeded semantically and on time; no failure or late-success population is hidden. Warm Echo improves against this matched control: paired p50 -20.002 us (6/7 lower), successful throughput +67.115/s (7/7 higher), and warm server batch CPU 1.78 -> 1.69 s (-5.06%; paired -2 ticks, 5/7 lower). Its p95/p99 changes remain mixed (each 4/7 lower), and sampled RSS increases. This addresses the direction of the inherited warm concern within #105, without claiming that the historical #104 cost has been erased.

Transform has the clearest matched improvement: p50 -146.641 us, throughput higher, and server CPU lower in every pair. The 64 KiB case remains a regression at p50: +13.713 us (5/7 higher), all-offered p50 +14.046 us (5/7 higher), throughput -4.055/s (4/7 lower), and paired server CPU +1 tick (4/7 higher), despite improved p99. Its p50 direction also flips by order stratum: control-first +33.834 us versus candidate-first -60.972 us. Compute p99 rises by 15.247 us (4/7 higher). Near-limit overall latency medians improve, but its p99 order strata differ (control-first +90.923 us versus candidate-first -650.329 us), so a consistent tail gain would overstate the evidence.

All-case server CPU decreases 9.64 -> 9.12 s (-5.39%), with each paired run lower; client CPU changes are mixed. Maximum sampled server RSS rises by a paired median 143,360 B (5/7 higher). These observations support neither a universal RPC speedup nor a general process-memory reduction, and do not attribute the mixed RPC effects solely to the codec.

## Codec-only normal results

Codec uses control `d9fc1e80405899c6e2efaf1b1369efd61ccfa1a3` and candidate/harness
`9a2749f6004372bf6c0c0aa20f045b1f3cacf3b0`. Independent normal replay checked all
84 normal children, 224,840 codec operations, actual same-task clocks and clean
owners. Full whole-suite/profile semantic replay also passed.
The full suite is bound by SHA-256
`23283585e723e71bb79a0ee983c12ba454a62a310d89f2b06c02f644761fc497`.

Each displayed operation time is its measured batch duration divided by its
successful operation count, then the median of seven process means. Percentages
are medians of seven paired percentages. These are not per-call p50/p95/p99
observations. Both measured directions include result Drop inside their selected
frame. The high-resolution CPU bracket surrounds the wall-clock calls; coarse
/proc samples lie outside that high-resolution bracket. Normal process metrics
include setup, preflight, warmup, both directions, validation, holds and teardown.

## Decode measured batches

| Family | Ops / child | Elapsed Control / candidate (us/op) | Paired elapsed delta (us/op; %) | Lower / equal / higher | Thread CPU Control / candidate (us/op) | Paired CPU delta (us/op; %) | Lower / equal / higher |
|---|---:|---:|---:|---:|---:|---:|---:|
| scalar-params | 4096 | 1.754 / 1.271 | -0.585; -26.070% | 5/0/2 | 1.754 / 1.272 | -0.585; -26.065% | 5/0/2 |
| byte-list | 573 | 437.948 / 157.192 | -285.227; -64.579% | 7/0/0 | 437.912 / 157.185 | -285.198; -64.577% | 7/0/0 |
| nested-record | 2943 | 70.659 / 48.211 | -24.024; -33.700% | 7/0/0 | 70.652 / 48.208 | -24.021; -33.699% | 7/0/0 |
| string-64k | 127 | 62.850 / 53.962 | -8.888; -14.141% | 7/0/0 | 62.863 / 53.982 | -8.881; -14.127% | 7/0/0 |
| string-near-limit | 68 | 103.162 / 105.782 | 0.693; 0.660% | 3/0/4 | 103.178 / 105.818 | 0.699; 0.666% | 3/0/4 |
| escaped-unicode | 85 | 231.578 / 238.911 | 6.416; 2.776% | 3/0/4 | 231.609 / 238.940 | 6.418; 2.776% | 3/0/4 |

## Encode measured batches

| Family | Ops / child | Elapsed Control / candidate (us/op) | Paired elapsed delta (us/op; %) | Lower / equal / higher | Thread CPU Control / candidate (us/op) | Paired CPU delta (us/op; %) | Lower / equal / higher |
|---|---:|---:|---:|---:|---:|---:|---:|
| scalar-params | 4096 | 0.693 / 0.696 | 0.007; 0.970% | 3/0/4 | 0.693 / 0.696 | 0.007; 0.970% | 3/0/4 |
| byte-list | 573 | 93.367 / 98.395 | 3.889; 4.268% | 1/0/6 | 93.363 / 98.391 | 3.891; 4.270% | 1/0/6 |
| nested-record | 2943 | 17.595 / 15.457 | -2.138; -12.153% | 7/0/0 | 17.593 / 15.457 | -2.136; -12.142% | 7/0/0 |
| string-64k | 127 | 16.241 / 16.742 | 0.263; 1.704% | 3/0/4 | 16.249 / 16.747 | 0.262; 1.697% | 3/0/4 |
| string-near-limit | 68 | 29.434 / 29.930 | -0.210; -0.716% | 4/0/3 | 29.441 / 29.937 | -0.214; -0.730% | 4/0/3 |
| escaped-unicode | 85 | 79.435 / 76.242 | -2.438; -3.155% | 6/0/1 | 79.444 / 76.244 | -2.430; -3.144% | 6/0/1 |

## Whole normal process costs

CPU includes child startup, fixture/type loading, preflight, warmup, both measured directions and output/cleanup. RSS is process-level, with the observed maximum distinct from live-read kernel VmHWM; neither is selected decoder allocation memory. No baseline subtraction is applied.

| Family | CPU Control / candidate (ms) | Paired CPU delta (ms) | Lower / equal / higher | Kernel VmHWM Control / candidate (MiB) | Paired delta (KiB) | Lower / equal / higher |
|---|---:|---:|---:|---:|---:|---:|
| scalar-params | 14.586 / 13.893 | -1.244 | 6/0/1 | 9.000 / 9.250 | 384.000 | 0/0/7 |
| byte-list | 321.732 / 159.043 | -164.930 | 7/0/0 | 9.875 / 9.875 | 0.000 | 2/3/2 |
| nested-record | 269.624 / 194.080 | -75.544 | 7/0/0 | 9.250 / 9.375 | 128.000 | 1/2/4 |
| string-64k | 17.258 / 15.945 | -1.190 | 6/0/1 | 9.250 / 9.375 | 256.000 | 1/0/6 |
| string-near-limit | 21.247 / 20.957 | 2.675 | 3/0/4 | 9.625 / 9.875 | 256.000 | 0/0/7 |
| escaped-unicode | 42.951 / 43.613 | 0.894 | 3/0/4 | 9.250 / 9.625 | 256.000 | 0/0/7 |

Whole normal CPU sums: control 4.906 s; candidate 3.162 s (-35.551%).

## Actual order strata

Control first: repetitions 1/3/5/7 (four pairs). Candidate first: 2/4/6 (three). The complete fixed population interleaves each normal pair with its separately profiled pair, so normal rows were not a standalone idle-host campaign. No causal attribution or statistical equivalence follows from order strata.

| Family | Decode elapsed delta Control-first / candidate-first (us/op) | Encode elapsed delta Control-first / candidate-first (us/op) | Whole CPU delta Control-first / candidate-first (ms) | VmHWM delta Control-first / candidate-first (KiB) |
|---|---:|---:|---:|---:|
| scalar-params | -0.509 / -0.585 | -0.026 / 0.007 | -2.194 / -0.672 | 448.000 / 256.000 |
| byte-list | -288.933 / -272.123 | 2.293 / 8.201 | -171.858 / -159.517 | 64.000 / -128.000 |
| nested-record | -24.264 / -21.209 | -2.268 / -2.055 | -76.538 / -71.576 | 64.000 / 128.000 |
| string-64k | -22.965 / -4.068 | 1.340 / -0.767 | -3.480 / -0.607 | 256.000 / 256.000 |
| string-near-limit | -0.336 / 0.693 | -0.232 / 1.587 | 2.792 / -0.387 | 320.000 / 256.000 |
| escaped-unicode | 10.417 / 6.416 | -2.816 / -2.087 | 1.480 / 0.894 | 256.000 / 384.000 |


## Allocation and peak evidence

Full Linux raw semantic replay passed all 168 children and 449,680 operations,
including all 84 separately profiled children. Aggregate SHA-256:
`c633ee7d25514d387b4b98dd1b9d50d189ab6b91c1eefca5f09ca24819d14ed9`
(1,005,817 bytes). All 84 attributions are available with zero
unresolved allocations. No profile is discarded or treated as an unavailable zero.

Selected counts and allocated bytes divide only the calls contained in their
measured batch frame. Peaks are undivided maximum simultaneous live bytes from
those allocation origins. The selected values below are invariant across all
seven repetitions within each arm, so every decrease is present in 7/7 pairs.

### Selected decode counts and bytes

| Family | Allocations / call C / N | Paired count change | Paired count change % | Allocated bytes / call C / N | Paired byte change | Paired byte change % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| scalar-params | 25 / 9 | -16 | -64.000% | 2,437 / 733 | -1,704 | -69.922% |
| byte-list | 8,216 / 4,108 | -4,108 | -50.000% | 731,424 / 458,608 | -272,816 | -37.299% |
| nested-record | 1,180 / 761 | -419 | -35.508% | 134,839 / 45,770 | -89,069 | -66.056% |
| string-64k | 3 / 2 | -1 | -33.333% | 65,856 / 65,584 | -272 | -0.413% |
| string-near-limit | 3 / 2 | -1 | -33.333% | 123,200 / 122,928 | -272 | -0.221% |
| escaped-unicode | 17 / 16 | -1 | -5.882% | 168,248 / 167,976 | -272 | -0.162% |

### Selected live-byte peaks

| Family | Decode peak C / N (B) | Paired decode change (B; %) | Simultaneous union peak C / N (B) | Paired union change (B; %) |
| --- | ---: | ---: | ---: | ---: |
| scalar-params | 1,294 / 640 | -654; -50.541% | 1,294 / 640 | -654; -50.541% |
| byte-list | 333,071 / 196,672 | -136,399; -40.952% | 333,071 / 196,672 | -136,399; -40.952% |
| nested-record | 90,286 / 24,330 | -65,956; -73.052% | 90,286 / 24,330 | -65,956; -73.052% |
| string-64k | 65,856 / 65,584 | -272; -0.413% | 131,076 / 131,076 | +0; +0.000% |
| string-near-limit | 123,200 / 122,928 | -272; -0.221% | 245,764 / 245,764 | +0; +0.000% |
| escaped-unicode | 102,528 / 102,448 | -80; -0.078% | 102,528 / 102,448 | -80; -0.078% |

The union peak uses the actual simultaneous trace of both origins; it is not
the sum of frame peaks. Encoding sets the larger selected peak for the 64 KiB
and near-limit strings. Every selected frame and union ends with zero remaining
allocations and zero live bytes in all 84 profiles.

### Selected encode values

Every value and paired difference is equal across both arms and all seven
pairs. Source and legacy-produced input capacities are common. Encode timing
variation in the normal processes does not imply an encoder implementation change.

| Family | Allocations / call, both arms | Allocated bytes / call, both arms | Peak live bytes, both arms |
| --- | ---: | ---: | ---: |
| scalar-params | 11 | 372 | 180 |
| byte-list | 15 | 32,767 | 16,384 |
| nested-record | 16 | 8,194 | 4,097 |
| string-64k | 4 | 196,617 | 131,076 |
| string-near-limit | 4 | 368,649 | 245,764 |
| escaped-unicode | 17 | 196,605 | 98,304 |

### Whole-process allocation totals

These totals include type/fixture setup, preflight, warmup, both directions,
validation and teardown. They are not attributed solely to the measured decoder
or divided by measured call count. Columns are medians of seven process totals;
paired changes are computed before taking their median. Allocation counts and
allocated bytes are lower in every pair for every family.

| Family | Allocations C / N | Paired count change | Allocated bytes C / N | Paired byte change | Paired byte change % |
| --- | ---: | ---: | ---: | ---: | ---: |
| scalar-params | 150,042 / 84,154 | -65,888 | 11,908,881 / 4,894,736 | -7,014,142 | -58.898% |
| byte-list | 4,911,532 / 2,467,272 | -2,444,260 | 456,007,488 / 293,684,889 | -162,322,602 | -35.596% |
| nested-record | 3,549,099 / 2,306,764 | -1,242,335 | 424,595,149 / 160,508,492 | -264,086,656 | -62.197% |
| string-64k | 2,809 / 2,660 | -149 | 40,035,840 / 39,998,247 | -37,595 | -0.094% |
| string-near-limit | 2,397 / 2,307 | -90 | 45,710,485 / 45,688,936 | -21,553 | -0.047% |
| escaped-unicode | 5,435 / 5,328 | -107 | 40,331,743 / 40,305,566 | -26,177 | -0.065% |

| Family | Whole peak live bytes C / N | Paired peak change (B; %) | L/E/H |
| --- | ---: | ---: | ---: |
| scalar-params | 142,036 / 142,054 | +18; +0.013% | 0/0/7 |
| byte-list | 864,623 / 744,456 | -120,167; -13.898% | 7/0/0 |
| nested-record | 276,359 / 198,236 | -78,123; -28.269% | 7/0/0 |
| string-64k | 612,020 / 611,740 | -280; -0.046% | 7/0/0 |
| string-near-limit | 1,070,788 / 1,070,508 | -280; -0.026% | 7/0/0 |
| escaped-unicode | 591,546 / 591,266 | -280; -0.047% | 7/0/0 |

Scalar whole-process peak increases by 18 B in every pair. The other five
families decrease, but this is not a universal whole-process peak or RSS gain.
Every whole profile ends with the same three allocations totaling 928 B.
That whole-process remainder is separate from the fully freed selected origins.
Kernel RSS, Rust capacity, selected heap and guest memory are distinct quantities.

## Recomputing the tables

In the RPC aggregate, select `comparisons[]` by case `id`. For each numbered
pair, read `control` and `candidate`, then `successful_response_latency_nanos`
or `all_offered_elapsed_nanos` at `median`, `p95`, `p99`. Compute their paired
candidate-minus-control changes before taking the across-pair median. The
retained `candidate_minus_control_nanos` and `paired_differences_nanos` fields
match this independent arithmetic. Throughput is `successes_per_second`; every
case here has equal attempted and successful throughput because all offers
succeeded. Resource deltas are already differenced in `runs[].batches[].resources`;
sum user/system CPU ticks once, then divide by the actual 100 Hz clock. Do not
subtract the deltas again or sum server RSS peaks across its five batches.

For codec normal rows, select `(family, mode='normal', repetition, variant)`.
Divide each actual direction's elapsed or thread-CPU difference by that row's
measured-success count. Pair by repetition, never by sorted performance. The
normal metrics are `decode_elapsed_nanos_per_operation`,
`encode_elapsed_nanos_per_operation`, `decode_thread_cpu_nanos_per_operation`,
`encode_thread_cpu_nanos_per_operation`, `whole_process_cpu_micros`,
`normal_observed_rss_bytes`, `normal_kernel_high_water_rss_bytes` and
`normal_completion_rss_bytes`. Keep all seven directions, including regression
and equal pairs; per-process averages are not individual latency samples.

For allocation rows, select `mode=allocation` and pair the same family and
repetition. Named entries in `allocation_attribution.frames` supply total
allocated bytes/counts and undivided peaks; divide only those totals by the
matched `result.directions[].measured_successes`. The simultaneous union is
`allocation_attribution.union`. Whole totals come from
`whole_process_allocations`. All 84 statuses are `available`, all unresolved
counts are zero, and selected remaining counts/bytes are zero. Preserve actual
whole-process remainders rather than replacing them with selected zeros.
