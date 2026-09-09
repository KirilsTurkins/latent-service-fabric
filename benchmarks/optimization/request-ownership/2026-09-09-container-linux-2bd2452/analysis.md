# Detailed request-ownership analysis

The [report](README.md) states the accepted ownership tradeoff and remaining
warm-RPC cost. These descriptive tables derive from the [primary RPC](rpc/aggregate.json),
[direct backend](backend/aggregate.json) and [replicated RPC](rpc-diagnostic/aggregate.json)
aggregates. They retain original per-campaign results and all combined pairs.
Each input suite hash and each displayed per-campaign latency difference was
checked against its aggregate references. Independent full archive replay is
reported separately in the report. No individual-call pooling or equivalence
claim is used.

## Primary campaign

All paired deltas below are candidate minus control, with each arm column the median of seven process-level observations. L/E/H counts lower/equal/higher paired values. Lower latency/CPU/memory and higher throughput are favorable. Difference of arm medians is not the median paired difference. Seven pairs are descriptive, without significance or universality claims.

The result supports earlier raw-owner release and smaller whole-process allocation totals, with mixed timing and no general RPC or RSS improvement. RPC successful p50 paired medians increase by 50.9345 / 129.5835 / 148.663 microseconds across the three cases. Direct near-limit context setup improves in all seven pairs, but its full-call p95 regresses in four pairs. All selected-frame allocation totals remain unavailable.

## Exact sources and populations

- Control: `1f01544586fccee29da3423133928324ea2b0a5f`.
- Candidate and executed measurement harness: `2bd245269ae113600f591492d2780ac4bc4467ed`; harness equality: True.
- RPC: 12936 offers / 70 seed/server/client owners; collection 37.968771894 s (measurement_elapsed 37.839601687 s).
- Direct: 3160 Invokes / 26 children; collection 80.193634631 s.
- RPC per arm: 6,468 total = 5,880 measured + 588 warmups. The two first payload cases each have 400 measured + 40 warmup per process; near-limit has 40 measured + 4 warmup. All three use one server per arm. The first warmup contains its cold preparation.
- Normal direct: 14 children × (6 × (4 warmup + 32 measured) + 2 pending proofs) = 3,052 Invokes. The measured timing denominator is 224 per shape per arm, reported as seven independent 32-call process distributions.
- Allocation: one separate pair per shape, 12 children × (1 warmup + 8 measured) = 108 Invokes, no pending proofs. Combined external + direct population: 16,096. One control generation preparation and its host-only checks are outside these populations, with zero Invokes/guest Stores.

control RPC actual outcomes: `{'success': 6468}`; measured 5880, warmup 588.
candidate RPC actual outcomes: `{'success': 6468}`; measured 5880, warmup 588.

## RPC latency

Units: ms. Successful response latency starts at actual dispatch. All-offered elapsed starts at scheduled offer time and includes producer dispatch delay. It therefore remains a distinct metric even where every offer succeeds. Quantiles below come from each entire measured case, not medians of 100-call sub-batches.

| Case | Population | Quantile | Control ms | Candidate ms | Paired delta ms | L/E/H |
| --- | --- | --- | --- | --- | --- | --- |
| warm-echo | successful | p50 | 0.606531 | 0.636752 | 0.0509345 | 3/0/4 |
| warm-echo | successful | p95 | 1.128734 | 1.16523 | 0.055214 | 3/0/4 |
| warm-echo | successful | p99 | 1.603577 | 1.44895 | 0.040172 | 3/0/4 |
| warm-echo | all offered | p50 | 0.682612 | 0.7122075 | 0.045081 | 2/0/5 |
| warm-echo | all offered | p95 | 1.253956 | 1.248641 | 0.021034 | 3/0/4 |
| warm-echo | all offered | p99 | 1.665132 | 1.561143 | 0.032905 | 3/0/4 |
| payload-64k | successful | p50 | 1.0331015 | 1.143487 | 0.1295835 | 2/0/5 |
| payload-64k | successful | p95 | 1.714139 | 1.848746 | 0.113297 | 2/0/5 |
| payload-64k | successful | p99 | 2.20236 | 2.421336 | 0.190987 | 2/0/5 |
| payload-64k | all offered | p50 | 1.114962 | 1.2384455 | 0.1404875 | 2/0/5 |
| payload-64k | all offered | p95 | 1.856458 | 1.943383 | 0.121797 | 2/0/5 |
| payload-64k | all offered | p99 | 2.286719 | 2.529843 | 0.230388 | 1/0/6 |
| payload-near-limit | successful | p50 | 1.542702 | 1.8856095 | 0.148663 | 1/0/6 |
| payload-near-limit | successful | p95 | 2.394669 | 2.602528 | 0.170862 | 2/0/5 |
| payload-near-limit | successful | p99 | 2.9996 | 2.966031 | 0.241542 | 3/0/4 |
| payload-near-limit | all offered | p50 | 1.6393075 | 2.0353615 | 0.17491 | 1/0/6 |
| payload-near-limit | all offered | p95 | 2.550228 | 2.752176 | 0.212791 | 1/0/6 |
| payload-near-limit | all offered | p99 | 3.187705 | 3.090948 | 0.208752 | 3/0/4 |

## RPC throughput and resource observations

Throughput is successful measured responses over first scheduled measured offer through last measured completion, including gaps. CPU ticks and RSS are the retained batch observation scope including warmup/observation, not per-call CPU or continuous instantaneous peak. Clock resolution is 100 ticks/s (10 ms/tick). Resource rows below are per-case process observations; server samples across its cases share one process and RSS maxima must not be summed.

| Case | Metric | Control | Candidate | Paired delta | L/E/H |
| --- | --- | --- | --- | --- | --- |
| warm-echo | successful responses/s | 1,190.457225 | 1,156.910385 | -47.90593 | 5/0/2 |
| warm-echo | server CPU ticks | 30 | 32 | 1 | 2/1/4 |
| warm-echo | server sampled RSS B | 25,944,064 | 26,030,080 | 122,880 | 3/0/4 |
| warm-echo | client CPU ticks | 15 | 16 | 1 | 2/1/4 |
| warm-echo | client sampled RSS B | 4,456,448 | 4,587,520 | 131,072 | 1/1/5 |
| payload-64k | successful responses/s | 745.702481 | 687.259664 | -73.437689 | 5/0/2 |
| payload-64k | server CPU ticks | 43 | 46 | 6 | 2/0/5 |
| payload-64k | server sampled RSS B | 28,614,656 | 28,319,744 | -8,192 | 4/0/3 |
| payload-64k | client CPU ticks | 27 | 29 | 4 | 2/0/5 |
| payload-64k | client sampled RSS B | 5,382,144 | 5,505,024 | 131,072 | 2/1/4 |
| payload-near-limit | successful responses/s | 518.919884 | 450.785712 | -26.959493 | 6/0/1 |
| payload-near-limit | server CPU ticks | 7 | 8 | 2 | 1/1/5 |
| payload-near-limit | server sampled RSS B | 28,614,656 | 28,348,416 | -8,192 | 4/0/3 |
| payload-near-limit | client CPU ticks | 3 | 4 | 0 | 0/5/2 |
| payload-near-limit | client sampled RSS B | 6,045,696 | 5,996,544 | -49,152 | 4/0/3 |

Sum of nonoverlapping server batch CPU observations: 571 → 617 ticks (5.71 → 6.17 s). This does not include unobserved process startup/teardown gaps.
Sum of nonoverlapping client batch CPU observations: 315 → 344 ticks (3.15 → 3.44 s). This does not include unobserved process startup/teardown gaps.

## Direct normal timings

Units: µs. Every row is based on seven 32-measured-call process distributions. Construction covers the owned request and boxed backend future. Full call covers construction start through contained report/future destruction; polling-only invoke is also shown. Backend setup and reclamation are the actual instrumented microsecond spans; backend total excludes outer context validation. These are direct factory calls, with no RPC, node or listener.
### Request construction

| Shape | Control p50 | Candidate p50 | Paired Δp50 | L/E/H | Control p95 | Candidate p95 | Paired Δp95 | L/E/H |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| warm-echo | 3.5855 | 4.096 | 0.2825 | 1/0/6 | 5.162 | 7.328 | -1.218 | 5/0/2 |
| payload-64k | 4.331 | 3.7295 | -0.3175 | 6/0/1 | 7.265 | 7.368 | -0.96 | 5/0/2 |
| payload-near-limit | 6.218 | 5.059 | -1.181 | 6/0/1 | 9.233 | 11.082 | -0.428 | 4/0/3 |
| context-small | 5.0375 | 4.0065 | -0.4835 | 5/0/2 | 12.015 | 4.999 | -2.533 | 6/0/1 |
| context-64k | 6.9595 | 6.868 | 0.0895 | 3/0/4 | 12.595 | 11.752 | -3.071 | 4/0/3 |
| context-near-limit | 21.0385 | 22.35 | -0.706 | 4/0/3 | 36.421 | 42.217 | -0.301 | 4/0/3 |

### Construction through return (full direct call)

| Shape | Control p50 | Candidate p50 | Paired Δp50 | L/E/H | Control p95 | Candidate p95 | Paired Δp95 | L/E/H |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| warm-echo | 69.1235 | 82.121 | 10.358 | 3/0/4 | 115.031 | 134.481 | -22.171 | 4/0/3 |
| payload-64k | 185.8405 | 186.2975 | 0.4225 | 3/0/4 | 297.898 | 304.223 | -13.315 | 4/0/3 |
| payload-near-limit | 284.1985 | 292.5615 | 8.7575 | 3/0/4 | 487.67 | 471.013 | 6.77 | 3/0/4 |
| context-small | 122.7495 | 98.3135 | -9.469 | 5/0/2 | 256.674 | 166.816 | -88.71 | 6/0/1 |
| context-64k | 116.108 | 111.337 | -2.531 | 4/0/3 | 187.495 | 239.174 | -0.647 | 4/0/3 |
| context-near-limit | 154.405 | 125.3155 | -30.9185 | 5/0/2 | 211.061 | 311.998 | 40.561 | 3/0/4 |

### Invoke polling through return

| Shape | Control p50 | Candidate p50 | Paired Δp50 | L/E/H | Control p95 | Candidate p95 | Paired Δp95 | L/E/H |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| warm-echo | 65.123 | 76.838 | 10.241 | 3/0/4 | 109.408 | 128.168 | -22.195 | 4/0/3 |
| payload-64k | 181.6835 | 182.433 | 1.4195 | 2/0/5 | 288.9 | 296.188 | -9.675 | 4/0/3 |
| payload-near-limit | 278.036 | 287.7695 | 10.6805 | 3/0/4 | 481.879 | 466.151 | 11.267 | 3/0/4 |
| context-small | 117.8255 | 94.2745 | -8.888 | 5/0/2 | 240.783 | 162.047 | -86.354 | 6/0/1 |
| context-64k | 109.1405 | 104.1395 | -2.656 | 4/0/3 | 179.471 | 233.253 | 2.275 | 3/0/4 |
| context-near-limit | 131.6835 | 102.7725 | -30.2575 | 5/0/2 | 190.665 | 263.955 | 33.736 | 3/0/4 |

### Backend setup

| Shape | Control p50 | Candidate p50 | Paired Δp50 | L/E/H | Control p95 | Candidate p95 | Paired Δp95 | L/E/H |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| warm-echo | 15 | 18 | 3 | 2/1/4 | 32 | 31 | 1 | 3/0/4 |
| payload-64k | 76.5 | 79 | 1 | 2/1/4 | 121 | 127 | -10 | 4/0/3 |
| payload-near-limit | 132 | 135.5 | 8 | 1/1/5 | 187 | 188 | 1 | 3/0/4 |
| context-small | 35 | 28 | -2 | 5/0/2 | 63 | 51 | -8 | 4/0/3 |
| context-64k | 33.5 | 30.5 | -1 | 4/0/3 | 52 | 47 | -3 | 4/0/3 |
| context-near-limit | 53.5 | 33.5 | -20 | 7/0/0 | 81 | 61 | -25 | 6/0/1 |

### Activation resource reclamation

| Shape | Control p50 | Candidate p50 | Paired Δp50 | L/E/H | Control p95 | Candidate p95 | Paired Δp95 | L/E/H |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| warm-echo | 17 | 20 | 1 | 2/1/4 | 33 | 31 | -2 | 4/0/3 |
| payload-64k | 22 | 22.5 | -1 | 4/0/3 | 39 | 43 | 7 | 3/0/4 |
| payload-near-limit | 25 | 25 | 1 | 3/0/4 | 62 | 48 | -15 | 5/0/2 |
| context-small | 24 | 19 | -2 | 4/0/3 | 36 | 33 | -2 | 4/0/3 |
| context-64k | 22 | 22 | 1 | 3/0/4 | 35 | 51 | 8 | 2/0/5 |
| context-near-limit | 20 | 20.5 | -0.5 | 4/1/2 | 37 | 45 | -8 | 4/0/3 |

## Direct normal process CPU and RSS

Whole owned-process CPU uses serial RUSAGE_CHILDREN and includes preparation, all warmups/measured calls, both proofs, validation and holds. It cannot be assigned to individual shapes or divided into an attributed per-call cost. RSS is process memory; it is not raw-vector ownership or selected heap.

| Metric | Control | Candidate | Paired delta | L/E/H |
| --- | --- | --- | --- | --- |
| whole process CPU ms | 217.734 | 212.386 | -6.598 | 4/0/3 |
| user CPU ms | 184.569 | 189.217 | 3.739 | 3/0/4 |
| system CPU ms | 26.017 | 29.362 | 4.141 | 2/0/5 |
| maximum observed RSS B | 22,659,072 | 23,019,520 | 286,720 | 3/0/4 |
| kernel high-water RSS B | 22,671,360 | 23,019,520 | 286,720 | 3/0/4 |
| completion RSS B | 22,659,072 | 23,019,520 | 286,720 | 3/0/4 |

control normal total owned-process CPU: 1.473127 s across seven children.
candidate normal total owned-process CPU: 1.550678 s across seven children.

## Separate whole-process allocation observations

One pair per shape; nine calls per process (one warmup + eight measured), plus its one selected-component preparation, input decoding, evidence writing and runtime lifetime. These are complete whole-process totals from raw chronological replay. They are not invocation-only or per-call counts. A single pair supplies no distribution or repeatability claim. Peak live bytes are simultaneous live allocation bytes, not summed bytes.

| Shape | Allocation count C→N (Δ) | Allocated B C→N (Δ) | Peak live B C→N (Δ) | Remaining live B C→N (Δ) | Remaining allocations C→N (Δ) |
| --- | --- | --- | --- | --- | --- |
| warm-echo | 57,869 → 57,645 (-224) | 28,952,933 → 28,935,295 (-17,638) | 2,780,262 → 2,780,270 (8) | 63,364 → 63,364 (0) | 423 → 423 (0) |
| payload-64k | 57,855 → 57,631 (-224) | 33,669,084 → 33,651,463 (-17,621) | 2,780,270 → 2,780,278 (8) | 63,364 → 63,364 (0) | 423 → 423 (0) |
| payload-near-limit | 57,855 → 57,631 (-224) | 37,568,816 → 37,551,173 (-17,643) | 2,780,298 → 2,780,306 (8) | 63,364 → 63,364 (0) | 423 → 423 (0) |
| context-small | 87,174 → 86,932 (-242) | 45,679,032 → 45,659,437 (-19,595) | 3,087,092 → 3,087,100 (8) | 63,364 → 63,364 (0) | 423 → 423 (0) |
| context-64k | 87,165 → 86,923 (-242) | 47,246,451 → 46,638,169 (-608,282) | 3,087,084 → 3,087,092 (8) | 63,364 → 63,364 (0) | 423 → 423 (0) |
| context-near-limit | 87,167 → 86,925 (-242) | 56,586,847 → 52,129,471 (-4,457,376) | 3,087,112 → 3,087,120 (8) | 63,364 → 63,364 (0) | 423 → 423 (0) |

Selected constructor/poll attribution is **unavailable in all 12 profiles** despite both exact nm symbol proofs being present. Each payload profile has 36 unresolved allocation records and each context profile has 882; the retained diagnostic identified unresolved fiber frames. The retained union/frame counts, allocated bytes, simultaneous peaks and remaining bytes are null. Do not substitute partial observed named counts, report zero selected allocation, divide whole-process totals by nine, or claim a complete selected/per-call allocation saving.

## Ownership and cleanup checks in the aggregate

control: all 14 normal proofs retain the actual `owner_scope_exit` order; seven cancellation acknowledgements and seven explicit pending-future destructions. Candidate raw capacity is released before guest dispatch; control retains it into the pending guest call.
candidate: all 14 normal proofs retain the actual `before_guest_call` order; seven cancellation acknowledgements and seven explicit pending-future destructions. Candidate raw capacity is released before guest dispatch; control retains it into the pending guest call.
All 26 direct children report successful factory shutdown, two joined/zero live compiler workers, zero independent prepared-runtime populations and zero live raw-input owners/capacity after shutdown. All 14 external arms report joined cleanup drivers, zero transient cleanup slots and no handoffs/fallbacks/timeouts/panics. These claims do not equate bounded history with live owners or direct future destruction with standalone cell reuse.

## Original summary file hashes

- `backend-aggregate.json`: 746,326 B; `sha256:0448bedf4c8e8016f145465bfb6e257264f0c411f05701cf868a4c263b676c8c`.
- `backend-backend-builds.json`: 92,038 B; `sha256:a5c20ec7c7eac4b78e30fcd69c68e7842946b16017d0ca76b1ceefe0f6b31de5`.
- `backend-suite.json`: 439,997 B; `sha256:655317a827fddf7bb5ab509214e078157012df2c8c2eba01fa0481be70efcb57`.
- `rpc-aggregate.json`: 1,196,795 B; `sha256:e16d09371b0d17c36a260e4b3696f0415ea8d620b03eafc2842633ddf9c7aee4`.
- `rpc-revision-builds.json`: 251,107 B; `sha256:348875a4b13b04c91a0b5a384bfca4a9ba7b78caf0737437343161161342a017`.
- `rpc-suite.json`: 638,316 B; `sha256:cee6ae2501d89496ed7acefd00ae184ab49d14e869933ee6b2d5dd604ef46e0d`.

## RPC replication and combined results

Both complete campaigns are retained. This addendum recomputes process-level quantiles and paired differences from their aggregates; it does not pool individual calls, select the more favorable campaign, establish equivalence, or claim a second raw/archive replay. The campaign records a predeclared 60 s interval without owned jobs before replication; that does not establish thermal, scheduler or shared-host isolation.

The first campaign is the original RPC full-02 evidence in the primary RPC package; the second is the RPC diagnostic package. The six-case direct/backend campaign is unchanged and is not replicated here.

Both use candidate/harness `2bd245269ae113600f591492d2780ac4bc4467ed` and control `1f01544586fccee29da3423133928324ea2b0a5f`. The exact build receipt hash, each retained server/client/CLI build object, and protocol plan match between campaigns.

First RPC collection: 37.968771894 s; replication: 35.674141699 s. These exclude completed builds and do not include the intervening idle/setup interval.

Each campaign has 12,936 offers and 70 seed/server/client owners. Combined: 25,872 offers and 140 owners, with 14 matched pairs per case. Per arm, combined measured denominators are 5,600 warm-echo, 5,600 payload-64k and 560 payload-near-limit; 1,176 warmups per arm remain outside latency quantiles. All offered outcomes stay in their denominators.

first actual offered outcomes, including warmup: `{'success': 12936}`.
replication actual offered outcomes, including warmup: `{'success': 12936}`.

## Result and interpretation

The larger-payload paired p50 changes reverse sign in replication, while warm-echo remains positive. Across both campaigns, paired p50 still increases in every case:
- warm-echo: 0.6027605 → 0.6301945; +0.037451; 5/0/9 (control → candidate arm medians; paired delta; lower/equal/higher).
- payload-64k: 1.04741775 → 1.082378; +0.08555275; 6/0/8 (control → candidate arm medians; paired delta; lower/equal/higher).
- payload-near-limit: 1.56256275 → 1.629616; +0.06182325; 6/0/8 (control → candidate arm medians; paired delta; lower/equal/higher).

Thus the evidence does not establish a general RPC speedup or prove that the earlier regression disappeared. Repeated warm-echo slowdown remains visible. Larger payloads show campaign-sensitive results, with small majorities of positive p50 differences across all 14 pairs. Read p95/p99 and all-offered timing separately, including adverse tails. Changes cannot be attributed to a particular production edit from these timing observations alone.

## Campaign and combined paired tables

Each cell is control → candidate arm median; median(candidate − control); L/E/H. Each arm median summarizes seven process quantiles within a campaign, or 14 across both. The paired statistic uses matching repetitions within each campaign. L/E/H counts lower/equal/higher candidate values; lower favors latency/CPU/RSS and higher favors responses/s. Difference of arm medians is not the median paired change.

Successful latency starts at actual dispatch; all-offered elapsed starts at scheduled offer and includes dispatch delay. Throughput uses first scheduled measured offer through last completion. CPU is the actual before/after batch observation, including warmup/observation, at 100 ticks/s (10 ms/tick). RSS is maximum observed within that batch, not instantaneous peak, allocation size, or live raw ownership.
### warm-echo

| Metric | First campaign, n=7 | Replication, n=7 | Combined, n=14 |
| --- | --- | --- | --- |
| success p50 ms | 0.606531 → 0.636752; +0.0509345; 3/0/4 | 0.59899 → 0.6229575; +0.0239675; 2/0/5 | 0.6027605 → 0.6301945; +0.037451; 5/0/9 |
| success p95 ms | 1.128734 → 1.16523; +0.055214; 3/0/4 | 1.065204 → 1.115321; +0.037371; 0/0/7 | 1.0887075 → 1.1518435; +0.0462925; 3/0/11 |
| success p99 ms | 1.603577 → 1.44895; +0.040172; 3/0/4 | 1.339185 → 1.482665; +0.14823; 3/0/4 | 1.4183335 → 1.4658075; +0.041207; 6/0/8 |
| offered p50 ms | 0.682612 → 0.7122075; +0.045081; 2/0/5 | 0.6643465 → 0.6861525; +0.021806; 2/0/5 | 0.67347925 → 0.69982875; +0.0334435; 4/0/10 |
| offered p95 ms | 1.253956 → 1.248641; +0.021034; 3/0/4 | 1.197603 → 1.251495; +0.034729; 1/0/6 | 1.199353 → 1.250068; +0.0321385; 4/0/10 |
| offered p99 ms | 1.665132 → 1.561143; +0.032905; 3/0/4 | 1.428582 → 1.550266; +0.121684; 2/0/5 | 1.5185735 → 1.5557045; +0.039563; 5/0/9 |
| responses/s | 1,190.457225 → 1,156.910385; -47.90593; 5/0/2 | 1,225.21957 → 1,203.324538; -28.85785; 5/0/2 | 1,215.507131 → 1,180.117462; -38.38189; 10/0/4 |
| server CPU ticks | 30 → 32; +1; 2/1/4 | 29 → 30; +2; 1/1/5 | 29 → 30.5; +1.5; 3/2/9 |
| server sampled RSS B | 25,944,064 → 26,030,080; +122,880; 3/0/4 | 26,075,136 → 25,821,184; -122,880; 5/0/2 | 26,009,600 → 25,989,120; -122,880; 8/0/6 |
| client CPU ticks | 15 → 16; +1; 2/1/4 | 15 → 15; 0; 1/4/2 | 15 → 15.5; 0; 3/5/6 |
| client sampled RSS B | 4,456,448 → 4,587,520; +131,072; 1/1/5 | 4,587,520 → 4,456,448; -131,072; 4/1/2 | 4,521,984 → 4,587,520; +65,536; 5/2/7 |

### payload-64k

| Metric | First campaign, n=7 | Replication, n=7 | Combined, n=14 |
| --- | --- | --- | --- |
| success p50 ms | 1.0331015 → 1.143487; +0.1295835; 2/0/5 | 1.0861565 → 1.012977; -0.0617425; 4/0/3 | 1.04741775 → 1.082378; +0.08555275; 6/0/8 |
| success p95 ms | 1.714139 → 1.848746; +0.113297; 2/0/5 | 1.783439 → 1.682737; -0.190081; 4/0/3 | 1.7551785 → 1.7937895; +0.0942995; 6/0/8 |
| success p99 ms | 2.20236 → 2.421336; +0.190987; 2/0/5 | 2.093942 → 2.177138; -0.209406; 4/0/3 | 2.188799 → 2.3518315; +0.101714; 6/0/8 |
| offered p50 ms | 1.114962 → 1.2384455; +0.1404875; 2/0/5 | 1.172853 → 1.0993265; -0.0565805; 4/0/3 | 1.12744075 → 1.16940825; +0.0939675; 6/0/8 |
| offered p95 ms | 1.856458 → 1.943383; +0.121797; 2/0/5 | 1.903465 → 1.771157; -0.215782; 4/0/3 | 1.8799615 → 1.9006075; +0.0695575; 6/0/8 |
| offered p99 ms | 2.286719 → 2.529843; +0.230388; 1/0/6 | 2.27609 → 2.247075; -0.129792; 4/0/3 | 2.2814045 → 2.488941; +0.1768725; 5/0/9 |
| responses/s | 745.702481 → 687.259664; -73.437689; 5/0/2 | 716.620366 → 760.084373; +47.855854; 3/0/4 | 731.161424 → 717.444176; -52.240621; 8/0/6 |
| server CPU ticks | 43 → 46; +6; 2/0/5 | 44 → 43; -3; 4/0/3 | 43.5 → 45.5; +2.5; 6/0/8 |
| server sampled RSS B | 28,614,656 → 28,319,744; -8,192; 4/0/3 | 28,684,288 → 28,413,952; -258,048; 6/0/1 | 28,647,424 → 28,366,848; -176,128; 10/0/4 |
| client CPU ticks | 27 → 29; +4; 2/0/5 | 27 → 25; 0; 3/1/3 | 27 → 28; +1.5; 5/1/8 |
| client sampled RSS B | 5,382,144 → 5,505,024; +131,072; 2/1/4 | 5,373,952 → 5,468,160; +131,072; 3/0/4 | 5,378,048 → 5,488,640; +131,072; 5/1/8 |

### payload-near-limit

| Metric | First campaign, n=7 | Replication, n=7 | Combined, n=14 |
| --- | --- | --- | --- |
| success p50 ms | 1.542702 → 1.8856095; +0.148663; 1/0/6 | 1.5675565 → 1.517652; -0.1789875; 5/0/2 | 1.56256275 → 1.629616; +0.06182325; 6/0/8 |
| success p95 ms | 2.394669 → 2.602528; +0.170862; 2/0/5 | 2.465975 → 2.231511; -0.111187; 5/0/2 | 2.430322 → 2.432783; +0.0371185; 7/0/7 |
| success p99 ms | 2.9996 → 2.966031; +0.241542; 3/0/4 | 2.744401 → 2.458657; -0.228585; 4/0/3 | 2.8781695 → 2.7297365; -0.032068; 7/0/7 |
| offered p50 ms | 1.6393075 → 2.0353615; +0.17491; 1/0/6 | 1.6523205 → 1.609963; -0.1840365; 5/0/2 | 1.645814 → 1.7161625; +0.08228975; 6/0/8 |
| offered p95 ms | 2.550228 → 2.752176; +0.212791; 1/0/6 | 2.565417 → 2.306959; -0.146611; 5/0/2 | 2.5578225 → 2.559956; +0.0864665; 6/0/8 |
| offered p99 ms | 3.187705 → 3.090948; +0.208752; 3/0/4 | 2.823302 → 2.599473; -0.256187; 4/0/3 | 2.9738385 → 2.8220405; -0.0090755; 7/0/7 |
| responses/s | 518.919884 → 450.785712; -26.959493; 6/0/1 | 523.903394 → 551.961428; +34.467396; 2/0/5 | 521.411639 → 492.886377; -17.264726; 8/0/6 |
| server CPU ticks | 7 → 8; +2; 1/1/5 | 7 → 6; 0; 3/3/1 | 7 → 7; 0; 4/4/6 |
| server sampled RSS B | 28,614,656 → 28,348,416; -8,192; 4/0/3 | 28,684,288 → 28,430,336; -258,048; 5/0/2 | 28,647,424 → 28,422,144; -98,304; 9/0/5 |
| client CPU ticks | 3 → 4; 0; 0/5/2 | 3 → 3; 0; 3/4/0 | 3 → 3; 0; 3/9/2 |
| client sampled RSS B | 6,045,696 → 5,996,544; -49,152; 4/0/3 | 6,021,120 → 5,898,240; -122,880; 4/0/3 | 6,027,264 → 5,994,496; -59,392; 8/0/6 |

## Execution-order strata

Actual retained run order is control-first for repetitions 1/3/5/7 and candidate-first for 2/4/6. Each campaign therefore has four control-first and three candidate-first pairs; combined there are eight and six. Each cell below shows paired median delta; L/E/H, using the same metric units as above. These small deterministic strata are descriptive, not an order-adjusted causal estimate. No stratum is removed from combined results.
### warm-echo

| Metric | First C-first n=4 | First N-first n=3 | Rep C-first n=4 | Rep N-first n=3 | Combined C-first n=8 | Combined N-first n=6 |
| --- | --- | --- | --- | --- | --- | --- |
| success p50 ms | +0.03112625; 2/0/2 | +0.0509345; 1/0/2 | +0.05755475; 1/0/3 | +0.009825; 1/0/2 | +0.0573; 3/0/5 | +0.01689625; 2/0/4 |
| success p95 ms | +0.0289505; 2/0/2 | +0.055214; 1/0/2 | +0.14047; 0/0/4 | +0.025595; 0/0/3 | +0.094447; 2/0/6 | +0.031483; 1/0/5 |
| success p99 ms | -0.142843; 2/0/2 | +0.040172; 1/0/2 | +0.2596115; 0/0/4 | -0.063642; 3/0/0 | +0.1032355; 2/0/6 | -0.056166; 4/0/2 |
| offered p50 ms | +0.03621525; 1/0/3 | +0.045081; 1/0/2 | +0.05693475; 1/0/3 | +0.0124185; 1/0/2 | +0.05693475; 2/0/6 | +0.01711225; 2/0/4 |
| offered p95 ms | +0.0292585; 2/0/2 | +0.021034; 1/0/2 | +0.155682; 0/0/4 | +0.022634; 1/0/2 | +0.0935545; 2/0/6 | +0.021834; 2/0/4 |
| offered p99 ms | -0.12129; 2/0/2 | +0.032905; 1/0/2 | +0.243678; 0/0/4 | -0.088964; 2/0/1 | +0.1090235; 2/0/6 | -0.043164; 3/0/3 |
| responses/s | -48.017422; 3/0/1 | -47.90593; 2/0/1 | -117.804306; 3/0/1 | -25.441916; 2/0/1 | -99.126202; 6/0/2 | -27.149883; 4/0/2 |
| server CPU ticks | +1.5; 1/1/2 | +1; 1/0/2 | +4.5; 1/0/3 | +1; 0/1/2 | +3; 2/1/5 | +1; 1/1/4 |
| server sampled RSS B | -188,416; 3/0/1 | +258,048; 0/0/3 | -225,280; 3/0/1 | -122,880; 2/0/1 | -188,416; 6/0/2 | +155,648; 2/0/4 |
| client CPU ticks | +1; 1/1/2 | +1; 1/0/2 | +0.5; 0/2/2 | 0; 1/2/0 | +0.5; 1/3/4 | 0; 2/2/2 |
| client sampled RSS B | +131,072; 0/1/3 | +131,072; 1/0/2 | -196,608; 3/0/1 | 0; 1/1/1 | +65,536; 3/1/4 | +65,536; 2/1/3 |

### payload-64k

| Metric | First C-first n=4 | First N-first n=3 | Rep C-first n=4 | Rep N-first n=3 | Combined C-first n=8 | Combined N-first n=6 |
| --- | --- | --- | --- | --- | --- | --- |
| success p50 ms | +0.03951975; 2/0/2 | +0.165394; 0/0/3 | +0.0876235; 1/0/3 | -0.1038885; 3/0/0 | +0.08555275; 3/0/5 | +0.0339205; 3/0/3 |
| success p95 ms | +0.0306665; 2/0/2 | +0.293307; 0/0/3 | +0.1352435; 1/0/3 | -0.280125; 3/0/0 | +0.098743; 3/0/5 | -0.038392; 3/0/3 |
| success p99 ms | -0.0101405; 2/0/2 | +0.352786; 0/0/3 | +0.372771; 1/0/3 | -0.516113; 3/0/0 | +0.1313855; 3/0/5 | -0.0092095; 3/0/3 |
| offered p50 ms | +0.051355; 2/0/2 | +0.187318; 0/0/3 | +0.0974915; 1/0/3 | -0.0892175; 3/0/0 | +0.0939675; 3/0/5 | +0.0419535; 3/0/3 |
| offered p95 ms | -0.004655; 2/0/2 | +0.253812; 0/0/3 | +0.1238275; 1/0/3 | -0.312804; 3/0/0 | +0.0695575; 3/0/5 | -0.0469925; 3/0/3 |
| offered p99 ms | +0.0703325; 1/0/3 | +0.357889; 0/0/3 | +0.3415465; 1/0/3 | -0.455989; 3/0/0 | +0.1787655; 2/0/6 | +0.050298; 3/0/3 |
| responses/s | -14.462482; 2/0/2 | -114.7931; 3/0/0 | -53.362282; 3/0/1 | +61.156881; 0/0/3 | -52.240621; 5/0/3 | -28.455854; 3/0/3 |
| server CPU ticks | 0; 2/0/2 | +8; 0/0/3 | +4; 1/0/3 | -5; 3/0/0 | +2.5; 3/0/5 | +2; 3/0/3 |
| server sampled RSS B | +71,680; 1/0/3 | -32,768; 3/0/0 | -176,128; 3/0/1 | -356,352; 3/0/0 | -79,872; 4/0/4 | -307,200; 6/0/0 |
| client CPU ticks | +1; 2/0/2 | +6; 0/0/3 | +1.5; 1/0/3 | -2; 2/1/0 | +1.5; 3/0/5 | +2.5; 2/1/3 |
| client sampled RSS B | +182,272; 0/1/3 | -28,672; 2/0/1 | -18,432; 2/0/2 | +262,144; 1/0/2 | +133,120; 2/1/5 | +51,200; 3/0/3 |

### payload-near-limit

| Metric | First C-first n=4 | First N-first n=3 | Rep C-first n=4 | Rep N-first n=3 | Combined C-first n=8 | Combined N-first n=6 |
| --- | --- | --- | --- | --- | --- | --- |
| success p50 ms | +0.117681; 0/0/4 | +0.647621; 1/0/2 | -0.197095; 3/0/1 | -0.1789875; 2/0/1 | +0.07951125; 3/0/5 | +0.00871075; 3/0/3 |
| success p95 ms | +0.124249; 1/0/3 | +0.494418; 1/0/2 | -0.2911855; 2/0/2 | -0.111187; 3/0/0 | +0.0835865; 3/0/5 | -0.064783; 4/0/2 |
| success p99 ms | +0.068959; 2/0/2 | +0.575437; 1/0/2 | -0.251092; 3/0/1 | +0.153135; 1/0/2 | -0.1180815; 5/0/3 | +0.364286; 2/0/4 |
| offered p50 ms | +0.1365745; 0/0/4 | +0.6734855; 1/0/2 | -0.16434175; 3/0/1 | -0.1840365; 2/0/1 | +0.09158675; 3/0/5 | +0.0391575; 3/0/3 |
| offered p95 ms | +0.177997; 0/0/4 | +0.585892; 1/0/2 | -0.277929; 2/0/2 | -0.146611; 3/0/0 | +0.120412; 2/0/6 | -0.1024385; 4/0/2 |
| offered p99 ms | +0.0559975; 2/0/2 | +0.638367; 1/0/2 | -0.2880275; 3/0/1 | +0.210091; 1/0/2 | -0.1051775; 5/0/3 | +0.424229; 2/0/4 |
| responses/s | -26.03733; 4/0/0 | -172.850231; 2/0/1 | +47.755038; 1/0/3 | +34.467396; 1/0/2 | -21.790944; 5/0/3 | -2.738735; 3/0/3 |
| server CPU ticks | +0.5; 1/1/2 | +2; 0/0/3 | 0; 1/2/1 | -2; 2/1/0 | 0; 2/3/3 | +1; 2/1/3 |
| server sampled RSS B | +71,680; 1/0/3 | -32,768; 3/0/0 | -229,376; 3/0/1 | -258,048; 2/0/1 | -79,872; 4/0/4 | -145,408; 5/0/1 |
| client CPU ticks | 0; 0/4/0 | +2; 0/1/2 | 0; 1/3/0 | -1; 2/1/0 | 0; 1/7/0 | 0; 2/2/2 |
| client sampled RSS B | +81,920; 1/0/3 | -278,528; 3/0/0 | +153,600; 1/0/3 | -417,792; 3/0/0 | +88,064; 2/0/6 | -352,256; 6/0/0 |

## Aggregate resource totals and preservation

CPU totals below sum distinct per-case observation intervals; server startup/teardown gaps are excluded. Do not sum RSS maxima across the three cases sharing a server process.
- first server: 571 → 617 ticks (5.71 → 6.17 s).
- first client: 315 → 344 ticks (3.15 → 3.44 s).
- replication server: 563 → 573 ticks (5.63 → 5.73 s).
- replication client: 317 → 316 ticks (3.17 → 3.16 s).

All aggregate/suite inputs were read without modification. Each displayed latency difference was checked against the matching campaign comparison records; both suite hashes match their aggregate references. Exact file hashes:

- first `rpc-suite.json`: 638,316 B; `sha256:cee6ae2501d89496ed7acefd00ae184ab49d14e869933ee6b2d5dd604ef46e0d`.
- first `rpc-aggregate.json`: 1,196,795 B; `sha256:e16d09371b0d17c36a260e4b3696f0415ea8d620b03eafc2842633ddf9c7aee4`.
- replication `suite.json`: 638,270 B; `sha256:4c22a605e3bc9808671f80aa68a446ffa1b1b3cb4a26fa4ea63697f041e4820f`.
- replication `aggregate.json`: 1,196,173 B; `sha256:fe86100aa00f3ebfe30d56f999e963735286aa37f547c9591cbdd658d78afc6e`.
