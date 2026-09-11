# Versioned catalog mutations and canonical persistence

All 24 measured mutation comparisons used less wall time and process CPU with the candidate. At 10,000 releases/deployments, the four public mutations took **35.74%-59.21% less time**, depending on operation and shape. Post-seed idle RSS fell **40.95%** for distinct services and **44.99%** for a shared service. Full semantic replay passed **32 collectors, 45,096 API operations, 224 resolves, 64 mutations and 16 reopen observations, with zero guest Invokes**.

Recovery had mixed results. Shared 10k reopen took **11.350 s versus 8.020 s**, **41.52% longer**, with higher process CPU. Distinct 10k reopened idle RSS rose **18.75%**, even though its opening was 6.01% faster and its later RSS fell. Both 100-release reopens were slower. The result supports cheaper versioned commits in this population; it does not establish uniformly faster recovery or a general memory ceiling.

The separate N4 profiles recorded fewer selected allocations, allocated bytes and lower selected live peaks for every mutation. Whole-process live peaks were slightly higher. Selected reopen attribution is unavailable because a retained raw symbol alias did not match the verifier's symbol spelling; the original zero summaries cannot demonstrate allocation-free recovery or a selected recovery improvement.

The [complete companion](analysis/report-data.json) preserves original aggregate values, exact input hashes and ten CSV tables. Each size/shape has one matched pair, with one observation per operation. These are descriptive differences, not latency quantiles or repeated-trial estimates.

## Implementation and preserved behavior

The compiler retains a bounded memo of previously verified release metadata and compatible compiler configuration. Fresh artifact validation still runs before reuse. Equal metadata and unchanged deployment contents permit reuse of derived revision records; changed records are rederived, and unaffected packed route memberships are remapped into the new record index. An unavailable optional memo uses the existing derivation path. Old pins keep their original generation and policy.

Persistence now produces one sealed final V2 envelope, streams canonical payload bytes through a checksum writer, and fills the reserved checksum offset. It reuses compiler-owned canonical deployment fragments and avoids constructing an intermediate payload tree and payload buffer. Load verification hashes its canonical traversal through a bounded sink. CAS/version checks, staged full-file writes, sync/rename publication and recovery remain part of the transaction. This is not constant-time persistence: every successful commit still writes the complete catalog.

Unchanged apply is a real versioned transaction. The experiment advances catalog generations 1 -> 2 -> 3 -> 4 -> 5 through unchanged apply, weight 1 -> 2 update, delete and create-only reapply. It validates old/current pins, missing get as `Ok(None)`, actual route errors after deletion, and final original content at object version 5 after fresh reopen. Canonical compatibility, fresh metadata/error behavior and durability are also covered by the native checks described below.

## Every normal mutation comparison

Times are seconds. CPU is measured process CPU in seconds, using each owner's actual 100 Hz clock; it includes the common sampler and concurrent work in that process. Each timer ends at the public Result return, before validation, projection and Result Drop. A negative change is lower candidate wall time.

| N | Shape | Operation | Control wall, s | Candidate wall, s | Wall change | CPU, control -> candidate, s |
| --- | --- | --- | --- | --- | --- | --- |
| 100 | distinct | Unchanged apply | 0.054 | 0.032 | -40.70% | 0.05 -> 0.03 |
| 100 | distinct | Weight update | 0.063 | 0.036 | -42.98% | 0.07 -> 0.03 |
| 100 | distinct | Delete | 0.060 | 0.030 | -50.94% | 0.05 -> 0.03 |
| 100 | distinct | Create-only reapply | 0.055 | 0.031 | -43.80% | 0.06 -> 0.03 |
| 100 | shared | Unchanged apply | 0.088 | 0.039 | -55.70% | 0.08 -> 0.03 |
| 100 | shared | Weight update | 0.101 | 0.031 | -69.12% | 0.09 -> 0.03 |
| 100 | shared | Delete | 0.088 | 0.037 | -58.24% | 0.09 -> 0.03 |
| 100 | shared | Create-only reapply | 0.065 | 0.033 | -49.71% | 0.06 -> 0.03 |
| 1,000 | distinct | Unchanged apply | 0.609 | 0.365 | -40.07% | 0.59 -> 0.35 |
| 1,000 | distinct | Weight update | 0.571 | 0.286 | -49.81% | 0.55 -> 0.26 |
| 1,000 | distinct | Delete | 0.667 | 0.302 | -54.73% | 0.66 -> 0.26 |
| 1,000 | distinct | Create-only reapply | 0.654 | 0.367 | -43.91% | 0.65 -> 0.34 |
| 1,000 | shared | Unchanged apply | 0.576 | 0.290 | -49.67% | 0.56 -> 0.26 |
| 1,000 | shared | Weight update | 0.691 | 0.320 | -53.66% | 0.61 -> 0.31 |
| 1,000 | shared | Delete | 0.670 | 0.280 | -58.24% | 0.65 -> 0.27 |
| 1,000 | shared | Create-only reapply | 0.684 | 0.274 | -59.94% | 0.69 -> 0.26 |
| 10,000 | distinct | Unchanged apply | 6.434 | 3.546 | -44.88% | 6.44 -> 3.54 |
| 10,000 | distinct | Weight update | 6.805 | 3.846 | -43.48% | 6.81 -> 3.84 |
| 10,000 | distinct | Delete | 8.904 | 3.632 | -59.21% | 8.95 -> 3.64 |
| 10,000 | distinct | Create-only reapply | 9.720 | 4.478 | -53.93% | 9.77 -> 4.47 |
| 10,000 | shared | Unchanged apply | 6.126 | 3.355 | -45.23% | 6.14 -> 3.36 |
| 10,000 | shared | Weight update | 5.813 | 3.736 | -35.74% | 5.85 -> 3.74 |
| 10,000 | shared | Delete | 6.062 | 3.721 | -38.62% | 6.08 -> 3.73 |
| 10,000 | shared | Create-only reapply | 5.879 | 3.627 | -38.31% | 5.89 -> 3.63 |

The [normal contrasts](analysis/normal-contrasts.csv) retain exact deltas, percentages, owner ordinals and arm order for every metric. At N100 and N10k, distinct ran control first and shared candidate first; N1k reversed those orders. Operations within an owner always followed the same sequence. These observations do not isolate order effects or estimate run-to-run variation.

## Fresh reopen and setup

Opening measures actual artifact/deployment repository opening before Node construction, including recovery and compilation. It is separate from node startup, connection establishment, seed apply and shutdown. The [operation table](analysis/operations.csv) retains each exact CPU bracket and wall boundary.

| N | Shape | Control opening, s | Candidate opening, s | Wall change | CPU, control -> candidate, s |
| --- | --- | --- | --- | --- | --- |
| 100 | distinct | 0.126 | 0.167 | +32.18% | 0.09 -> 0.11 |
| 100 | shared | 0.123 | 0.536 | +334.84% | 0.09 -> 0.34 |
| 1,000 | distinct | 1.327 | 0.998 | -24.77% | 1.28 -> 0.96 |
| 1,000 | shared | 0.949 | 0.812 | -14.38% | 0.88 -> 0.76 |
| 10,000 | distinct | 10.280 | 9.662 | -6.01% | 10.24 -> 9.63 |
| 10,000 | shared | 8.020 | 11.350 | +41.52% | 7.96 -> 11.35 |

All six reopened candidate catalogs still derived N records: there is no previous in-memory generation to reuse in the fresh process. The timings are mixed despite lower serialization work; a single pair does not identify the cause of the slower observations. Initial empty opening, full seed apply, node startup and client connection values remain in the companions and are not counted as mutation speedups.

## Work removed and work retained

The following N10k record and serialization counts hold in both shapes. Values are control -> candidate per public transaction; delete temporarily leaves 9,999 records.

| Operation | Record derivations | Derivation reuses | Compiler deployment encodes | Contract-schema encodes | Envelope encoder calls | Persistence deployment encodes |
| --- | --- | --- | --- | --- | --- | --- |
| Unchanged apply | 10,000 -> 0 | 0 -> 10,000 | 10,000 -> 0 | 10,000 -> 0 | 2 -> 1 | 20,000 -> 0 |
| Weight update | 10,000 -> 1 | 0 -> 9,999 | 10,000 -> 1 | 10,000 -> 0 | 2 -> 1 | 20,000 -> 0 |
| Delete | 9,999 -> 0 | 0 -> 9,999 | 9,999 -> 0 | 9,999 -> 0 | 2 -> 1 | 19,998 -> 0 |
| Create-only reapply | 10,000 -> 1 | 0 -> 9,999 | 10,000 -> 1 | 10,000 -> 1 | 2 -> 1 | 20,000 -> 0 |

Fresh checks were retained: each N10k unchanged/weight/reapply commit fetched metadata and verified components 10,000 times, hashing 247,850,000 component bytes; delete did so 9,999 times. Both arms had the same counts. Those operations made zero full-artifact fetches and no additional artifact-verification metadata-fingerprint attempts. Compiler derivation/reuse counters are separate; they do not measure the compiler memo fingerprint cost. [All work receipts](analysis/work-counters.csv) distinguish these scopes.

For unchanged apply, the candidate remapped 20,000 route memberships and reused 10,000 distinct scopes or the one shared scope. A distinct weight update staged two memberships and remapped 19,998. A shared weight update still staged all 20,000 memberships because its sole scope changed. The shared delete/reapply likewise rebuilt that scope. Reuse therefore reduces derivation without eliminating all work proportional to catalog size.

Both arms wrote and file-synced the same complete byte counts below, with one completed staging operation and zero recorded write/sync failures. Encoder calls fell from two to one, but durable write volume did not fall.

| N10k shape | Operation | Bytes written, each arm | Bytes file-synced, each arm |
| --- | --- | --- | --- |
| distinct | Unchanged / weight / reapply | 34,510,328 | 34,510,328 |
| distinct | Delete | 34,506,877 | 34,506,877 |
| shared | Unchanged / weight / reapply | 33,720,407 | 33,720,407 |
| shared | Delete | 33,717,035 | 33,717,035 |

For N10k unchanged apply, summed payload-buffer bytes fell from 69,020,424 distinct / 67,440,582 shared to zero; the candidate streamed one payload traversal into its final envelope. Its final buffer was 34,510,328 / 33,720,407 bytes. The maximum individual final-buffer capacity rose from 54,001,664 to 62,324,736 bytes in both shapes. Zero intermediate-buffer counters therefore do not mean zero allocation, zero retained capacity or a measured scratch peak. On reopen, load-payload buffer bytes also fell to zero, while both arms still performed the canonical load traversal and a full compile.

## Process memory and old pins

Post-seed idle is before the mutation proof sequence. Reopened idle is before reopened proof outputs are released. Values below are RSS bytes; neither boundary is an exact catalog heap measurement.

| N | Shape | Post-seed RSS, control -> candidate, B | Change | Reopened idle RSS, control -> candidate, B | Change |
| --- | --- | --- | --- | --- | --- |
| 100 | distinct | 18,132,992 -> 17,022,976 | -6.12% | 19,779,584 -> 18,812,928 | -4.89% |
| 100 | shared | 18,255,872 -> 17,600,512 | -3.59% | 19,582,976 -> 19,927,040 | +1.76% |
| 1,000 | distinct | 30,097,408 -> 23,470,080 | -22.02% | 51,642,368 -> 42,008,576 | -18.65% |
| 1,000 | shared | 32,382,976 -> 23,494,656 | -27.45% | 50,561,024 -> 42,352,640 | -16.23% |
| 10,000 | distinct | 149,237,760 -> 88,125,440 | -40.95% | 309,673,984 -> 367,747,072 | +18.75% |
| 10,000 | shared | 148,721,664 -> 81,813,504 | -44.99% | 285,556,736 -> 238,284,800 | -16.55% |

The distinct 10k candidate's higher reopened idle RSS was also visible in PSS: 309,159,936 -> 367,167,488 B. At the later oracle-released checkpoint, RSS was 309,673,984 -> 232,968,192 B; after reopened outputs were released it was 309,805,056 -> 233,099,264 B. The oracle construction had already dropped its temporary table before the oracle-released checkpoint. These observations do not isolate the cause of the earlier RSS difference. Shared 10k reopened output-release RSS was 285,687,808 -> 238,284,800 B. A boundary-specific gain does not establish a lifetime memory ceiling.

Old-pin overlap retains generation 1 while current generation 5 is live. Dropping the pin did not reduce sampled candidate RSS at any normal size. This does not show that the pin retained no heap: allocator retention and page-level sampling remain in the process measurement.

| N10k shape | Boundary | Control RSS, B | Candidate RSS, B |
| --- | --- | --- | --- |
| distinct | overlap-before-pin-drop | 152,551,424 | 105,148,416 |
| distinct | pin-released | 152,551,424 | 105,148,416 |
| shared | overlap-before-pin-drop | 179,093,504 | 99,774,464 |
| shared | pin-released | 148,897,792 | 99,774,464 |

The [checkpoint table](analysis/checkpoint-memory.csv) retains RSS, PSS, current VmSize, lifetime VmPeak/VmHWM, and private/shared page fields at every boundary, plus before-node and after-shutdown observations. These values are not interchangeable.

## Samples inside operations and lifetime high water

The source sampler retained 7,468 normal samples, requesting 100 ms cadence; actual adjacent starts ranged from 100.152 to 414.987 ms. Nineteen of the 84 normal opening/seed/mutation windows contained no complete sample bracket, including six of the 48 mutation windows, so their within-operation maxima are unavailable. All twelve normal reopen windows contained samples. The following N10k windows are sampled RSS maxima, with actual sample counts.

| N10k shape | Operation | Control sampled RSS max, B | Candidate sampled RSS max, B | Samples, control / candidate |
| --- | --- | --- | --- | --- |
| distinct | Unchanged apply | 340,340,736 | 127,840,256 | 64 / 36 |
| distinct | Weight update | 346,804,224 | 136,077,312 | 68 / 38 |
| distinct | Delete | 348,213,248 | 136,773,632 | 89 / 36 |
| distinct | Create-only reapply | 349,913,088 | 139,657,216 | 97 / 45 |
| distinct | Reopen | 482,197,504 | 398,245,888 | 102 / 96 |
| shared | Unchanged apply | 312,049,664 | 121,528,320 | 61 / 33 |
| shared | Weight update | 316,694,528 | 129,032,192 | 58 / 37 |
| shared | Delete | 316,653,568 | 131,850,240 | 61 / 37 |
| shared | Create-only reapply | 316,854,272 | 133,464,064 | 58 / 36 |
| shared | Reopen | 446,840,832 | 364,761,088 | 79 / 113 |

A maximum of contained samples can miss the true transient peak. VmHWM is cumulative, so a read inside an operation can reflect earlier work. Candidate N10k lifetime resident high water reached 139,657,216 B distinct initial / 399,855,616 B reopen and 133,464,064 B shared initial / 364,761,088 B reopen. These whole-process observations do not isolate compiler or serializer scratch.

## Separate N4 allocation profiles

All eight profile owners passed whole-process interpreted/folded replay. The sixteen mutation frames have supported selected attribution with zero unresolved origins; each observed one actual future poll and one owned Result Drop. Each row below covers one operation, not a per-deployment average. No profile used the normal 100/1k/10k populations. The four reopen profiles have the coverage limitation described below.

| N4 shape | Selected frame | Allocations, control -> candidate | Allocated B, control -> candidate | Selected peak B, control -> candidate |
| --- | --- | --- | --- | --- |
| distinct | Unchanged apply | 27,561 -> 12,894 | 1,381,297 -> 524,386 | 82,954 -> 21,869 |
| distinct | Weight update | 27,562 -> 14,480 | 1,381,473 -> 585,586 | 86,043 -> 23,854 |
| distinct | Delete | 18,935 -> 7,927 | 935,976 -> 352,270 | 61,797 -> 20,567 |
| distinct | Create-only reapply | 27,560 -> 14,635 | 1,381,449 -> 599,648 | 86,043 -> 23,977 |
| distinct | Reopen frame | unavailable | unavailable | unavailable |
| shared | Unchanged apply | 27,436 -> 12,884 | 1,370,068 -> 524,596 | 80,299 -> 21,581 |
| shared | Weight update | 27,437 -> 14,525 | 1,370,244 -> 594,061 | 83,388 -> 23,566 |
| shared | Delete | 18,849 -> 7,979 | 927,242 -> 361,840 | 58,591 -> 20,413 |
| shared | Create-only reapply | 27,435 -> 14,680 | 1,370,220 -> 608,123 | 83,388 -> 23,689 |
| shared | Reopen frame | unavailable | unavailable | unavailable |

**Selected reopen attribution is unavailable.** Original summaries retain status `available` and zero selected origins. The [retained symbol inspection](validation/reopen-allocation-coverage.json) found that the interpreted trace's raw reopen symbol omits the `.llvm...` suffix present in the verified raw symbol; exact matching missed this alias. The actual wrapper and one observed poll remain present. This is a selected-attribution coverage defect, not evidence of zero recovery allocations. Original aggregate bytes are preserved; the report excludes all four selected reopen summaries from allocation conclusions. The mutation symbols are unaffected. Reopen retains the returned catalog through Node shutdown, so its frame Drop count is intentionally zero. Whole-process traces below retain real allocation work.

All selected mutation end-live bytes and remaining allocations were zero after later frees. The union of the four mutation frames allocated 5,080,195 -> 2,061,890 B distinct and 5,037,774 -> 2,088,620 B shared; union live peak was 88,587 -> 26,702 B and 85,491 -> 25,973 B. Union peak is simultaneous live selected bytes, not a sum of individual frame peaks.

Whole-process profiles additionally include opening, publication, seed, proofs, output, observation and shutdown:

| N4 shape | Process | Allocations, control -> candidate | Allocated B, control -> candidate | Whole live peak B, control -> candidate |
| --- | --- | --- | --- | --- |
| distinct | Initial + four mutations | 256,525 -> 197,090 | 17,085,918 -> 13,505,968 | 758,147 -> 758,645 |
| distinct | Fresh reopen | 81,101 -> 77,274 | 6,077,405 -> 5,771,946 | 761,904 -> 762,219 |
| shared | Initial + four mutations | 262,693 -> 203,935 | 17,577,475 -> 14,068,677 | 756,600 -> 757,098 |
| shared | Fresh reopen | 87,241 -> 83,443 | 6,579,386 -> 6,271,709 | 760,787 -> 761,100 |

Whole live peaks rose 498 B for each initial profile and 315/313 B for distinct/shared reopen. Every whole trace ended with **802 allocations / 102,916 B** remaining in both arms. Selected residual zero does not establish zero whole-process retention. Exact `temporary_scratch_peak_bytes` is unavailable with reason `selected-origins-include-retained-catalog-ownership`; neither selected totals nor work-buffer counters can supply it. [Allocation frames](analysis/allocation-frames.csv) and [scope totals](analysis/allocation-scopes.csv) retain the exact witnesses and residuals.

## Sources, environment and finite population

Control was `165d1eb5084c256dab72ac10217b26af3c6e4c44`; candidate and harness were `15f3fba3f47404240dd577d9eaaa3f60270b81d1`. Both were clean release builds with the same collector, observer, fixture and bounded helper sources. Their source trees were `575f07560c9ae3cfa45ff9c3fb6fdb9563ebada7` and `0b476179c2c3494071a2d37c0908dc2611173c8a`; the shared Cargo.lock SHA256 is `ad0cdff10a0c980cd93441afcdf0501a4d1910074b0756940751701989c6c976`. The bound build receipt records Rust/Cargo 1.97.1, LLVM 22.1.6, Wasmtime 47.0.3 and target `x86_64-unknown-linux-gnu`, with opt-level 3, 16 codegen units, LTO disabled and symbols retained. Profile tool receipts record Heaptrack/heaptrack_print 1.4.0 and zstd 1.5.4.

The recorded environment was a Linux x86_64 Docker container on WSL2 kernel 6.6.87.2, Intel Core i7-11850H, 16 visible logical CPUs and 33,233,743,872 B host memory. The visible cgroup had a four-CPU quota (`400000 100000`), cpuset 0-15 and no leaf memory maximum. Shared cgroup counters are observations, not attribution to one collector or proof of ancestor limits. Allocator preload/configuration variables were unset. This is the recorded container environment, not a bare-metal or Kubernetes comparison.

Normal collection used freshly seeded N100, N1k and N10k roots in both shapes, one matched pair each. Each arm's initial and fresh reopen children were adjacent on the same exclusively owned root; no populated root was copied or restored. The parent bound marker/device/inode, actual process identity and post-exit catalog bytes before reopen, then performed bounded final inventory and cleanup. All counted pins/proof outputs were released; full replay checked process exits, native ownership gauges and runtime joins. There were no guest Stores, Invokes or preparation jobs, hidden warmups, retries, or extra uncounted public catalog reads.

Full collection took 951.708568420 s: normal 783.405416428 s and allocation 168.303148117 s, plus the recorded surrounding stage overhead. These are collection elapsed times, not public-operation timings or semantic replay duration. Normal accounts for 24 collectors / 44,910 commands and separate N4 profiles for eight / 186. Smoke passed 16 / 372 and validates the protocol only. [The fixed method](../../../../docs/testing/phase-1-measurements.md#catalog-mutation-and-commit-experiments) describes the full bounds and counting rules.

This population has one pair per size/shape and no 100k state. It supplies no confidence intervals, universal SLO, exact transient scratch peak, or extrapolated large-state allocation estimate. The [#107 report](../../catalog-memory/2026-09-10-container-linux-96716c8/README.md) remains historical context; its medians and distinct-100k RSS targets are not subtracted from or imported into this campaign.

## Retained attempts and validation

Earlier failures remain separate from the qualified full root. Their actual identities and partial populations are retained; offline export/compression diagnostics did not rerun a collector or fill a missing owner. The [attempt appendix](attempts/README.md) and [hash manifest](attempts/manifest.json) retain 29 original small witness files, 4,142,406 B, and identify the original empty smoke log without publishing an empty file. This is a diagnostic subset excluding the older large binaries, source trees and expanded profiles; the original failed roots remain separate. It is not a replayable qualifying archive.

| Attempt | Retained scope | Outcome |
| --- | --- | --- |
| Dirty normal07 | Four owners, 93 commands, zero Invokes | Protocol regression evidence only; dirty/debug identity. |
| Neutral N16 smoke | Eight normal owners passed 186 commands; first profile collector passed 52 | Folded export killed at the old 256 MiB bound; 268,591,104 B partial output. |
| Paired N4 smoke01 | Original source/build/trace and partial export retained | Still exceeded 256 MiB. Offline re-export completed 469,170,020 B under a diagnostic 512 MiB bound. |
| e275/bfb paired smoke02 | 14 collection owners completed; 15 native collectors passed 366 commands, including 12 expected route errors | Peak gzip coexistence reached the retained-root guard; final six-command reopen never ran. |
| Copied peak compression diagnostic | Original 473,689,685 B expanded peak; original hash unchanged | Verified 7,110,251 B gzip in 5.322614888 s using explicit scratch accounting; no workload rerun. |
| 165d1eb/15f3fba smoke03 | All 16 owners / 372 commands | Complete protocol smoke, followed by this separately qualified full population. |

The smoke02 retained bytes excluding its one active expanded file were 600,042,499 B; its partial gzip was 5,098,471 B. The guard rejected the next write before accepting its bytes. The final protocol explicitly declares 512 MiB expanded folded text and one owned active-file allowance of the same size. Gzip and all other files remain charged within a **1 GiB retained root**, with at most **1.5 GiB temporary physical coexistence**. Sequential export/compression/roundtrip retains its 120 s deadline; expanded originals are removed only after exact byte/hash verification. The earlier catalog experiment remains at 256 MiB with its original protocol.

Other bounds remain: ordinary retained files 256 MiB, 4,096 evidence files, four million interpreted records, folded 64 KiB lines / 100,000 rows / 512 frames, and 32 MiB raw documents. The archive remains bounded at 1 GiB expanded / 5,000 members and 198,000,000 B split gzip. Lossless compression does not waive decoded profile checks.

Native validation recorded [122 passing observation-enabled control-store checks](validation/control-store-observed.log), [109 passing default control-store checks](validation/control-store-default.log) and [71 passing latentd checks plus 14 ignored](validation/latentd-units.log). The finite export/retention correction also passed [113 Linux checks](validation/scratch-python.log) and 55 focused Windows checks; these scopes overlap and are not summed. [All six CI jobs passed at the measured source head](validation/source-ci.json). Final report-head CI is recorded in [PR128](https://github.com/KirilsTurkins/latent-service-fabric/pull/128). Full collection semantic replay and canonical aggregate equality passed before report extraction. These replay results preserve the original reopen-attribution limitation described above.

## Archive and reproduction

Linux packaging completed its mandatory full semantic roundtrip replay, and independent Windows full semantic replay passed in **118.264682700 s**. The [Linux receipt](validation/linux-package.json) and [log](validation/linux-package.log), and [Windows receipt](validation/windows-replay.json) and [log](validation/windows-replay.log), retain actual exit-zero evidence and byte identities. The Windows copy remained unchanged through replay. Linux package duration was not recorded and is not estimated.

The [member manifest](catalog/raw-evidence.manifest.json) covers **1,370 members / 619,755,414 expanded bytes**. Logical split gzip is **161,619,941 B**, SHA256 **`b1b1abe26eaeca39670b09a1f6a32d41e55ed419bd83c32341985928f03dd01d`**. The [part manifest](catalog/raw-evidence.parts.json) binds three 50,000,000 B parts and one 11,619,941 B part. The [original aggregate](catalog/aggregate.json), both clean binaries, retained build closure and all full-population raw evidence are in this qualifying package; failed attempts remain separate.

From the repository root, replay the closed package with:

```sh
python tools/validate_phase1_archive.py benchmarks/optimization/catalog-mutations/2026-09-11-container-linux-15f3fba/catalog
```

To reproduce collection, use a clean checkout of the exact harness above and fresh directories. Build both source revisions with `tools/build_optimization_backend_revision.py --experiment catalog-mutations --profile full --control-ref 165d1eb5084c256dab72ac10217b26af3c6e4c44 --candidate-ref 15f3fba3f47404240dd577d9eaaa3f60270b81d1 --harness-ref 15f3fba3f47404240dd577d9eaaa3f60270b81d1 --output <fresh-build-root> --target-root <fresh-build-parent>`. Copy its complete hash-bound build closure into fresh smoke/full roots, including referenced sidecars and executable modes. Run the smoke and full profiles sequentially:

```sh
python tools/run_optimization_backend_revision.py --experiment catalog-mutations --profile smoke --builds <smoke-root>/backend-builds.json --target-root <owned-data-parent>
python tools/run_optimization_backend_revision.py --experiment catalog-mutations --profile full --builds <full-root>/backend-builds.json --target-root <owned-data-parent>
python tools/validate_optimization_backend_revision.py <full-root>/suite.json --aggregate <full-root>/aggregate.json
python tools/package_phase1_evidence.py --source <full-root> --output <fresh-package> --compression-level 9 --split-archive
```

The standalone validator replays raw evidence and requires canonical equality to the retained aggregate. Packaging performs its own mandatory semantic roundtrip before publishing. The [report transformation](extract.py) consumes the qualified aggregate and its exact suite in a fresh output directory outside both input roots:

```sh
python benchmarks/optimization/catalog-mutations/2026-09-11-container-linux-15f3fba/extract.py <full-root>/aggregate.json <full-root>/suite.json <fresh-analysis-directory>
```

It performs no collector or semantic replay and preserves nulls and unrounded values. Failed attempts never become part of the qualified population through reporting or compression.
