# Transport interruption cleanup: release comparison

Historical raw archive payloads are omitted from this checkout. Results and
original validation records remain; recorded replay passes describe publication
checks. [Restore the exact historical package](../../../../docs/testing/benchmark-retention.md) before running raw
replay or extraction commands below. Set `restored_root` to its fresh restore
directory; manifests alone do not make the current directory replayable.

Both full suites completed and passed semantic replay. Their complete archives passed mandatory Linux replay and independent Windows replay.

Issue [#119](https://github.com/KirilsTurkins/latent-service-fabric/issues/119) adds bounded standalone ownership after a transport deadline or disconnect. Each accepted RPC reserves a finite cleanup slot. Ordinary completion refunds it; an interrupted RPC transfers its exact activation and slot to one node-owned driver, which continues native cleanup within a fixed allowance. Cell reuse still requires the backend's affirmative reusable disposition. Refusal, timeout or panic remains conservative.

In the release recovery pair, the candidate completed all 30 follow-up calls and kept all four cells reusable; the control completed 5 of 30 and exhausted its reusable capacity by offer 11. Ordinary warm RPC results were mixed, including higher all-offered p99 in four of seven pairs. This is a recovery improvement, not a universal warm-path speedup.

The original incoming and admitted deadlines remain authoritative. A raw disconnect is distinct from an accepted explicit Cancel. No replacement request, node restart or enlarged cell pool is used to obtain recovery.

## Sources and controlled execution

| Role | Exact source |
| --- | --- |
| Control | `62c543eb0babf1856a93f98ad815fb30fe644300` |
| Candidate and executed harness | `ee10b02037606b170ce53d51bdd4552d192412e0` |
| Candidate production checkpoint | `963207c6c3ccc3f5fd0da67b15571ece4d98fb52` |
| Merged #103 base | `0f1aefa00769186cf9a7c30bf850ad10c473823d` |

The control retains previous production behavior with the common recorder, collectors and replay support. Both references use byte-identical common inputs, the pinned Rust 1.97.1 / Wasmtime 47.0.3 release recipe, and the same owned source and target paths. The external client, CLI and component come from the identified common harness. The separate recovery collector uses the same generic component in both arms. Actual binaries, inputs and hashes remain in the build receipts.

Both nodes have four cells, 64 queue slots, four preparation jobs, two compiler workers and four cache entries. Invocation, control and client runtime sizes are fixed and recorded. The candidate adds one cleanup driver and 68 finite cleanup slots. The control's absent supervisor observation is unavailable, not zero work.

Collection ran in Docker/WSL2 Linux, kernel 6.6.87.2-microsoft-standard-WSL2, on an Intel Core i7-11850H with 16 logical CPUs and 33,233,743,872 bytes of host memory. The cgroup quota was `400000 100000` (four CPUs), effective cpuset `0-15`, and memory limit `max`. Process accounting used 100 Hz ticks. Shared cgroup counters do not isolate the service. These observations establish neither native-host production SLOs nor a Docker/Kubernetes deployment comparison.

## Fixed populations

| Package | Independent pairs | Per arm | Full total |
| --- | ---: | --- | ---: |
| External warm RPC | 7, alternating order | 1 prewarm + 40 warmup + 400 measured Echo calls | 6,174 offers; 5,600 measured |
| Recovery diagnostic | 1 | 61 offers and 125 commands | 122 offers; 250 commands |

Warm calls use the unchanged external client, one outstanding request and a 1,000 ms envelope. The 574 prewarm/warmup offers remain retained but are excluded from measured latency distributions. Measured owners are 14 servers and 28 clients; validation also covers 14 seed servers. Every failure remains in its offered population. Successful-response latency is conditional on success. All-offered elapsed time includes every offer, and throughput uses first scheduled offer through last completion.

Each recovery arm starts one fresh four-cell node and keeps it for all 61 offers:

- One generic identify prewarm.
- Three rounds of expiry and attempted disconnect at each of 1, 2, 5 and 10 ms. Each of these 24 interruptions is followed by identify.
- Five planned Running-triggered disconnects with 1,000 ms envelopes, each followed by identify. Candidate qualification requires five actual Running observations, client task aborts and joins, and successful follow-ups.
- One positive explicit Cancel and a final identify.

Short cases keep their original transport, caller and native limits. Early rejection does not prove Running interruption coverage. A response winning the planned-abort race remains its actual response. The longer positive cases test recovery beyond the four-cell capacity; they do not claim 1 ms Running execution. The control still attempts all 61 requests if it loses capacity. Both recovery profiles deliberately use one pair; smoke never qualifies as full publication evidence.

## Warm RPC results

All 6,174 warm offers succeeded with matching output, including all 2,800 measured calls per arm. The 56 validated process owners completed with retained cleanup receipts. Each table arm value is the median of seven process-level quantiles. The paired column is the median of the seven candidate-minus-control differences; it need not equal the difference of the arm medians.

| Latency, ms | Control | Candidate | Median paired change | Pairs lower / higher |
| --- | ---: | ---: | ---: | ---: |
| Successful-response p50 | 0.5947185 | 0.5966650 | -0.007425 | 4 / 3 |
| Successful-response p95 | 1.059463 | 1.065003 | -0.004709 | 4 / 3 |
| Successful-response p99 | 1.374964 | 1.347576 | -0.000626 | 4 / 3 |
| All-offered p50 | 0.6623520 | 0.6674825 | -0.006037 | 4 / 3 |
| All-offered p95 | 1.149643 | 1.144351 | -0.022202 | 4 / 3 |
| All-offered p99 | 1.482761 | 1.421928 | +0.013341 | 3 / 4 |

The all-offered p99 arm medians fell, but four paired differences increased. Those differences ranged from -0.087463 to +0.093617 ms. Successful-response p99 differences ranged from -0.070144 to +0.118577 ms. Throughput arm medians were 1,238.013756 and 1,238.952090 calls/s; the paired median change was -4.453102 calls/s, with three of seven pairs improving. These small, mixed observations do not establish a general warm performance gain or statistical equivalence.

| Observed warm resource | Control median | Candidate median | Median paired change | Pairs lower / equal / higher |
| --- | ---: | ---: | ---: | ---: |
| Server CPU, ticks | 25 | 25 | -1 | 4 / 1 / 2 |
| Client CPU, ticks | 15 | 15 | 0 | 2 / 3 / 2 |
| Maximum sampled server RSS, bytes | 25,804,800 | 26,066,944 | +65,536 | 2 / 0 / 5 |
| Maximum sampled client RSS, bytes | 4,456,448 | 4,456,448 | 0 | 3 / 2 / 2 |

Server CPU totals across the seven warm batches were 179 -> 174 ticks (1.79 -> 1.74 s); client totals were 103 ticks (1.03 s) in both arms. These intervals include the 40 warmup calls and observation work, not only the 400 measured calls. They are not per-call CPU estimates. RSS samples are not instantaneous allocation peaks. External timer counts are unavailable. Ordinary warm completions are not cleanup handoffs and cannot establish interruption recovery on their own.

## Recovery under original transport limits

Both arms retained all 61 offers and 125 commands. Every candidate checkpoint showed four available cells, no active leases or queued activations, and no quarantine. The control reached four quarantined cells by ordinal 11 and continued every planned request; the subsequent capacity failures remain in the population.

| Client-visible outcome / recovery proof | Control | Candidate |
| --- | ---: | ---: |
| Semantic success | 6 / 61 | 31 / 61 |
| Platform failure response | 51 / 61 | 7 / 61 |
| Transport failure | 2 / 61 | 9 / 61 |
| Confirmed client task abort and join | 2 / 61 | 14 / 61 |
| Successful follow-up identify | 5 / 30 | 30 / 30 |
| Actual Running drop among five longer cases | 0 / 5 | 5 / 5 |
| Final quarantined cells | 4 | 0 |

The success totals include one prewarm. The candidate's unsuccessful spin responses are the intended interruption/cancellation population, not failed follow-up calls. Retained native outcomes were 31 completed, six admission-rejected, 13 deadline-exceeded and 11 cancelled. The control retained six completed, six admission-rejected, three deadline-exceeded, one cancelled and 45 unavailable outcomes. Client transport outcomes and eventual native terminal states are separate observations.

For the following table, each mechanism has three offers per budget and arm. `P` means an actual platform failure response, `T` a transport failure, and `D` a confirmed client task abort/join. The Running column counts source Running observations across both mechanisms, six offers per arm.

| Original budget | Expiry outcomes, control -> candidate | Disconnect outcomes, control -> candidate | Actual Running, control -> candidate |
| --- | --- | --- | --- |
| 1 ms | 3 P -> 3 P | 3 P -> 3 P | 0 / 6 -> 0 / 6 |
| 2 ms | 2 P + 1 T -> 3 T | 2 P + 1 D -> 3 D | 2 / 6 -> 6 / 6 |
| 5 ms | 2 P + 1 T -> 3 T | 2 P + 1 D -> 3 D | 2 / 6 -> 6 / 6 |
| 10 ms | 3 P -> 3 T | 3 P -> 3 D | 0 / 6 -> 6 / 6 |

All six 1 ms attempts in each arm were admission-rejected before Running under the existing feasibility floor. They do not prove interruption of running work. The candidate did reach Running for all 18 short 2/5/10 ms interruption offers and recovered after each. The control's later short and long cases encountered lost capacity; their low work is not an equivalent successful workload.

All five longer candidate cases observed Running before dropping the RPC, then received a cancelled native terminal and released the cell. Each abort was joined, and each subsequent identify succeeded. The handoff slot was 0; distinct generations bind the five actual transfers:

| Offer ordinal | Slot generation | Client abort-to-join, ms | Handoff start to terminal publication, ms |
| --- | ---: | ---: | ---: |
| 49 | 50 | 0.109830 | 1.090179 |
| 51 | 52 | 0.118949 | 0.417265 |
| 53 | 54 | 0.106369 | 0.690378 |
| 55 | 56 | 0.107617 | 2.356114 |
| 57 | 58 | 0.122961 | 4.839956 |

The candidate's separate positive Cancel observed Running and returned Accepted; the control returned AlreadyTerminal after failing to reach Running. No extension of original deadlines or late accepted completion decision was recorded in either arm.

The candidate retained 23 activation-bound handoffs and 23 completed cleanup futures. Handoff-to-terminal publication ranged from 0.333059 to 4.839956 ms, with median 2.096054 ms. Actual native cleanup logs recorded 55 released and six no-cell dispositions. The control recorded six released, 51 no-cell and four abandoned dispositions. The candidate driver joined with accepting/alive false, no reserved/queued/running slots, no timeout/panic/fallback and failed false. The control's missing supervisor counters remain unavailable.

These source events mark the start of transferring ownership, before queue commit or driver polling. Terminal publication can precede future destruction and slot refund; publication timing alone is not full cleanup latency. The source Running records, matching activation/revision cleanup logs, healthy follow-ups, cell snapshots and final joined ownership together establish reusable recovery. The native grace is 100 ms and fixed handoff ceiling is 200 ms. The separate 250 ms acknowledgement observer extends neither. Its maximum observed wait was 2.199041 ms in control and 6.711949 ms in candidate, with no observation overrun.

## Recovery resources and limits

The complete recovery population, controls and drain consumed 42 -> 62 process CPU ticks (0.42 -> 0.62 s). This increase accompanies 5 -> 30 successful follow-ups and additional acknowledged native work; it is not a matched-completion CPU comparison. Manager sleep guards were armed 120 -> 165 times, completed 0 -> 10, dropped 120 -> 155, and ended with zero live guards. These counters do not count every Tokio, Tonic or OS timer.

Maximum sampled process RSS was 26,976,256 -> 27,656,192 bytes, an increase of 679,936 bytes. Both arms observed 13 OS threads, at most 24 FDs, eight socket references, five unique sockets, one listener and no descendants. These are 63 fixed node checkpoints per arm, including the common libtest and client runtimes, not continuous or allocator-level observations. The cleanup driver did not add an OS thread in this sample.

Both arms joined their compiler workers and epoch helper and ended with zero transient activation/backend ownership. Control quarantine remained four; candidate quarantine remained zero. Flushed bounded telemetry history retained 99 control and 106 candidate entries, so a blanket all-counters-zero claim would be wrong. This one pair proves the declared finite recovery population, not a statistical performance claim.

## Reproduction and retention

From the clean candidate/harness checkout, use the exact references above with:

```sh
python3 tools/run_optimization_revision_benchmarks.py --experiment recovery --profile full \
  --control-ref 62c543eb0babf1856a93f98ad815fb30fe644300 \
  --candidate-ref ee10b02037606b170ce53d51bdd4552d192412e0 \
  --harness-ref ee10b02037606b170ce53d51bdd4552d192412e0 \
  --target-root /workspace/optimization-recovery-builds \
  --output target/optimization-recovery/build-only-warm-01 \
  --backend-build-output target/optimization-recovery/build-only-recovery-01 --build-only
```

Before collection, copy each untouched build-only directory into fresh `warm-smoke-01`, `warm-full-01`, `recovery-smoke-01` and `recovery-full-01` directories; existing destinations must fail. Run both smoke profiles and replay them, then run the fresh full copies serially:

```sh
python3 tools/run_optimization_revision_benchmarks.py --experiment recovery --profile full \
  --builds target/optimization-recovery/warm-full-01/revision-builds.json \
  --target-root /workspace/optimization-recovery-data
python3 tools/run_optimization_backend_revision.py --experiment recovery --profile full \
  --builds target/optimization-recovery/recovery-full-01/backend-builds.json \
  --target-root /workspace/optimization-recovery-data
```

Smoke uses the corresponding fresh smoke directories and `--profile smoke`. Replay with `validate_optimization_revision_evidence.py` for warm and `validate_optimization_backend_revision.py` for recovery, each accepting `suite.json` and an `--aggregate` output. Package each full root separately with `package_phase1_evidence.py --compression-level 9 --split-archive`; replay complete new or restored historical packages with `validate_phase1_archive.py`, which never executes retained binaries. The complete procedure is in the [transport interruption recovery method](../../../../docs/testing/phase-1-measurements.md#transport-interruption-recovery).

## Validation and historical diagnostics

Both full suites completed and replayed successfully, after their separate smoke suites passed. Before release collection, 279 affected Rust tests, required scoped Clippy and workspace formatting passed. Full Linux Python discovery passed all 662 tests in 132.916 s. Repository validation covered 1,940 source files; foundation validation passed. Full Windows discovery also ran 662 tests; its failures were confined to historical Phase 0 tests requiring POSIX execution, `grep` or `zstd` on that host.

Both unchanged actual functional graphs replay with 61 offers and 125 commands per arm. Nineteen focused fixture tests passed; independent rehashed attacks cannot erase Running/cleanup evidence, cross handoff clocks or revisions, remove terminal decisions, or exchange raw-disconnect and deadline winners. The debug-only candidate had 30/30 successful follow-ups and all 61 checkpoints at four available cells with no quarantine. The debug-only control had 5/30 successful follow-ups and four quarantined cells by offer 11. These are functional results, excluded from release performance conclusions. Their original JSON, source/process receipts and shared metadata remain in bounded fixtures, with Git attributes preserving their bytes.

The earlier same-deadline failure documented with the [#103 comparison](../../precise-budgets/2026-09-09-container-linux-e25b609/README.md) remains historical evidence and motivated #119. This report does not rewrite it or interpret #103's longer outer diagnostic envelope as recovery under the original short transport limit.

**Validated release suite hashes:** warm `sha256:e0533dba5ab25b59db284e3d5c6426d8b3fa6a03f962494025901f6acc29e253`; recovery `sha256:7a59bafc4d124d16489b388a0757bfb2aaf33c76d66ce12dd141e9db17fbd097`.

## Retained evidence and independent replay

Each historical package contains its original suite, aggregate, binaries, source/build inputs, logs and raw observations; its payloads require restoration for replay. The archive is one logical gzip stream transported in ordered bounded parts. Its aggregate, file manifest and parts index are directly inspectable:

| Package | Retained files | Expanded bytes | Logical gzip bytes | Parts | Evidence |
| --- | ---: | ---: | ---: | ---: | --- |
| Warm | 1,220 | 459,011,097 | 102,995,837 | 3 | [aggregate](warm/aggregate.json), [file manifest](warm/raw-evidence.manifest.json), [ordered parts](warm/raw-evidence.parts.json) |
| Recovery | 330 | 418,549,436 | 95,725,834 | 2 | [aggregate](recovery/aggregate.json), [file manifest](recovery/raw-evidence.manifest.json), [ordered parts](recovery/raw-evidence.parts.json) |

Logical gzip SHA-256:

- Warm: `sha256:f50869f16b023bcdd9527b5f1f5dbf710100cfaebb1f4cd8d0818584d40ae952`.
- Recovery: `sha256:302ddfb2482721683ebc6fc03cc7540a42495c87084e9626092eb81c693896f7`.

Linux packaging verified every retained file and replayed each complete suite. Independent Windows archive replay also passed: 1,220 warm files and 330 recovery files. Replay checks all offered attempts, source/process identities, deadline lineage, actual abort/join and cleanup associations; it never executes the retained binaries.

```sh
python3 tools/validate_phase1_archive.py \
  "${restored_root}/benchmarks/optimization/transport-cleanup/2026-09-09-container-linux-ee10b02/warm"
python3 tools/validate_phase1_archive.py \
  "${restored_root}/benchmarks/optimization/transport-cleanup/2026-09-09-container-linux-ee10b02/recovery"
```

Original functional and historical failures remain preserved separately. No attempt was removed from a successful suite, and retries use fresh output directories.
