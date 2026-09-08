# Pre-optimization standalone reference

The full reference is complete: **88,326 attempts and 245 independently owned
processes**, seven alternating pairs, all 16 cases per arm, and no incorrect
workload results. The retained process receipts cover 14 measured servers,
224 clients and seven LSF provisioning servers. Every ordinary measured workload succeeded. Budget and
saturation failures remain part of the measured population. This establishes
the starting point for the Phase 1 extension; it is not an optimization gain.

Measured source: `8bbc1fd3f529c79c5932a56e64f8891b6abbac38`; tree
`17b898c304cf3aadf36f06b5bacd4813c28e417e`. The checkout was clean before/after
build and collection. Actual executables, components, source/build controls,
all attempts and cleanup receipts are bound by the manifest and retained.

## Environment and comparison

Both arms ran as separate Linux processes inside the same Docker Linux
environment on WSL2, kernel 6.6.87.2, Intel Core i7-11850H, 16 visible logical
CPUs and a 4-CPU quota (`cpu.max: 400000 100000`). The guest reported
33,233,743,872 bytes of RAM and no local cgroup memory ceiling. This is a
declared container/VM reference, not a native-Linux bare-metal result. CPU
frequency policy was not controlled. Rust/Cargo 1.97.1, Wasmtime 47.0.3 and
the pinned release recipe are recorded in `aggregate.json`.

The external persistent client invokes shared pure Rust Echo, computation
and transformation logic compiled for native tonic and a real Wasm component.
LSF includes routing, scheduling, fresh-store isolation, capabilities, budgets
and lifecycle retention. Native omits those services. LSF has four cells, 64
queue slots, four cache slots, one preparation slot, two runtime workers and
two control workers. Native has four executing slots and two runtime workers.
Native fuel/memory consumption is unavailable, not zero. RPC framing,
authentication, connection reuse and valid output bytes match.

## Successful responses

Each value below is the median of the seven independent per-arm p50 or p99
values, in milliseconds; these are not pooled percentiles or confidence
intervals. Warmup is excluded. All successful ordinary populations are full.

| Case | Native p50 | Native p99 | LSF p50 | LSF p99 |
| --- | ---: | ---: | ---: | ---: |
| warm-echo | 0.191 | 0.529 | 0.960 | 2.023 |
| compute | 0.207 | 0.610 | 1.129 | 2.213 |
| transform | 0.217 | 0.652 | 1.326 | 2.528 |
| payload-64k | 0.409 | 1.059 | 1.367 | 2.646 |
| payload-near-limit | 0.643 | 1.500 | 1.947 | 3.365 |
| cache-working-set | 0.192 | 0.619 | 33.755 | 46.608 |

Each arm has 2,800 measured calls per ordinary case, 280 for the 120 KiB payload
and 700 for the five-component cache working set. The working set exceeds
LSF's four slots and exposes repeated preparation; native has no component
compiler/cache. The 120 KiB payload fits the 128 KiB lifting allowance, below
the separate 256 KiB JSON-string and 1 MiB RPC ceilings.

The warm Echo engineering target is p50≤1 ms and p99≤2 ms. The median p50
meets its target on this host; the 2.023 ms median p99 remains above target.
Seven repetitions do not establish a production SLO.

## Millisecond budgets and load

Budget success requires both a valid successful response and completion by
the original scheduled deadline. Late successful responses are misses.

| Budget | Native within budget | LSF within budget | LSF valid responses |
| --- | ---: | ---: | ---: |
| budget-1ms | 2798/2800 (99.93%) | 0/2800 (0.00%) | 0/2800 |
| budget-2ms | 2800/2800 (100.00%) | 2625/2800 (93.75%) | 2661/2800 |
| budget-5ms | 2800/2800 (100.00%) | 2800/2800 (100.00%) | 2800/2800 |
| budget-10ms | 2800/2800 (100.00%) | 2800/2800 (100.00%) | 2800/2800 |

The ≥99% warm 2 ms target remains unmet: LSF completed 93.75% within budget.
The 1 ms LSF population had no successful responses, so it has no successful
latency percentile. Rejection latency is never presented as a latency win.

| Offered load | Native successes/s | LSF successes/s | LSF valid responses |
| --- | ---: | ---: | ---: |
| concurrency-4 | 10145.6 | 2201.6 | 2800/2800 |
| concurrency-16 | 17538.6 | 2369.7 | 2800/2800 |
| concurrency-64 | 21278.5 | 2581.4 | 2800/2800 |
| rate-250 | 250.3 | 250.2 | 2800/2800 |
| rate-1000 | 999.9 | 998.2 | 2800/2800 |
| rate-4000 | 3995.5 | 2557.9 | 2073/2800 |

Throughput is the median observed successful-response rate over complete
measured-phase intervals, not a reciprocal latency. At 4,000 scheduled offers/s, LSF returned
2,073 valid responses from 2,800 offers; all 727 remaining offers were recorded
as client overload because the 64 in-flight slots were occupied. They were
not sent to the server. Dispatch lag remains retained. These short cases
show saturation behavior, not sustained infrastructure capacity.

## Startup, resources and reclamation

| Observation | Native | LSF |
| --- | ---: | ---: |
| Median process-to-ready, ms | 11.769 | 39.573 |
| Median process-to-first-response observation, ms | 60.341 | 121.086 |
| Median per-server maximum sampled RSS, MiB | 4.969 | 29.129 |

The first RPC after durable restart had a median 0.586 ms native and 34.998 ms
LSF, including LSF initial preparation. The process-to-first-response metric
is a parent-observed upper bound that also includes readiness observation,
client launch/connect and event delivery. It is not isolated compiler time,
container startup or image-pull time.

Resource intervals include client startup/connect, warmup and measured work
through completion observation. RSS peaks are 100 ms sampled maxima. Client
peak RSS stayed at or below 6 MiB in both arms. CPU ticks, I/O and shared
cgroup counters are retained separately; cgroup consumption cannot be
attributed wholly to one server. The 512 MiB journal allowance is a configured
ceiling for conservative reservations, not an allocation or measured RSS.

Cases share a server in fixed order, so earlier cache/journal state carries
forward. All measured LSF shutdown reports had zero quarantined cells and
zero live execution/queue/reservation owners, flushed telemetry and a joined
epoch helper. Native servers exited cleanly after draining. Every measured
and provisioning child was reaped with its output closed.

## Replay and retained diagnostic

The archive contains 2,003 unchanged files,
408,638,361 expanded bytes and 74,394,099 compressed bytes.
Archive SHA-256: `654142050ecb1c11e18c6717451dc9c19f59da08b8b9ee89cbd1e266b0c06e77`.

From the repository root:

```sh
python3 tools/validate_phase1_archive.py \
  benchmarks/optimization/reference/2026-09-08-container-linux-8bbc1fd
```

This independently verifies the bounded archive, all artifact hashes,
source/process associations, workload outputs, deadlines, population and
cleanup, then regenerates the exact retained aggregate.

The [earlier rejected attempt](../../diagnostics/2026-09-08-container-linux-7857e6c/REPORT.md)
is retained separately with its original replay tools. Its cache budget was
at the server maximum and could exceed that maximum after deadline rounding.
It contributes no substituted cases to this complete rerun.

Actual Docker and Kubernetes deployment comparisons remain tickets #111 and
#112. This same-environment native/LSF process comparison does not answer
those infrastructure questions. Original Phase 0/Phase 1 evidence is unchanged.
