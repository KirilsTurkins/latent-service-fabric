# Phase 1 optimization measurements

The [Phase 1 extension](https://github.com/KirilsTurkins/latent-service-fabric/issues/97)
uses a separate native Rust/tonic service and a standalone `latentd` process.
Both execute the same pure Rust Echo, bounded compute and structured transform
logic from `tools/optimization-workloads`. The maintained Wasm component wraps
those functions; the native reference uses their JSON framing adapter. The same
external client sends the same protobuf requests over one persistent connection
per case. Native means native code in the recorded environment, not bare metal.

The [clean pre-optimization reference](reference/2026-09-08-container-linux-8bbc1fd/REPORT.md)
retains seven alternating pairs and all 88,326 attempts. Its report includes
unmet latency/budget targets and links to the separately retained rejected
configuration attempt. Verify the complete archive with:

```sh
python3 tools/validate_phase1_archive.py \
  benchmarks/optimization/reference/2026-09-08-container-linux-8bbc1fd
```

Run the bounded smoke profile on Linux, including a declared Linux container:

```sh
python3 tools/run_optimization_benchmarks.py --profile smoke
```

The runner builds the pinned binaries and real component, publishes five actual
component identities, and starts independent measured servers. It owns all child
processes, bounds output and execution time, records clean shutdown, and retains
failed attempts and original logs. Output directories must be new and empty.
CI runs smoke; smoke validates the protocol and cannot establish performance.

Explicit full collection requires a clean source checkout:

```sh
python3 tools/run_optimization_benchmarks.py --profile full
python3 tools/validate_optimization_evidence.py target/optimization-benchmarks/full-.../suite.json \
  --check-aggregate target/optimization-benchmarks/full-.../aggregate.json
```

The full profile collects seven independent pairs, alternating arm order. Each
server serves the same fixed ordered case matrix: warm Echo, compute, transform,
64 KiB and near-transfer-limit payloads,1/2/5/10 ms deadlines, concurrency4/16/64,
scheduled arrivals at250/1000/4000 requests per second, and a five-component
working set against four cache slots. Closed-loop throughput uses whole-batch
elapsed time. Scheduled load records dispatch lag and explicit client overload
or expired arrivals; it never silently reduces the attempted population.

The120 KiB near-limit string stays below the current128 KiB Component Model
lifting allowance. The standalone RPC ceiling is1 MiB and the JSON string cap
is256 KiB. These are different limits. Results state effective configuration;
the benchmark does not raise product limits to make a payload succeed.

The first invocation after durable restart includes preparation. Process-to-first
response is a parent-observed upper bound that includes readiness observation,
client startup and connection setup. Raw client startup/connect and per-call
timings remain separate. This does not measure pure compiler time or image pull
time. Subsequent warm samples follow explicit warmup. The working-set case uses
five distinct valid component binaries with identical code and different custom
sections, so it exercises actual cache replacement.

Each attempt retains identity, outcome, response identity/hash, deadline and
timings, including failures and outliers. RPC latency begins after request
construction and includes channel readiness, encoding, network and server work;
client response hashing and output writing occur afterward. Scheduled-to-complete
latency also includes dispatch delay and retains undispatched offers. Successful
responses, all dispatched attempts and individual failure classes have separate
distributions. Paired successful-call deltas never substitute fast rejections
for successful responses. Resource snapshots distinguish the
server and client;100 ms RSS observations are sampled maxima. Shared local
cgroup CPU/memory/pressure counters are retained as raw observations and are not
attributed wholly to one service. CPU ticks and wall latency are distinct.

After completing and persisting its timed work, the client holds for100 ms so
the parent can sample its live memory before it exits. The parent ends the
resource interval when it receives that completion event. This observation
window is excluded from request and batch timings. Controller counters come
from the resolved runner cgroup; the recorded leaf limits do not establish
effective limits imposed by ancestors.

The fixture uses four cells and64 queue slots. Its512 MiB journal allowance
accommodates conservative accounting for68 reservations; this is a finite
retention ceiling, not a512 MiB allocation or RSS measurement. The runner clips
all measured child lifetimes to a shared execution deadline and reserves their
bounded output before starting each batch. Build time has a separate one-hour
watchdog. Source, lockfile and recipe identities are checked before/after build
and again after collection.

The native reference has authentication, bounded invocation admission and
deadline checks. LSF additionally performs catalog/routing, fresh Wasm isolation,
capability enforcement, fuel/memory accounting, scheduling and lifecycle/status
retention. These treatment differences are part of the comparison. They are not
silently equated. No failure data is discarded to claim a faster successful-call
latency. Valid workload outputs must match across both arms.

Cases run in a fixed order on the same server within each arm. Cache contents,
journal entries and any quarantined cells can therefore affect later cases.
Clean shutdown establishes reclaimed ownership; the retained quarantine count
separately describes lost serving capacity. Process resource intervals include
client startup, connection setup and warmup through the completion observation,
so their CPU deltas are not measured-only per-call costs. Native admission uses
four executing slots and two runtime workers; LSF also has64 queue slots and two
control workers. These configurations describe the compared systems explicitly.

This protocol supplies the baseline for optimization tickets. Real Docker and
Kubernetes deployment comparisons are tracked separately in
[#111](https://github.com/KirilsTurkins/latent-service-fabric/issues/111) and
[#112](https://github.com/KirilsTurkins/latent-service-fabric/issues/112).
Original Phase0 and Phase1 evidence remains immutable under `benchmarks/phase0`
and `benchmarks/phase1`. Engineering targets and their final evaluation belong to
the extension epic and final gate; protocol validation alone is not an
optimization result or a production capacity claim.
