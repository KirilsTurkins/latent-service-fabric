# Phase 1 controlled historical/current comparison

The full paired experiment passed its evidence and cleanup checks: seven
independent pairs, 14 processes and 6,160 successful semantic Echo calls. It
compares the actual historical runtime with the current production standalone
node on the same observed Linux container host. It supplies the controlled
productionization observations requested by issue #94; it does not independently
complete every Phase 1 criterion.

The current backend total was higher in all seven pairs. Across process medians,
the historical arm measured 103 microseconds and the current arm 176 microseconds;
the median paired difference was +75 microseconds. These are descriptive
observations of the declared runtime changes and measurement surfaces. They do
not isolate the cost of one implementation change or establish a universal SLO.

## Source and retained evidence

| Identity | Historical control | Current candidate |
| --- | --- | --- |
| Source commit | `52ac47542a05c0a1263f78a14c04a5c2e6b761f3` | `e7e06f7d568617d0d54c9cc77c268d7bb034c035` |
| Source tree | `cac3ececdbd0b5734691c30c0283fccff169a5f5` | `744410de5def1083f8ef594e5032f9336317d012` |
| Dirty source | `false` | `false` |
| Executed binary bytes | 137,712,032 | 197,774,032 |
| Executed binary SHA-256 | `04b48d3a697b16ed95286ac69b327d8518b3124a58a8a2a9664040899634ca89` | `352ec30ca550f78488c13c42f255e7941019cf0b9ab5a3f6a64d86add2f73ef0` |
| Echo component bytes | 24,754 | 24,754 |
| Echo component SHA-256 | `c0239a7c3223867231efe0bc0a7de04761b6ad47d132622c5320d5ef2c708f7c` | `a45c2680dcbb6f5a67c532459cc2ff14daaa5b893f793b92eecec31c7488a694` |

[aggregate.json](aggregate.json) contains all per-process distributions,
per-pair differences, boundaries, identities and limitations. The
[archive manifest](raw-evidence.manifest.json) lists every unchanged file by
path, byte count and SHA-256. The [raw archive](raw-evidence.tar.gz) retains all
14 raw reports, the suite, process and cleanup receipts, original executables,
components, transmitted metadata, build receipts, logs, guest source proofs and
historical method source copies. This report is an accompanying interpretation,
not a replacement for those original records.

- Archive: 77,589,832 bytes;
  SHA-256 `27c8660cf6da586b9e0d6cbe2d4ea6c2e37a915083490f4beddc1aa1262da99c`.
- Expanded evidence: 168 files, 368,365,719 bytes.
- Aggregate: 172,576 bytes;
  SHA-256 `e7bb6af16d7a82f715660a16ae60bc4aaf270f6bfccdff65946f227bdda6acd2`.
- Original suite: 98,760 bytes;
  SHA-256 `804cfb9451cfe0221fa85f9a5a2220f7c7006acc94dabc37c5a7a33cbffc4e98`.

Packaging verified all file identities, bounded archive expansion, regular-file
extraction, byte-for-byte round trips, the outer aggregate and strict semantic
replay. It preserved the original measurement files and did not rerun guests.

## Controls, population and treatment

Both arms used Rust and Cargo 1.97.1, Wasmtime 47.0.3 and
`x86_64-unknown-linux-gnu`. Their release recipe used optimization level 3,
debug level 1, 16 codegen units, no LTO or incremental compilation, and the same
recorded path-remapping and linker settings. The recipe SHA-256 is
`16266aee2b730aac007d2ef6b7e5a74f8ce7391c69a0ffc1849011f30884414d`.

The observed host was an Intel Core i7-11850H, with 16 logical CPUs, Linux
`6.6.87.2-microsoft-standard-WSL2`, a Docker marker and WSL detection. The cgroup
CPU quota was `400000 100000`, equivalent to four CPUs, with cpuset `0-15`.
Historical `available_parallelism` independently reported four. Host memory was
33,233,743,872 bytes; the cgroup memory limit was `max`. `LD_PRELOAD` and
`MALLOC_CONF` were unset. CPU frequency policy observations were unavailable
as an empty policy map, and the systemd virtualization detector was unavailable;
the explicit Docker/WSL observations remain recorded. These are container
observations, not native-host calibration.

Every process prepared one Echo component once, then made 440 sequential calls.
The first 40 calls were the predetermined warmup prefix; all remaining 400 calls
were measured. There were 2,800 measured calls per arm and 560 warmup calls
overall. Pair order alternated control/candidate, then candidate/control. No
sample was excluded based on its observed timing. The 14 supervised process
windows totalled 27.093577 seconds; builds and the gaps between processes are
outside that total.

The semantic input and output were the same 25 UTF-8 bytes:
`phase0 targeted warm echo`. Both arms used the same per-call activation-ID
spelling, ten billion fuel, 16 MiB memory, a 1000 ms wall limit, 16384 log bytes,
two cells and three queue slots. The retained maintained Echo `component.rs`
and `logic.rs` sources match byte for byte. Each runtime used its own
ABI-compatible component, whose distinct identity is recorded above.

The declared treatment includes the historical typed facade versus current
dynamic dispatch, guest ABI, routing, admission, context, logging and accounting.
It also includes two historical runtime workers versus two invocation workers
and one control worker in the current node, and a native binary versus a libtest
collector. Historical cache capacity was one; current capacity was four, with
exactly one actual resident preparation in both arms. Current bounded status and
telemetry retention differ from the historical runner's post-call log clearing.
These differences are observed production and instrumentation changes, not
unrecorded equivalence assumptions.

## Timing observations

The first two numeric columns below are medians of the seven process medians.
The difference column is the median of seven within-pair candidate-minus-control
differences. The range preserves all seven paired differences. Therefore the
difference column need not equal the subtraction of the first two columns.
Values are microseconds except the host-call count row.

| Boundary | Control | Candidate | Paired difference | Paired difference range |
| --- | ---: | ---: | ---: | ---: |
| Initial component preparation, after engine construction | 31,597 | 34,710 | +833 | -6,782 to +4,469 |
| Backend setup | 44 | 71 | +30 | +12.5 to +33 |
| Guest call, including automatic canonical post-return | 32 | 66 | +33 | +29 to +39 |
| Host calls, subset of guest-call time | 0 | 17 | +17 | +16 to +18 |
| Host-call count | 2 | 2 | 0 | 0 |
| Post-call host accounting | 0 | 0 | 0 | 0 |
| Actual activation-resource reclamation | 21 | 27 | +7 | +6 to +9 |
| Outcome classification | 0 | 0 | 0 | 0 |
| Reusable proof | 0 | 0 | 0 | 0 |
| Backend total | 103 | 176 | +75 | +51 to +84 |
| Wider semantic invocation path, differing entrypoints | 135 | 1,459 | +1,330.5 | +1,224.5 to +1,389 |

Preparation was higher for the candidate in five pairs and lower in two. Setup,
guest call, host-call time, reclamation and backend total were higher in all
seven pairs. Equal zero-microsecond medians reflect timestamp quantization; they
do not prove that work or overhead is absent. A percentage against zero is
explicitly undefined in the aggregate.

The backend-total per-process p95 ranged from 158–194 microseconds for the
control and 304–343 for the candidate; p99 ranged from 210–252 and 387–564.
These are ranges across seven separate process distributions, not pooled
percentiles or confidence intervals. The aggregate retains the complete
per-process and paired statistics.

The wider semantic-invocation row deliberately has different physical
entrypoints: historical prepared-envelope execution through outcome and cell
disposition versus current persistent loopback RPC through terminal receipt.
It describes the wider product path and cannot be read as an isolated backend
regression or a pure scheduler/transport cost. Its per-process p95 ranges were
191–244 and 2,202–2,596 microseconds; p99 ranges were 269–322 and 2,807–3,354.

Guest-call timing includes automatic canonical post-return in both arms.
Host-call time is a subset and is never added to guest-call time. The named
post-return interval is subsequent host accounting. Historical summed cleanup,
current gaps between named intervals and residual timings are not combined into
a fabricated comparable cleanup total. Startup boundaries have different
exclusions and remain unmatched.

## Outcome, accounting and ownership evidence

Every one of the 6,160 calls returned the expected semantic string. CPU
consumption was 3,062 fuel and peak guest memory 1,179,648 bytes in both arms.
The historical log charge was 115 bytes per call; the current charge was 330
bytes. The latter reflects the current complete encoded record and trusted
correlation accounting, so the two log figures are not claimed to measure an
identical byte representation.

Each process created 440 fresh stores and returned per-call live store,
host-state, component-instance, temporary-buffer, cancellation and cell owners
to idle. Current cache hits increased from 1 through 440 with one miss and one
resident entry; explicit release then removed that entry. Every current receipt
retained the published release, revision and route generation 1, and its final
consumption matched the subsequent retained status. All current shutdown
receipts were clean, with zero transient owners, flushed telemetry and a joined
epoch helper. All 14 supervised processes exited successfully, were reaped, closed
their output readers and removed their owned temporary data.

Per-call process observations showed four threads and zero listeners in the
historical arm, and six threads and one listener in the current arm. These are
the actual process-with-collector observations, not a claim that all observed
threads are runtime workers. The historical collector retains a growing sample
vector; the current collector streams bounded JSON. Different probe,
serialization and retention costs affect inter-call spacing and possible cache
or thermal state. RSS therefore cannot establish an isolated runtime memory
saving. Alternating order reduces but does not remove temporal confounding.

## Replay and scope

From the repository root, verify the archive and all underlying evidence:

```sh
python3 tools/validate_phase1_archive.py \
  benchmarks/phase1/paired/2026-09-08-container-linux-e7e06f7
```

The verifier performs safe temporary extraction and reconstructs the aggregate
from the archived suite and original arm records. For already extracted raw
evidence, use `tools/validate_phase1_paired.py --aggregate /path/to/aggregate.json`.
The [method documentation](../../../../docs/testing/phase-1-controlled-comparison.md)
describes the fixed population, retained controls and per-metric boundaries.

The unchanged [August 30 native Phase 0 calibration](../../../phase0/calibration/native-linux-2026-08-30-52ac4754/)
remains a separate historical reference. This same-container experiment does
not replace it or turn its incompatible environment/input comparison into a
matched one. The historical targeted report continues to require a separate
full invariant proof; the selected warm experiment does not claim to rerun it.

The separate [full Phase 1 scale, soak and benchmark report](https://github.com/KirilsTurkins/latent-service-fabric/blob/e88b362f202b88ea62c681a1b0d48473d701cc2d/benchmarks/phase1/measurements/2026-09-08-container-linux-d72c99b6/REPORT.md)
contains the 100,000-release/deployment scale, repeated 100,000-activation mixed
soak and broader benchmark evidence. Neither that report nor this comparison
silently substitutes one workload for the other. The paired aggregate keeps
`phase1_completion: incomplete`; final issue/epic acceptance requires the
collective evidence and an explicit reconciliation.
