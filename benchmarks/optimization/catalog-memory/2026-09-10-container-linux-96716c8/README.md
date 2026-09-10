# Catalog memory and public resolver comparison

At 100,000 distinct services, candidate post-publication RSS was **1,117,204,480 B**, versus **2,718,257,152 B** for control: **58.90% lower**. This met both reference-shape targets: at least 25% lower matched RSS and at most 1,750,000,000 B. The full campaign passed semantic replay with 24 collectors, 596,720 API operations, 196,396 resolves and **zero guest Invokes**.

The result depends on workload shape and lifecycle. With 100,000 deployments sharing one service, RSS fell only **14.19%**, to **2,504,171,520 B**. All four shared-shape resolver p50/p99 pairs were slower at that scale, and its weight update took 24.53% longer. Reopened candidate RSS was 2.95 GB distinct and 2.78 GB shared. The reference target therefore does not establish a general memory ceiling or universal latency improvement.

All sixteen tiny allocation profiles had available selected attribution. Public default-success allocation counts fell from 21 to 11 per call and named-success counts from 22 to 12, with lower selected bytes and peaks. These profiles contain sixteen releases; they are separate from the unprofiled 100k measurements.

The [complete companion](analysis/report-data.json) preserves unrounded values and the original aggregate. Its CSV tables retain every scale, case, outcome, memory checkpoint and allocation comparison. This is one full matched pair per shape, not a repeated-trial estimate.

## Implementation and compatibility

The compiled deployment catalog now retains immutable shared revision records and packed route, endpoint and cumulative-weight indexes. Desired state and its revision record share the deployment manifest. Default routes, named routes and candidate lists refer to the same record instead of retaining duplicated public snapshot rows and a separate copied admission-policy map.

Lookup compares borrowed identifiers. Weighted selection streams the unchanged length-framed UTF-8 input into SHA-256 and reads its first eight bytes without a temporary framed buffer or hexadecimal conversion. Records can be reused across pinned generations only after fresh artifact verification derives equal contents. A weight change preserves the revision ID but replaces the changed canonical deployment attributes; old pins preserve their original generation and policy.

Public snapshots, watcher results, resolved revisions and admission policies still return owned values. Tenant-scoped projection preflights the selected borrowed range before materialization; persistence and pagination preserve their existing canonical ordering, versions and bounds. Public response construction is not allocation-free. The measured product change is in deployment catalog ownership, search and projection; it does not include an artifact-index rewrite or a persistence/no-op transaction optimization.

The old implementation's compatibility fixtures were captured at `2a3bd3c753ff17b2adb8e27e8bd2fa580c52f46b`. They retain exact canonical V2 persistence and snapshot JSON, 36 weighted choices and three lookup errors across multiple scopes, mixed weights and escaped/Unicode keys. Candidate regression tests compare against those retained bytes and values rather than regenerating their expectations.

## Memory at each scale

Primary idle is sampled after applying the growth delta and dropping its request, before resolver input, result and oracle buffers are constructed. Values are bytes; percentages compare candidate with the same-shape control.

| Shape | Deployments/releases | Control RSS | Candidate RSS | Change |
| --- | ---: | ---: | ---: | ---: |
| Distinct | 100 | 18,595,840 | 18,071,552 | -2.82% |
| Distinct | 1,000 | 38,936,576 | 30,785,536 | -20.93% |
| Distinct | 10,000 | 240,922,624 | 149,573,632 | -37.92% |
| Distinct | 100,000 | 2,718,257,152 | 1,117,204,480 | **-58.90%** |
| Shared | 100 | 18,984,960 | 18,030,592 | -5.03% |
| Shared | 1,000 | 39,641,088 | 29,859,840 | -24.67% |
| Shared | 10,000 | 283,787,264 | 149,385,216 | -47.36% |
| Shared | 100,000 | 2,918,371,328 | 2,504,171,520 | **-14.19%** |

Both formal targets apply to the distinct 100k primary boundary and were met independently. The shared result reaches neither the same 25% reduction nor the same numerical 1.75 GB ceiling. Dropping the resolver outputs did not lower RSS at the final scale in either arm or shape.

| Shape | Other 100k boundary | Control RSS, B | Candidate RSS, B |
| --- | --- | ---: | ---: |
| Distinct | After artifact publication, before growth apply | 289,288,192 | 217,862,144 |
| Distinct | Old pin overlaps updated generation | 3,523,907,584 | 1,198,800,896 |
| Distinct | Old pin released | 3,504,594,944 | 1,174,687,744 |
| Distinct | Fresh process, reopened idle | 3,855,446,016 | 2,948,530,176 |
| Shared | After artifact publication, before growth apply | 283,787,264 | 177,958,912 |
| Shared | Old pin overlaps updated generation | 4,131,037,184 | 2,504,478,720 |
| Shared | Old pin released | 4,113,432,576 | 2,497,277,952 |
| Shared | Fresh process, reopened idle | 3,533,197,312 | 2,777,202,688 |

The before-apply row still includes the previous 10k compiled deployment generation; it is not an isolated artifact-repository measurement. Reopened RSS was 23.52% lower distinct and 21.40% lower shared, but substantially above the candidate's original primary boundary. These observations do not separate live catalog ownership from allocator-retained construction/recovery scratch.

Candidate lifetime resident high-water marks were 3,263,250,432 B distinct initial and 4,719,112,192 B distinct reopen; shared values were 2,977,480,704 B and 4,363,980,800 B. The met 1.75 GB idle target does not bound these peaks.

At primary distinct 100k, PSS was 2,718,251,008 -> 1,117,139,968 B and private dirty pages were 2,704,183,296 -> 1,103,003,648 B. Shared PSS was 2,918,100,992 -> 2,504,288,256 B. [All checkpoint memory](analysis/checkpoint-memory.csv) also retains current virtual mappings and lifetime high-water values. These quantities are not interchangeable with RSS or exact stage-local peaks.

## Apply windows, sampling and CPU

The table distinguishes growth to 100k from the subsequent one-deployment weight update. Durations are seconds. RSS maxima use only source sampler reads whose complete read bracket falls inside that operation.

| Shape / operation | Control seconds | Candidate seconds | Control sampled RSS max, B | Candidate sampled RSS max, B | Samples, control/candidate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Distinct growth | 123.710 | 69.681 | 4,022,554,624 | 3,211,911,168 | 1,232 / 694 |
| Distinct weight update | 104.517 | 64.583 | 5,038,362,624 | 3,263,250,432 | 1,041 / 644 |
| Shared growth | 77.613 | 70.015 | 3,597,312,000 | 2,942,218,240 | 773 / 697 |
| Shared weight update | 64.958 | 80.895 | 4,468,137,984 | 2,977,480,704 | 647 / 805 |

Distinct growth/update took 43.67%/38.21% less time. Shared growth took 9.79% less, while its update took **24.53% more** despite lower sampled RSS. At smaller scales, distinct 1k apply was 2.37% slower. [Every growth/update window](analysis/apply-samples.csv) retains the actual brackets, sample counts and high-water observations.

The normal source sampler retained 59,166 samples. It requested 100 ms cadence; observed adjacent starts ranged from 100.137 to 139.785 ms. All twenty growth/update windows had contained samples, but the smallest windows had only one. These are sampled maxima, not exact transient peaks. A VmHWM read during an operation can reflect an earlier lifetime maximum. The common observer perturbs both arms; no allocator purge was forced.

| Shape / mode | Control catalog-open seconds | Candidate catalog-open seconds | Control measured process CPU seconds | Candidate measured process CPU seconds |
| --- | ---: | ---: | ---: | ---: |
| Distinct initial | 0.050721 | 0.177253 | 574.79 | 389.39 |
| Distinct reopen | 100.564319 | 90.213400 | 10.92 | 9.33 |
| Shared initial | 0.024069 | 0.121928 | 397.66 | 395.21 |
| Shared reopen | 96.032881 | 89.793509 | 7.84 | 9.80 |

CPU uses the actual 100 Hz process counters from the first empty/reopened-idle checkpoint through before-shutdown. It includes that population's operations, validation, persistence and observation, but excludes preceding catalog open and subsequent shutdown. Reopen CPU is therefore not recovery CPU. Shared reopen CPU rose 25%; initial empty-catalog opening was slower in both candidate runs. [Run costs](analysis/run-costs.csv) and [normal contrasts](analysis/normal-contrasts.csv) preserve node-start/client-connect timings and all unrounded values. Short single observations do not identify the cause of those differences.

## Public resolver latency

Each full scale has 5,000 default successes, 5,000 named successes, 1,000 route misses and 1,000 export misses per owner. The timer stops when the public resolver returns its owned Result; validation and Result Drop follow the timer. Expected misses remain counted and validated. The 100k results below are microseconds.

| Shape / case | Control p50 | Candidate p50 | Control p99 | Candidate p99 |
| --- | ---: | ---: | ---: | ---: |
| Distinct default success | 19.7870 | 15.7605 | 74.501 | 42.147 |
| Distinct named success | 24.3750 | 13.0450 | 93.094 | 32.236 |
| Distinct route miss | 9.5395 | 10.7035 | 42.303 | 27.335 |
| Distinct export miss | 16.0180 | 10.2855 | 48.214 | 15.211 |
| Shared default success | 4.5060 | 5.4575 | 18.862 | 30.484 |
| Shared named success | 10.0260 | 17.9535 | 28.091 | 51.694 |
| Shared route miss | 0.4180 | 0.7655 | 1.986 | 7.459 |
| Shared export miss | 0.4170 | 1.0215 | 1.593 | 14.638 |

Distinct 100k success p50/p99 improved, but route-miss p50 increased 12.20%. **Every shared 100k p50 and p99 increased**; named-success p50/p99 rose 79.07%/84.02%. Smaller scales are also mixed: all four distinct 10k p50 values were higher. Across the sixteen scale/case rows per shape, candidate p50 was lower in 7 distinct and 10 shared rows; p99 was lower in 13 distinct and 9 shared rows. These are descriptive row directions, not sixteen independent process trials.

[All distributions](analysis/resolver-distributions.csv) include p95, counts, expected success/error totals and the separately wider chunk windows. They do not represent external RPC latency or a universal service SLO.

## Separate sixteen-release allocation profiles

All sixteen selected profiles were available with zero unresolved allocation origins. Each measured frame contained 256 calls after one preflight and sixteen warmups. Selected totals were identical between the two shapes for each case, so this table shows their common result. Counts and allocated bytes per call divide the measured frame totals by 256; the peak column is the undivided maximum simultaneously live selected bytes.

| Public case | Allocations/call, control -> candidate | Allocated B/call, control -> candidate | Selected peak B, control -> candidate |
| --- | ---: | ---: | ---: |
| Default success | 21 -> 11 | 2,137 -> 1,667 | 1,976 -> 1,667 |
| Named success | 22 -> 12 | 2,154 -> 1,679 | 1,993 -> 1,679 |
| Route miss | 9 -> 6 | 679 -> 646 | 679 -> 646 |
| Export miss | 11 -> 6 | 748 -> 682 | 748 -> 682 |

The selected frame includes public resolve, full Result comparison, owned Result Drop and bounded counter maintenance. It excludes preflight, warmup and publication but the whole-process profile includes them. It does not prove zero allocation for a private helper.

| Shape / case | Whole-process allocations, control -> candidate | Whole-process allocated B, control -> candidate | Whole-process peak B, control -> candidate |
| --- | ---: | ---: | ---: |
| Distinct default | 312,491 -> 296,841 | 20,502,655 -> 19,873,407 | 1,144,542 -> 1,039,766 |
| Distinct named | 312,766 -> 297,115 | 20,507,281 -> 19,876,668 | 1,144,537 -> 1,039,764 |
| Distinct route miss | 308,478 -> 294,738 | 20,016,579 -> 19,506,603 | 1,144,528 -> 1,039,754 |
| Distinct export miss | 309,022 -> 294,736 | 20,035,686 -> 19,516,732 | 1,144,532 -> 1,039,758 |
| Shared default | 311,744 -> 296,202 | 20,436,372 -> 19,815,814 | 1,109,058 -> 1,019,860 |
| Shared named | 312,014 -> 296,472 | 20,440,615 -> 19,818,664 | 1,109,049 -> 1,019,855 |
| Shared route miss | 307,721 -> 294,089 | 19,939,674 -> 19,438,362 | 1,109,042 -> 1,019,846 |
| Shared export miss | 308,266 -> 294,089 | 19,958,802 -> 19,448,505 | 1,109,043 -> 1,019,848 |

Selected residual allocations/bytes were zero in every profile. Whole-process replay separately retained 802 allocations / 102,916 B in every arm; those are not selected residuals. [Per-arm allocation evidence](analysis/allocation-arms.csv) and [paired contrasts](analysis/allocation-contrasts.csv) preserve both scopes. No 100k process was Heaptrack-profiled, so these tiny profiles do not establish allocation growth or retained memory at 100k.

## Protocol, environment and ownership

Distinct shape assigns one service per deployment; shared shape has one service with the same distinct releases, deployments and named routes. Both use the maintained Echo bytes plus the fixed 31-byte indexed custom section. The initial owner grows through 100/1,000/10,000/100,000, then performs one weight update with an old pin. Its adjacent reopen child uses the same executable and unchanged durable root, bound by the original process/raw identity, exclusive marker, device/inode and post-exit catalog hash.

Full has four initial and four reopen children, followed by sixteen separate allocation children. Normal API operations total 592,080, including 192,000 timed resolves. Allocation operations total 4,640, including 4,096 measured calls, 256 warmups and sixteen preflights. Pins, policy reads, publications and applies remain counted outside the declared resolver timing population. All full completeness flags are true; expected route/export misses are successful protocol coverage.

The host was an Intel i7-11850H with 16 logical CPUs and 33,233,743,872 B reported memory, Docker on Linux 6.6.87.2-microsoft-standard-WSL2. The shared cgroup had `cpu.max=400000 100000`, cpuset `0-15` and no memory ceiling. Its normal-window throttle counters added zero events/time; these shared observations do not prove CPU isolation or native-Linux calibration. Allocator preload/config overrides were unset.

Both arms retained the default on-demand/speed engine, two runtime workers, one control worker and two cells. All normal checkpoints recorded eight OS threads, 20 file descriptors, seven socket references/five unique sockets, one listener and no descendants. Semantic replay required zero guest/native preparation/Store activity, no quarantine, actual compiler/cleanup/runtime joins, sampler termination, released catalog owners and parent same-root removal. Public pin/policy/reopen checks passed. The generated release/catalog files are excluded from the archive; fixed recipes, hashes, operation digests and bounded filesystem/cleanup receipts remain retained.

The total collection stage took **6,160.052188127 s**: normal **6,055.422895003 s**, allocation **104.629287824 s**. Initial/reopen bounds were 3,600/1,800 s within a 21,600 s normal stage. Allocation children had 180 s within an independent 7,200 s stage. Build had its separate 10,800 s bound. These are independent stage limits, not one combined campaign deadline.

## Exact sources and validation

| Arm | Commit | Tree | Release libtest B | Executable SHA-256 |
| --- | --- | --- | ---: | --- |
| Control | `397ee901ee919ae538d2a964d1543169bb740926` | `6cc2395be9df059bdc426cb49160ff669deb9703` | 216,184,304 | `a06f74223eb8f112753e9656646faec96097efb160a641b995b72f70ffc845da` |
| Candidate/harness | `96716c8468e90246c59c6282d401c0f5402d0dda` | `de03793e3cb7507038c42d93b3c8d75a18526de5` | 215,970,656 | `4fd8fde555d49461ac5c5b05973953a9ed046d1ff3e2c44524d2c6de2fa45585` |

Build02 used clean sources, Rust/Cargo 1.97.1, Wasmtime 47.0.3 and target `x86_64-unknown-linux-gnu`; its owned build checkout was removed. Cargo.lock SHA-256 is `ad0cdff10a0c980cd93441afcdf0501a4d1910074b0756940751701989c6c976`. The shared Echo component is 24,754 B, SHA-256 `4dc815f10d7a2f4d7b204efa39a53ab1882bb58da8248fcd03449e87d9e9e788`. Release settings retain opt-level 3, 16 codegen units, debug 1, no LTO/incremental, unwind panics and the established path-remap/build-ID controls.

Corrected smoke02 passed 40 collectors / 8,900 operations / 8,292 resolves in 136.482750251 s. Its smoke aggregate correctly remains `incomplete` and nonqualifying for full performance. Recorded correctness checks include 87 control-store tests, 69 latentd tests with 13 ignored collectors, five focused projection checks, original-golden capture/regression and strict owning Clippy/formatting. Linux Python discovery passed 815 tests in 186.268 s; the cap correction also passed 30 catalog and 10 ownership/compression checks on Windows. Overlapping runs are not summed. All six CI jobs passed the measured source head; final report-head CI is a separate merge gate.

Full aggregate SHA-256: `9a74ed5a75a047a8869538945e8c41be43e8b0f42e6f0fa3de002fa0b85ba71c`; suite: `eecd37ba995e26c176793534f418565586b6d64640cbc42ad3e3ce9b62c74b46`; backend-build receipt: `b8c57d4df5b16009dd48eea68284c39640528c8db87ac8cfad20743210644871`.

## Retained attempts and explicit limit correction

| Attempt | Actual work / outcome | Qualification boundary |
| --- | --- | --- |
| Dirty diagnostic01 | 35 operations: two publications, one apply, 32 unexpected resolver errors | The success fixture inherited an empty function; common collector input was corrected to actual Echo `echo`. Production resolution policy was unchanged. |
| Dirty diagnostic02 | Initial child passed 604 operations | Functional diagnostic only. |
| Dirty diagnostic03 | Initial 604 / reopen 7 / allocation-default-success 98 operations passed | Explicit dirty/debug snapshot `2abef5f89c22a86a292eadad4ef8f01231a5f4cffc8dbc3ad254d5dd322d5381`; original raw/component/sampler regression bytes are retained, without fabricated release identity. |
| Release smoke01, control8fb79ff / candidateb592c0c | All 24 normal children passed/replayed 7,332 operations; first allocation child completed 98 operations, then export failed | Actual 25 children ran 7,430 operations. Failed aggregate validates only 24 / 7,332 / 6,996 resolves; allocation validation contributes zero. Fifteen allocation children never ran. |
| Corrected release smoke02 | All 40 / 8,900 / 8,292 passed semantic replay | Complete smoke at the final measured refs; separate from full02. |

Smoke01's folded allocation export was **171,422,982 B**, above the original 64 MiB bound. The actual child and Heaptrack completed first. Its 16,460 rows, maximum 33,618-byte line and 140 stack frames fit the unchanged row/line/frame limits. Original failed files were preserved; an unmeasured full01 build copy is not a failed full workload.

The corrected common plan explicitly selects **256 MiB expanded folded text for catalog only**, used by compression and whole/selected replay. Gzip preserves every stack/weight and verifies the restored bytes. Historical 64 MiB defaults, ownership/codec 128 MiB selections, the ordinary 256 MiB file bound, 1 GiB evidence root, 4,000,000 interpreted records, 100,000 folded rows, 64 KiB lines and 512 frames remain unchanged. No Rust or production behavior changed for that correction. Earlier failed suites are not upgraded with the new plan or mixed into the qualified full02 root.

## Archive and reproduction

**Linux and independent Windows archive replay: PASS.** Full raw semantic replay and mandatory Linux package round-trip semantic replay passed. The [publication receipt](publication-receipt.json) records helper exit 0, unchanged source bytes, identical tar round-trip bytes and completed semantic replay. All eight package files were copied into `catalog/` with file-set, size and SHA equality; their combined size is 194,303,083 B. Independent Windows full semantic archive replay validated all 1,316 files in 322.201534700 s with exit 0; its [receipt](validation/windows-replay.json) and [log](validation/windows-replay.log) retain the exact validator and result hashes.

The compressed archive is **193,350,965 B**, SHA-256 `d9209cedec5f08354c8f00e7608c0bb5723dd6996c1a0ab9fec27434f4920cbf`. It contains **1,316 members / 777,448,331 B** of payload; the canonical USTAR stream is **778,475,520 B**. The four ordered parts are:

| Part | Bytes | SHA-256 |
| --- | ---: | --- |
| [0001](catalog/raw-evidence.tar.gz.part-0001) | 50,000,000 | `19590bfce4d9f8ad23c96f098af4bb150f550ce26ee4bea95195b26746123f35` |
| [0002](catalog/raw-evidence.tar.gz.part-0002) | 50,000,000 | `de024531a62e33d6fff182c63fa13dc732414123c1f153a89644e275bb677247` |
| [0003](catalog/raw-evidence.tar.gz.part-0003) | 50,000,000 | `3902e7828e23c907329ea8233c79d29a2ee3236d3a8fa38690d99ceef79b23e1` |
| [0004](catalog/raw-evidence.tar.gz.part-0004) | 43,350,965 | `bb50192667815b714808322d31d6b9944b9342a1ffebd88bd78b138f742d1d46` |

The [member manifest](catalog/raw-evidence.manifest.json), [ordered parts manifest](catalog/raw-evidence.parts.json), [gzip checksum](catalog/raw-evidence.tar.gz.sha256) and [outer aggregate](catalog/aggregate.json) retain the complete package bindings.

From the repository root, replay the published package with:

```sh
python tools/validate_phase1_archive.py benchmarks/optimization/catalog-memory/2026-09-10-container-linux-96716c8/catalog
```

The repository validator checks the captured source/build graph and replays the retained evidence; validation does not relabel it to the checkout used for replay.

The first packaging attempt used the existing gzip level9 path and produced 204,279,199 B, above the unchanged 198,000,000 B split limit. Packaging failed; its transient gzip was automatically removed by `TemporaryDirectory`. The measurement source, [failure log](attempts/issue107-package-02.log) and [attempt receipt](attempts/issue107-packaging-attempt-02.json) remain retained. The successful separate attempt above used stronger compatible gzip compression of the exact same canonical USTAR bytes, with the original archive limits and mandatory semantic verifier. No measurement was rerun or relabeled for compression. The earlier folded-export failure has its own [bounded diagnostic receipt](attempts/issue107-smoke01-allocation-bound.json).

The package is placed under `catalog/`; companion files are under `analysis/`. The [method](../../../../docs/testing/phase-1-measurements.md#catalog-memory-experiments) defines the backend-only build/run/replay path. Measurement reproduction uses control `397ee901ee919ae538d2a964d1543169bb740926` and candidate/harness `96716c8468e90246c59c6282d401c0f5402d0dda`, with fresh build and collection directories. The raw full source was `/workspace/project/target/optimization-catalog/full-02`, copied from the untouched completed build02 graph before measurement. Never overwrite a measured root.

The report-local [extract.py](extract.py) writes exact strings/nulls and report tables to a separate directory; it does not replace semantic validation. From this report directory, substitute actual paths in:

```sh
python extract.py <completefull-root>/aggregate.json <fresh-analysis-directory>
```

The separate postprocessing recipe [publish.py](publish.py) imports the original packaging helpers and validator from the clean measured harness. It uses pigz 2.6 with `-11 -I 15 -b 1024 -p 4 -n -c`, verifies the complete canonical USTAR length/SHA and original member hashes after gzip round-trip, then applies the unchanged split schema/bounds and mandatory `verify_package` semantic replay before publishing. Pigz's level 11 uses Zopfli within the compatible gzip format; the recipe requires pigz with that option, without a separate Zopfli executable. See the [pigz manual](https://www.zlib.net/pigz/pigz.pdf).

```sh
python publish.py --repository <clean96716c8harness> \
  --source <completefull-root> --output <fresh-package> --work <fresh-work>
```

Here `<clean96716c8harness>` is a clean checkout of the full candidate/harness commit above; `<fresh-package>` and `<fresh-work>` must not exist. Use ordinary Python with optimization disabled: no `-O` or `-OO`, and `PYTHONOPTIMIZE` unset or `0`, because the executed recipe uses assertions for its guards. This publication-only recipe changes compression, not measured source, raw evidence or populations. Its executed SHA-256 is `c29c77d32cfb16f0d7ac62b60c1e925b14ca09421325dfd9093ff8afe9888199`, matching the publication receipt.

The existing package policy keeps at most 1 GiB expanded including root suite/aggregate, 5,000 archive members and 198,000,000 split-gzip bytes in two to four parts of at most 50,000,000 B. Catalog's declared inventory remains at most 4,096 files. Generated data roots have separate 16 GiB logical / 400,016-file / 100,016-directory bounds and one final close walk; native filesystem free space does not establish physical host backing capacity. Failed diagnostics remain separate from the complete primary archive.

This full run uses one pair per shape, with distinct control first and shared candidate first. Shape, order, filesystem/cache state and allocator retention cannot be separated by this design. Repeated calls provide within-child distributions, not independent process replications. Keep the slower shared 100k paths, reopened RSS and sampled-peak limits alongside the met reference target. Historical #104-106 or older catalog medians are not subtracted to claim an unmeasured cumulative speedup or universal SLO.
