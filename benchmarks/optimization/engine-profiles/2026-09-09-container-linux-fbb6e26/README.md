# Bounded Wasmtime engine profiles (#106)

**Keep on-demand/speed (D0) as the default.** Pooling reduced warm setup in every phase and all seven pairs, but increased fresh compilation time, retained virtual mappings, RSS, and compiled-image charges. Its much lower virtual high-water values do not make it a general low-memory setting. Speed-and-size produced no compiled-image charge reduction in these fixtures and had mixed latency results.

The separate default-path external comparison had lower paired p50/p95 and batch CPU, but higher successful-response p99 and order-dependent RSS. Matrix D0's Echo p50 was higher than its matched old control. The two measurement boundaries remain separate; neither establishes a universal warm-path speedup or an SLO.

## Sources, controls, and complete populations

| Evidence | Control | Candidate and shared harness |
| --- | --- | --- |
| Primary external04 | `172c5a3f2ea9c8b233a780bafdcb4c2d453f939b` | `9e50564cb2fbe78e1c136e634fcca6747c6779f8` |
| Primary matrix05 | `d4eac343cd4e0a87a4d1c1a0c0f288e6e6537a2f` | `fbb6e2601d85a344898c5f6220d4ebe03e0a59a7` |

The matrix05 common correction changed five files: its Rust per-offer clock projection, Python request replay, two focused test modules, and method documentation. Both source arms received that correction; the same 20 product-file differences remained unchanged. The completed external04 campaign was retained before inspecting its metrics. It was not relabelled or rerun to select a favorable outcome. Exact clean trees, executable/component hashes, configuration digests and source receipts are retained with each archive.

The matched release builds used Rust 1.97.1, Wasmtime 47.0.3 and `x86_64-unknown-linux-gnu`, with the retained locked release recipe. The host was an i7-11850H with 16 logical CPUs under Docker/WSL2 Linux 6.6.87.2; the recorded cgroup CPU quota was 400000/100000, cpuset 0-15, memory maximum `max`. Actual CPU counters ran at 100 Hz. Shared-runner cgroup observations are not isolated per-service resource measurements.

| Population | Complete full count | Statistical unit |
| --- | ---: | --- |
| External defaults | 6,160 Invokes: 560 warmup + 5,600 measured; 42 validated owners | Seven server/client process pairs |
| Five-row matrix | 27,790 Invokes; 56,315 commands; 35 owners | Seven five-row blocks |
| Matrix composition | 1,750 warmup + 25,200 measured ordinary + 840 functional | 50 + 720 + 24 Invokes per owner |
| Actual matrix outcomes | 27,475 successes + 315 intentional platform failures | Every offered invocation retained |
| Combined Invokes | 33,950 | Accounting total only; timings are not pooled |

Each matrix owner compiled eight distinct releases once and retained 794 Invokes / 1,609 commands. Ordinary measured phases were Echo 400, compute 128, 4 MiB memory initialization 64, and four-wide Echo 128; other phases had width one. Setup included eight publications and eight deployment applications. Every Invoke had one status command; the functional slice added five accepted Cancels. External owners had 40 warmup and 400 measured offers each, with no hidden prewarm. Its 42 owners comprise 14 seed servers, 14 measured servers and 14 clients; helper receipts are retained separately.

## Profiles and comparison method

| Row | Source | Allocator / optimization | Memory reservation / guard / growth reservation |
| --- | --- | --- | --- |
| O | Control containing merged #105 | Existing on-demand / speed | 4 GiB / 32 MiB / 2 GiB |
| D0 | Candidate | On-demand / speed | 4 GiB / 32 MiB / 2 GiB |
| P0 | Candidate | Pooling / speed | 64 MiB / 0 / 0 |
| D1 | Candidate | On-demand / speed-and-size | 4 GiB / 32 MiB / 2 GiB |
| P1 | Candidate | Pooling / speed-and-size | 64 MiB / 0 / 0 |

All rows retained four execution cells, queue capacity 64, cache capacity eight, four preparation jobs and two compiler workers. Pooling capacities were bounded by execution capacity; zero keep-resident thresholds, zero unused warm slots and decommit batch one are policy settings, not measured zero RSS. The 512 MiB retention allowance and 512 MiB image-charge ceiling are limits, not observed allocation.

The fixed orders were `O D0 P0 D1 P1`; `O P1 D1 P0 D0`; `P0 D1 P1 O D0`; `P0 D0 O P1 D1`; `P1 O D0 P0 D1`; `P1 D1 P0 D0 O`; `D0 P0 D1 P1 O`. Default preservation compares D0 with O. P0, D1 and P1 each reuse the same actual D0 in that block. Pooling changes allocator and memory layout together; P1 additionally changes optimization, so those effects are not isolated compiler causality.

Tables report medians of seven process observations and median paired differences. A difference of row medians is not the median paired difference. `[L/E/H]` counts lower/equal/higher candidate values; all displayed contrasts have seven available pairs. [Complete analysis](analysis.json) preserves exact values, per-pair percentages, all seven pair records, execution-order strata, outcomes and unavailable fields; [the readable companion](analysis.md) contains additional tables. Individual calls are not pooled into artificial independent repetitions.

## External default-path follow-up

The external aggregate is full/complete with both completeness flags true: 6,160 validated Invokes, 42 owners and seven pairs. Every call succeeded on time, including 280 warmup and 2,800 measured offers per arm; no failure or outlier was removed. These results come from the unchanged retained full04 aggregate, independently checked for exact pair associations and paired arithmetic.

| Quantity | Control process median | Candidate process median | Median paired delta | Lower/equal/higher | Available pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| Successful response p50 (us) | 525.7915 | 513.0115 | -13.0635 | 5/0/2 | 7/7 |
| Successful response p95 (us) | 986.765 | 905.782 | -81.542 | 5/0/2 | 7/7 |
| Successful response p99 (us) | 1,273.965 | 1,299.335 | +28.086 | 3/0/4 | 7/7 |
| All-offered elapsed p50 (us) | 589.0105 | 579.4005 | -8.0655 | 5/0/2 | 7/7 |
| All-offered elapsed p95 (us) | 1,076.263 | 1,006.613 | -47.889 | 6/0/1 | 7/7 |
| All-offered elapsed p99 (us) | 1,394.547 | 1,353.265 | -59.569 | 4/0/3 | 7/7 |
| Measured successes/s (= attempts/s) | 1,380.779141 | 1,406.851016 | +16.276728 | 3/0/4 | 7/7 |
| Server batch CPU (ticks) | 25 | 24 | -1 | 4/2/1 | 7/7 |
| Client batch CPU (ticks) | 13 | 12 | -1 | 4/1/2 | 7/7 |
| Server sampled maximum RSS (bytes) | 25,657,344 | 25,796,608 | -53,248 | 4/0/3 | 7/7 |
| Client sampled maximum RSS (bytes) | 4,587,520 | 4,587,520 | 0 | 3/2/2 | 7/7 |

Actual clock frequency was 100 Hz. Summed server batch CPU was 1.82 to 1.70 s; client CPU was 0.90 to 0.86 s. These are totals over seven batch windows per arm, distinct from the paired process medians above. Collection elapsed 17.651233992 s; suite elapsed 17.742795272 s.

The control-first subset has successful p50 paired median -5.32925 us (2/4 lower), versus -35.753 us (3/3 lower) in the candidate-first subset. For server RSS, all four control-first pairs are lower (paired median -178,176 bytes), while all three candidate-first pairs are higher (+368,640 bytes). The opposing RSS strata and higher successful p99 remain part of the result; neither the lower central latency nor the negative overall paired RSS median supports a universal performance or resident-memory claim. All seven pairs and both order strata remain in the external analysis.

Successful latency is conditional on success; all-offered elapsed retains scheduling gaps. Throughput spans the first scheduled measured offer to final completion. Server/client CPU and sampled RSS cover the full batch, including warmup and observation, not per-call CPU or an instantaneous memory peak. Cgroup observations describe the shared runner and need their actual scope and unavailable reasons.

This slice measures omitted-configuration defaults in control and candidate. Matrix D0 selects the equivalent policy explicitly. The external D0 result cannot qualify external warm performance for P0, D1, or P1; choosing one of those as a new default would require its own predeclared external follow-up.

## First response, compilation, and process CPU

Each fresh owner contributed one first Echo warmup. That response includes acquisition, compilation and invocation; it is not an engine-construction-only timer. The following are medians across seven owners. Compilation CPU is the actual compiler-thread tick delta; the first-compilation resolution is coarse at 100 Hz.

| Quantity | O | D0 | P0 | D1 | P1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| First Echo RPC (ms) | 34.827748 | 36.030747 | 39.429435 | 35.192727 | 37.899789 |
| First Echo Component::new (ms) | 32.772646 | 33.82151 | 36.892663 | 32.590719 | 35.670772 |
| First Echo compilation CPU (ticks) | 3 | 3 | 3 | 2 | 3 |
| Median of eight Component::new spans (ms) | 32.188656 | 33.250055 | 39.503624 | 33.727406 | 36.74837 |
| Total of eight Component::new spans (ms) | 228.951052 | 235.186103 | 276.194748 | 235.864614 | 263.60937 |
| Eight compilations' CPU (s) | 0.21 | 0.22 | 0.26 | 0.22 | 0.24 |
| Population-and-controls process CPU (s) | 2.89 | 2.82 | 2.85 | 2.84 | 2.82 |

P0 versus D0 added a paired 3.398688 ms to the first RPC (6/7 higher), 34.450716 ms to the total eight Component::new spans (7/7 higher), and 0.05 s compilation CPU (7/7 higher). P1 added 2.848380 ms, 31.846588 ms and 0.03 s respectively. The per-owner median Component::new span increased by paired 7.015 ms for P0 and 3.500 ms for P1, both 7/7 higher. These per-job medians and eight-job totals are different quantities.

Whole population-and-controls CPU paired deltas were -0.10 s for D0 - O (5/7 lower), -0.05 s for P0 - D0 (4/7 lower), -0.01 s for D1 - D0 (4/7 lower), and -0.06 s for P1 - D0 (6/7 lower). Those combined node/client/functional/observation windows do not establish per-call CPU or replace external server CPU. Raw repository verification, metadata validation, compilation, linking, cache adoption, whole-job and queue-wait stages remain available; whole-job spans overlap their children and must not be added to them.

## Warm RPC and native timing

Every cell below is the median paired delta in **microseconds**, followed by `[lower/equal/higher]`. RPC quantiles are conditional on successful responses; all-offered p50/p95/p99, per-phase process CPU, throughput and timing p95 remain in the complete analysis.

| Contrast | Phase | RPC p50 | RPC p99 | Setup p50 | Guest p50 | Reclamation p50 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| D0 - O | echo | 5.8935 [1/0/6] | 47.189 [3/0/4] | 3 [1/1/5] | 1 [1/1/5] | 1 [2/1/4] |
| D0 - O | compute | -69.4315 [5/0/2] | -62.153 [4/0/3] | 1 [3/0/4] | 0 [3/1/3] | -2 [4/1/2] |
| D0 - O | memory | -403.339 [6/0/1] | -853.61 [4/0/3] | 2 [3/0/4] | -557.5 [6/0/1] | -0.5 [5/0/2] |
| D0 - O | concurrent-echo | -19.26 [5/0/2] | 128.584 [3/0/4] | -2 [5/0/2] | 4 [3/0/4] | 0.5 [3/0/4] |
| P0 - D0 | echo | -53.2585 [6/0/1] | -141.5 [6/0/1] | -18 [7/0/0] | -7 [6/0/1] | -2 [6/0/1] |
| P0 - D0 | compute | -176.653 [6/0/1] | -283.317 [5/0/2] | -16 [7/0/0] | -186 [7/0/0] | -12 [7/0/0] |
| P0 - D0 | memory | -331.0795 [6/0/1] | -193.996 [4/0/3] | -18 [7/0/0] | -273 [6/0/1] | -10.5 [4/0/3] |
| P0 - D0 | concurrent-echo | -106.481 [7/0/0] | -275.47 [6/0/1] | -29 [7/0/0] | -13 [6/0/1] | -4 [6/0/1] |
| D1 - D0 | echo | -6.321 [6/0/1] | -127.82 [4/0/3] | -1 [4/1/2] | -0.5 [4/2/1] | 0 [3/2/2] |
| D1 - D0 | compute | 33.005 [2/0/5] | 54.48 [3/0/4] | 0 [3/1/3] | -6 [4/0/3] | 0.5 [3/0/4] |
| D1 - D0 | memory | -247.987 [4/0/3] | -109.415 [4/0/3] | -2.5 [4/0/3] | 8.5 [3/0/4] | -1 [4/0/3] |
| D1 - D0 | concurrent-echo | -25.06 [4/0/3] | 16.079 [3/0/4] | -0.5 [4/0/3] | -6.5 [5/0/2] | 1.5 [2/1/4] |
| P1 - D0 | echo | -15.159 [5/0/2] | -51.411 [4/0/3] | -17 [7/0/0] | -4 [7/0/0] | -2 [6/0/1] |
| P1 - D0 | compute | -170.526 [7/0/0] | -311.589 [5/0/2] | -16.5 [7/0/0] | -168.5 [7/0/0] | -11 [7/0/0] |
| P1 - D0 | memory | -1,152.2535 [7/0/0] | -160.68 [4/0/3] | -26 [7/0/0] | -1,004 [7/0/0] | -17.5 [6/0/1] |
| P1 - D0 | concurrent-echo | -111.921 [7/0/0] | -81.683 [4/0/3] | -30 [7/0/0] | -13.5 [6/0/1] | -3 [7/0/0] |

Pooling setup fell in all seven pairs in all four phases. The default-preservation Echo p50 increased 5.8935 us in the matrix (6/7 higher), while the separate external median paired p50 fell 13.0635 us (5/7 lower). They have different boundaries and overheads, so neither result erases the other. D1's compute p50 increased 33.005 us (5/7 higher); its speed-and-size name is not evidence of a free latency or footprint improvement.

RPC latency stops at response receipt before validation/status. Matrix batch throughput includes Invoke, status, validation and evidence retention. Guest-call timing includes canonical post-return; the separate component-post-return field records the later host-accounting span. Host-call time is a subset of guest-call time. Overlapping timing categories are not summed into an invented runtime-exclusive duration.

## Virtual mappings, resident memory, and code charges

These are medians across seven owners, rounded to three decimals for MiB. Empty means after publication but before the first Invoke; before-shutdown follows drained work while the prepared cache remains resident. Captured maxima include the complete owner, including functional work. All shown memory fields were available in all seven owners per row.

| Quantity | O | D0 | P0 | D1 | P1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Empty VmSize (MiB) | 821.871 | 821.926 | 1,342.566 | 821.926 | 1,342.566 |
| Before-shutdown VmSize (MiB) | 823.102 | 823.156 | 1,343.879 | 823.156 | 1,343.879 |
| Highest captured VmPeak (MiB) | 17,471.117 | 17,471.172 | 1,343.879 | 17,471.172 | 1,406.555 |
| Highest captured RSS (MiB) | 32.059 | 31.93 | 32.715 | 32.031 | 32.852 |
| Highest captured VmHWM (MiB) | 34.938 | 34.969 | 35.836 | 35.09 | 35.996 |
| Before-shutdown PSS (MiB) | 31.514 | 31.442 | 32.32 | 31.628 | 32.408 |
| Before-shutdown private dirty (MiB) | 11.277 | 11.043 | 12.094 | 11.43 | 12.383 |
| Resident compiled-image span charge (bytes) | 743,312 | 743,312 | 829,360 | 743,312 | 829,360 |
| After-shutdown VmSize (MiB) | 821.742 | 821.797 | 821.797 | 821.797 | 821.797 |
| After-shutdown RSS (MiB) | 32.059 | 31.93 | 32.629 | 32.012 | 32.441 |

Against D0, both pooling profiles increased before-shutdown VmSize by paired **520.722656 MiB** and resident compiled-image span charge by **86,048 bytes**, all seven pairs higher. Captured maximum RSS increased **765,952 bytes** for P0 and **876,544 bytes** for P1, again all seven higher. VmPeak moved the other way: paired -16,127.292969 MiB for P0 and -16,064.617188 MiB for P1, all seven lower. Pooling therefore reduced the high-water virtual-address requirement while retaining larger current mappings and more resident memory in this workload.

D1 retained exactly the same 743,312-byte compiled-image charge as D0 in all seven pairs; P1 retained the same 829,360-byte charge as P0. Speed-and-size did not produce an observed image-span reduction here. Logical address-span charge is not ELF file size, committed pages or RSS. VmPeak/VmHWM are kernel high-water observations, RSS maxima are sampled values, and smaps PSS/private/shared values have their own capture boundaries. Their differences are not exact committed-page counts. #106 did not run Heaptrack and makes no allocation-per-call claim.

For repeated fresh instantiation where these retained-memory and compilation costs are acceptable, P0 is a supported opt-in with consistent setup reductions. P1 may be relevant to a workload resembling the measured memory loop, but its combined policy and unchanged pooling image charge require workload-specific evaluation. D1 is not justified as a lower-footprint choice by these fixtures. Keep D0 as the default; any proposal to change the external default to P0/D1/P1 needs a separately predeclared external warm comparison.

## Correctness and owned cleanup

All 35 owners passed the fixed functional graph: 24 Invokes / 53 commands each, 15 successes, nine intentional platform failures, five accepted Cancels, ten functional guest logs, and 20 idle proofs. The graph checked tenant context/trace authority, clocks and log-byte accounting, global and memory reset, fuel/memory/deadline faults, trap/cancel recovery, four live holders, an actually queued fifth call, and three remaining live holders after its success. The scheduler proof does not identify a physical Wasmtime slot; separate bounded native one-slot tests cover exhaustion and reset.

A separate native test, `every_profile_drops_pending_native_ownership_and_recovers_the_only_slot`, passed across all four candidate profiles in 2.02 s. It dropped an actual Pending prepared-owner future with a live Store, checked zero native and affine ownership counters, recovered the sole slot with a fresh `bump = 1`, and joined the factory's workers. This direct-abort witness is separate from the matrix's cooperative Cancel checks. It was added and run after measurement as a test-only change; production behavior and the measured source identities above remained unchanged.

Fuel/memory causes came from two existing tenant-scoped native retained-status reads bound to the same activation, release/revision and consumption. Public RPC details remained redacted. Fresh per-offer wall-clock projection preserved the five-second outer monotonic deadline and unchanged native grants; replay bound each sample before dispatch and checked the actual admitted inner deadline. The ordinary Echo log oracle checked behavior already present in both production arms, including its input-byte and outcome fields.

All owners shut down cleanly with zero quarantine/live native transients and joined compiler, epoch, invocation/control/client runtimes and transport-cleanup driver. The independent final runtime ledger had zero live, resident, unpublished and evicted-live populations and all corresponding source/metadata/compiled-image charges. Bounded telemetry history remained permitted; it is not a live Store or cache runtime. Post-shutdown process RSS is therefore not claimed to be zero.

## Retained failures and corrections

Failed attempts supply no selected full-performance result, and no corrected identity is substituted into an older attempt. The [retained diagnostic subset](retained-diagnostics/README.md) publishes original raw reports and validation receipts for four earlier release attempts, including all ten actual owners. It excludes executables, source trees and other unselected dependencies and is not a qualifying Phase1 evidence archive. The complete original attempt roots remain preserved separately.

| Retained attempt | Actual work and outcome | Correction / qualification boundary |
| --- | --- | --- |
| Matrix smoke01 | 0 Invokes; work counter records one attempted publication; no response/sample row emitted | Namespace validation correctly rejected mismatched fixture tenant/world/export names. Actual outer exports and matching metadata were retargeted; nested guest code/imports remained unchanged. |
| Matrix smoke02 | 52 Invokes / 125 commands: 34 gRPC InvalidArgument, 17 successes, one expected platform failure | Caller deadline ceil could produce 5001 ms against the 5000 ms maximum; fn01 also had a wrong WIT None oracle. Common corrections conservatively floor the deadline and check `{none:null}`. |
| Dirty snapshot10 D0 | 52 / 125; 43 successes, nine expected platform failures; only fuel/memory semantic oracles failed | Public redaction was correct. Add the two bounded existing-native-status witnesses instead of exposing private causes publicly. |
| Dirty snapshot11 first D0 attempt | 0 Invokes, before identity construction | Missing snapshot copy from orchestration ordering; retained separately. |
| Corrected dirty snapshot11 D0 and P0 | Each 52 / 125, ten functional logs, all witnesses matched, clean joined shutdown | Actual functional and Python regression checks only; dirty-source identity is not release qualification. |
| Matrix smoke03 at 807a1a8 | All five actual collectors passed 260 Invokes / 625 commands; CLI then failed with `engine-unexpected-guest-log` during Python replay | Ordinary Echo already emits an info `echo invocation` result log. Python wrongly rejected it; Rust execution and logging were correct. |
| Separate smoke03 validator-workingtree replay | Entire original suite passed 260 / 625 / five owners in 1.504234302 s; both smoke completeness flags true | Original suite and identities unchanged. Derived aggregate correctly remains `incomplete` for a smoke profile. It is a separately labelled diagnostic derivation, not a new collection or full campaign. |
| Matrix full04 | Three owners actually offered 794 Invokes each: 2,382 total / 4,827 commands. Control D0 and candidate D0 each passed 785 successes and nine expected faults; candidate P0 retained 448 successes followed by 346 gRPC InvalidArgument failures | Actual message: `deadline exceeds the configured maximum`, starting at ordinal 449 after 1.118692798 s. All three owners shut down cleanly. The failed aggregate counts only the two validated owners, 1,588 Invokes / 3,218 commands / two processes; it is not a qualified full matrix. |
| Dirty snapshot13 full-population P0 regression | 794 Invokes / 1,609 commands: 785 successes and nine intentional faults; strict Python call/status/diagnostic/native-proof graph replay passed | Validates the corrected per-offer projection through the full P0 workload. This dirty-source regression is not a release benchmark or a replacement matrix profile result. |

For the 24 recorded P0 functional ingress samples in failed full04, the frozen-origin projection exceeded the actual ingress Unix-ms floor by 2.749 to 3.619 ms; caller deadlines were 5,002 or 5,003 ms above that floor. The actual body-decoding Unix sample is not recorded, so the underlying clock-difference cause remains unresolved. Matrix05 removes dependence on the frozen origin by sampling the wall clock for every offer. It preserves the rejected offers and failed root instead of upgrading them into corrected evidence.

The smoke03 correction touches exactly `engine/diagnostic.py` and `test_optimization_engine_functional.py`: the oracle verifies the actual Echo level/message, activation ID, input UTF-8 byte length, success outcome and host correlation fields; the real D0/P0 fixture tests now cover ordinary oracles and 12 rehashed Echo log mutations. Both files are common to release04 control/candidate. The unchanged original smoke03 suite SHA-256 is `bd958ef09bd53b295e6e7a317352104fe6501c9e1247ad6c0002ae74d925e960`; the separate replay receipt records all loaded validator module hashes.

Earlier syntax/type/namespace/lint and command-environment failures remain in the detailed validation inventory. In particular, the first Windows discovery run used missing Linux tools/wrong shell assumptions; its errors were not runtime correctness results. Correct Linux runs and correctly scoped lint commands are reported independently. Do not combine retries into a fabricated clean first attempt.

## Validation and evidence

Both primary full populations passed semantic replay. The immutable external04 and matrix05 archives each passed mandatory Linux package semantic replay and independent Windows full semantic archive replay. Local checks included 279 native Rust tests and 30 bounded native command receipts at the unchanged product implementation; later common namespace/clock regressions and strict Clippy passed. Linux Python discovery passed 776 tests at 807a1a8; the final clock correction passed 47 focused Python tests, repository validation passed 2,188 files, and foundation validation passed. Six native clock/status units passed before a private-field rename; strict Clippy passed afterward. The later all-profile direct-abort test passed on snapshot14 (`5f865ffb786712a0b098d014b9e6b98688d61de53b503ec557013e5dfde207de`), followed by Wasmtime all-targets/all-features Clippy in 7.74 s. These overlapping checks are not summed. Final-head CI remains a separate required PR merge gate.

| Archive | Files | Expanded bytes | Gzip bytes | SHA-256 |
| --- | ---: | ---: | ---: | --- |
| [External04 manifest](external-rpc/raw-evidence.manifest.json) | 1,133 | 461,428,230 | 103,718,971 | `156015dacbb733f4675b4da5884afd4355c0c6422e3d9f66d1c2dfc8af97562f` |
| [Matrix05 manifest](matrix/raw-evidence.manifest.json) | 1,750 | 567,510,275 | 109,724,887 | `459aae84e4848688402c9d5021e3336b3f934f42f35b6c560a04867452927e6a` |

Both use three parts: 50,000,000 / 50,000,000 / 3,718,971 bytes externally and 50,000,000 / 50,000,000 / 9,724,887 bytes for the matrix. Each part has its own retained checksum. Existing 1 GiB expanded, 256 MiB ordinary-member and 198 MB split-compressed bounds remain unchanged. Each archive retains all original inputs, raw attempts, process/build receipts and declared artifacts for its corresponding primary full population. Older attempts are represented by the separately labelled diagnostic subset above.

External aggregate SHA-256 is `b2cc3e2ac920b7a7ee52d53a81958a25d5ebcadfdebfe0b72dd696efcade2501`; matrix aggregate is `17a9006902fb424e31741179f089aa16306cba98488ae651671f5b1c952fbe15`. Their suite hashes are `92f17fe3c2afd162828b7dc75f628e7740772769743333a30bb2b6e18917cec2` and `9024d42fedeef0381375dbeebf6383f4a713bca55f548dc1c6b1cf2a2fa77e6f`. Matrix collection took 116.793424432 s; external collection took 17.651233992 s. Build and collection stages have independent limits, not a single shared campaign deadline.

The [measurement method](../../../../docs/testing/phase-1-measurements.md#engine-profile-experiments) defines exact-source build-only/prebuilt collection and strict archive replay. [analyze.py](analyze.py) reproduces descriptive extraction from complete aggregates and matching suites/raw files without invoking workloads or replacing semantic validation. [external-analysis.md](external-analysis.md) retains the standalone campaign's seven pairs and order strata; the combined analysis also retains their unrounded data.

The retained build/collection commands below require fresh output directories. Use separate clean workspaces at each named harness revision when reproducing them; never overwrite the retained evidence. The external build04 used:

```sh
python3 tools/run_optimization_revision_benchmarks.py --experiment engine --profile full \
  --control-ref 172c5a3f2ea9c8b233a780bafdcb4c2d453f939b \
  --candidate-ref 9e50564cb2fbe78e1c136e634fcca6747c6779f8 \
  --harness-ref 9e50564cb2fbe78e1c136e634fcca6747c6779f8 \
  --target-root /workspace/issue106-builds-04 \
  --output target/optimization-engine/build-only-rpc-04 \
  --backend-build-output target/optimization-engine/build-only-matrix-04 --build-only
```

The corrected matrix build05 used the identical build mode with its actual source refs:

```sh
python3 tools/run_optimization_revision_benchmarks.py --experiment engine --profile full \
  --control-ref d4eac343cd4e0a87a4d1c1a0c0f288e6e6537a2f \
  --candidate-ref fbb6e2601d85a344898c5f6220d4ebe03e0a59a7 \
  --harness-ref fbb6e2601d85a344898c5f6220d4ebe03e0a59a7 \
  --target-root /workspace/issue106-builds-05 \
  --output target/optimization-engine/build-only-rpc-05 \
  --backend-build-output target/optimization-engine/build-only-matrix-05 --build-only
```

Before either stage's measurements, copy its completed build-only directories into fresh smoke/full siblings (`rpc-smoke-04`, `rpc-full-04`, `matrix-smoke-04`, `matrix-full-04`, and the corresponding `-05` names). A copy must fail if its destination exists; preserve the build-only originals. Smoke04 preceded external full04; corrected matrix smoke05 preceded matrix full05. The relevant collection commands were:

```sh
python3 tools/run_optimization_revision_benchmarks.py --experiment engine --profile smoke \
  --builds target/optimization-engine/rpc-smoke-04/revision-builds.json --target-root /workspace/issue106-data
python3 tools/run_optimization_backend_revision.py --experiment engine --profile smoke \
  --builds target/optimization-engine/matrix-smoke-04/backend-builds.json --target-root /workspace/issue106-data
python3 tools/run_optimization_revision_benchmarks.py --experiment engine --profile full \
  --builds target/optimization-engine/rpc-full-04/revision-builds.json --target-root /workspace/issue106-data
python3 tools/run_optimization_backend_revision.py --experiment engine --profile smoke \
  --builds target/optimization-engine/matrix-smoke-05/backend-builds.json --target-root /workspace/issue106-data
python3 tools/run_optimization_backend_revision.py --experiment engine --profile full \
  --builds target/optimization-engine/matrix-full-05/backend-builds.json --target-root /workspace/issue106-data
```

The common data parent is shared only as a directory: every owner gets a fresh bounded child and retains its own cleanup receipt. The failed matrix-full-04 root is preserved separately. Its two successful rows are not substituted into the corrected five-row campaign.

## Historical boundary

[The #104 report](../../request-ownership/2026-09-09-container-linux-2bd2452/README.md) retained warm paired p50 +37.451 us (9/14 higher) and warm server batch CPU 4.18 to 4.42 s, with larger-payload direction reversals. [The #105 report](../../typed-codec/2026-09-09-container-linux-9a2749f/README.md) measured its own warm paired p50 -20.002 us (6/7 lower), server CPU 1.78 to 1.69 s, mixed 64 KiB/compute tails and higher sampled RSS. Different revisions and campaigns are not a synthetic third arm: these medians are not subtracted to claim that an earlier cost was erased. The mixed default-path observations, retained-memory costs and supported opt-in tuning boundary remain part of #113's evidence record. Seven pairs and small order strata do not establish equivalence or a universal SLO.
