# Full Phase 1 measurements: container Linux, 2026-09-08

All eleven full-profile processes passed: one dormant-catalog scale run, three
mixed-workload soaks and seven independent benchmark runs. The suite attempted
**362,080 Invokes and 939,916 counted commands**. The retained
[aggregate](aggregate.json) reports measurement status `complete`; its separate
`phase1_completion` remains `incomplete`. The separate
[controlled historical/current comparison](../../paired/2026-09-08-container-linux-e7e06f7/REPORT.md)
and the [Phase 1 completion report](../../../../docs/phase-1-completion.md)
combine this receipt with the other required evidence.

The [raw archive](raw-evidence.tar.gz) retains every original evidence file,
including the exact executed ELF, all three component fixtures, normalized
publication inputs, all attempted runs and samples, logs, and process/data
cleanup receipts. No outliers were removed. Packaging and independent replay
did not rerun any guest workload.

## Identity and measurement scope

The clean measured source is `d72c99b6f3320572ed318226304f1039cf7c4b80`, tree
`d5df7561de3c2c194e212d18e5a6092c7ed190c0`. All eleven raw headers agree on source,
build, configuration, binary and fixture identities. The Cargo lock SHA-256 is
`4fef007f3c6b800f845659d62a319334a1e7428efc0e3fecc7182c88b9cc6669`.
The executed 197,010,104-byte ELF is retained as `reproduction/collector`, with
SHA-256 `f4baba64c13b7c590a2b11addbfe666b9e9925d04190712019f49f49b3942d44`.

The observed host is an Intel Core i7-11850H with 16 visible logical CPUs and a
four-CPU cgroup quota, running Linux kernel
`6.6.87.2-microsoft-standard-WSL2` with the Docker marker present. Reported host
memory is 33,233,743,872 bytes; the cgroup memory ceiling is `max`. CPU policy and
some virtualization probes were unavailable and remain explicitly unobserved.
These results are container observations and do not replace the historical
native Ryzen calibration.

The release build uses Rust/Cargo 1.97.1, Wasmtime 47.0.3 and the pinned
`phase0_release_cargo` recipe: optimization level 3, debug level 1, 16 codegen
units, LTO disabled, incremental compilation disabled, unwind panic handling
and recorded path remapping. `suite.json` and `identity.json` inside the archive
retain the complete observed build/environment fields.

Each disposable collector process composes the actual standalone node with its
fixed libtest and client overhead. Process resource observations include that
overhead. Configuration fixes two standard cells, queue capacity three, two
invocation workers, one control worker, four cache entries, at most 64 terminal
journal entries with a 20 MiB journal bound, and a telemetry sink bounded by
128 entries and 1 MiB. The pipeline queue capacity is 256. The archived header
contains the sanitized configuration; credentials are excluded.

## Dormant catalogs at four scales

Each checkpoint contains exactly the stated number of releases and deployments,
with 10,000 direct resolver timing samples. The empty baseline and every
checkpoint have one node process, six tasks/threads, 19 open descriptors, seven
socket descriptors referring to five unique sockets, one TCP listener and no
descendants. Fixed node topology is identical throughout. Both cells remain
available, with zero leases, queued work, quarantine, prepared entries and stores
created. Service-resident process/thread/listener counts remain zero.

| Releases and deployments | RSS bytes | Direct route median ns | Direct route p99 ns |
| ---: | ---: | ---: | ---: |
| 0 | 13,762,560 | - | - |
| 100 | 16,646,144 | 1,776 | 7,591 |
| 1,000 | 38,227,968 | 2,845 | 13,803 |
| 10,000 | 242,589,696 | 5,348 | 22,742 |
| 100,000 | 2,326,077,440 | 12,720.5 | 69,123 |

The p99 values use nearest rank within each 10,000-sample population. Catalog
metadata RSS grows substantially and is reported directly; zero dormant
execution allocation does not imply constant catalog memory. Scale setup uses
actual durable local publication and batched deployment application. Its timing
is distinct from management RPC timing. This run used zero Invokes, 140,004
counted commands and 1,157.898788284 seconds.

## Three mixed-workload reclamation runs

Each process performs 1,000 sequential warmup calls, followed by 100 measured
batches of 1,000 calls at offered concurrency two. Every measured population
contains 45,000 ordinary successes and 5,000 each of cancellation, context,
deadline, declared error, fresh-store, fuel exhaustion, accepted log, denied
log, malformed input, memory exhaustion and trap. Warmup is excluded from the
measured population and included in total attempted work.

The unchanged [measurement policy](measurement-policy.json) uses each process's
own idle baseline after the complete mixed-cycle warmup, a 67,108,864-byte RSS
growth allowance, a two-descriptor growth allowance and a ten-batch tail window.

| Run | Warm RSS bytes | Maximum idle RSS bytes | Final RSS bytes | Maximum growth | Final growth | Last-ten median minus warm | Last-ten minus first-ten median |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| soak-01 | 27,836,416 | 28,254,208 | 28,053,504 | 417,792 | 217,088 | 219,136 | 57,344 |
| soak-02 | 27,856,896 | 27,963,392 | 27,873,280 | 106,496 | 16,384 | -172,032 | -94,208 |
| soak-03 | 28,078,080 | 28,291,072 | 28,205,056 | 212,992 | 126,976 | 122,880 | 116,736 |

Last-ten RSS ranges are respectively 27,828,224–28,114,944;
27,430,912–27,873,280; and 28,028,928–28,286,976 bytes. Warm, maximum and final
descriptor counts are all 22. Across measured checkpoints, maximum tasks,
socket descriptors, unique sockets, listeners and descendants are 6/7/5/1/0.

All sampled transient backend owners, leases, quotas, journal reservations,
cancellation registrations and observer correlations return to zero. Journal
retention stays at or below 64 terminal entries and 890,929 bytes against the
20,971,520-byte bound. Sink retention stays at or below 107 entries and
1,046,106 bytes against 128 entries and 1,048,576 bytes. Sampled pipeline depth
is zero against capacity 256. Bounded retained state is expected and accounted.

| Run | Total attempted Invokes | Counted commands | Elapsed seconds |
| --- | ---: | ---: | ---: |
| soak-01 | 101,000 | 217,019 | 184.755711623 |
| soak-02 | 101,000 | 216,992 | 186.558374113 |
| soak-03 | 101,000 | 216,999 | 184.088406679 |

Every run satisfies the declared finite observation policy. This does not prove
arbitrary-duration leak freedom. General OS timer registrations are not
enumerated by the process probe; deadline/drop tests and the owned epoch
helper's shutdown provide separate ownership evidence.

## Seven independent benchmark runs

Each process retains 40 warmup calls, 400 samples per repeated boundary, one
initial engine-cold preparation, 400 cache-reset preparations, 400 cache-hit
preparations and 400 management publish/reapply pairs. Each attempts exactly
8,440 Invokes: 400 first calls, 400 warm calls, 800 offered-capacity calls, 2,000
cancellation-released queue calls, six fault populations of 400 and six
corresponding recovery populations of 400, plus warmup. All 403 idle checkpoints
per run satisfy owner and capacity checks. Final retained consumption matches
the immediate outcomes.

The following values are per-process median microseconds from the 400 `warm_rpc`
observations, with each timing boundary kept separate.

| Run | Commands | Elapsed seconds | RPC median | Backend median | Guest-call median | Resource-reclamation median |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| benchmark-01 | 21,267 | 46.817244839 | 1,541 | 164.5 | 64.5 | 28 |
| benchmark-02 | 21,274 | 49.698876830 | 1,615 | 187.5 | 73 | 30 |
| benchmark-03 | 21,267 | 47.430654625 | 1,549.5 | 175.5 | 68 | 29 |
| benchmark-04 | 21,271 | 46.846841438 | 1,485.5 | 169 | 65 | 28 |
| benchmark-05 | 21,276 | 47.239677267 | 1,501 | 172 | 67.5 | 28 |
| benchmark-06 | 21,272 | 47.738314060 | 1,525.5 | 171.5 | 65 | 28 |
| benchmark-07 | 21,275 | 48.263395637 | 1,573 | 175 | 68 | 28 |

The median of the seven run representatives is 1,541 us for warm RPC, 172 us for
backend total, 67.5 us for guest call and 28 us for resource reclamation. Initial
preparation is 32,762 us, cache-reset preparation 31,406.5 us and cache hit 58 us.
The 83,011 us maximum initial preparation remains in the evidence.

Guest-call timing includes safe canonical post-return; host-call time is a
subset. Current result framing falls outside the individually named
post-return/reclamation timers, so their sum does not measure complete cleanup.
A separate cell-disposition-only timer is unavailable. The timing definitions
and workload plans are documented in
[Phase 1 measurements](../../../../docs/testing/phase-1-measurements.md).

## Shutdown and historical comparison

All eleven summaries record clean shutdown, zero transient owners, flushed
telemetry and a joined epoch helper. Replay verifies parent process identity,
reaping and output-closure receipts, plus collector and parent witnesses that
the owned catalog data was removed. Large generated catalogs are not retained
as evidence; their actual publication receipts, counts and resource observations
are retained.

The [general historical comparison](comparison.json) preserves all **189
`not_comparable` observations and zero causal deltas** against the unchanged
August Phase 0 reference. Host, fixture/ABI, grant and measurement-boundary
differences remain explicit. The old native advisory bands cannot establish
“no detectable regression” for this container suite. Issue #94's separate
controlled same-environment historical/current warm-echo protocol
[passed all seven pairs](../../paired/2026-09-08-container-linux-e7e06f7/REPORT.md),
with the original binaries, components and all attempts retained. It reports
the measured production changes and their methodological limits separately;
this receipt alone does not close the Phase 1 gate.

## Verify and replay without executing workloads

From the repository root, using the repository's Python tooling:

```sh
python3 tools/validate_phase1_archive.py \
  benchmarks/phase1/measurements/2026-09-08-container-linux-d72c99b6
```

This verifies the compressed checksum and every member's path, type, size and
SHA-256 before safe temporary extraction, rechecks extracted bytes, and
regenerates the aggregate and comparison from their raw evidence. It executes
neither the retained ELF nor a guest. The package is ordinary gzip/USTAR and
contains 200 regular files, totaling 282,655,298 uncompressed file bytes: all
199 original files plus the unchanged policy. Filesystem timestamps, owners and
executable mode are normalized; file contents are byte exact.

The archive is 50,544,383 bytes, SHA-256
`f1537fdadfd9190c328a712de5d1720876a8bb178ee2d5ea2f6885d67631be1b`.
The [checksum sidecar](raw-evidence.tar.gz.sha256) and
[per-file manifest](raw-evidence.manifest.json) cover the full archive. The outer
aggregate, comparison and policy are byte-exact copies of their archived files.
The manifest records the policy file's byte hash; the aggregate separately
records its canonical JSON hash, which is also verified.

Packaging performed a complete safe extraction and raw-evidence replay before
publishing this directory. Twelve focused tests cover byte preservation,
deterministic archive output, malformed paths and links, oversized headers,
duplicate members and JSON fields, checksum and policy tampering, truncated or
appended data, bounds, and refusal to publish a package whose replay fails.
