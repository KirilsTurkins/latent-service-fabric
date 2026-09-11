# Typed JSON codec comparison

Historical raw archive payloads are omitted from this checkout. Results and
original validation records remain; recorded replay passes describe publication
checks. [Restore the exact historical package](../../../../docs/testing/benchmark-retention.md) before running raw
replay or extraction commands below. Set `restored_root` to its fresh restore
directory; manifests alone do not make the current directory replayable.

The typed decoder improves warm Echo against its matched control: paired p50
falls by **20.002 us** (6/7 pairs), and observed warm server batch CPU falls from
1.78 to 1.69 s. Transform improves in every pair at p50, throughput and server
CPU. Results remain mixed: the 64 KiB payload's paired p50 rises by **13.713 us**
(5/7 pairs), compute p99 rises by 15.247 us, and sampled server RSS increases.
This is not a universal RPC speedup or a process-memory reduction.

In the separate codec processes, decode allocation count, allocated bytes and
selected live-byte peak decrease in all six families and every pair. Byte-list
and nested-record decode elapsed averages fall by paired medians of 64.579%
and 33.700%. Near-limit and escaped strings remain slightly slower, while
encoder allocation metrics are unchanged. Full semantic replay qualifies both
fixed populations, including all 84 allocation profiles.

The change decodes JSON against the component's authoritative value types
without first building a generic JSON value tree. On rejection, the legacy
decoder preserves error precedence after partial typed values are dropped.
A typed rejection that the legacy decoder accepts becomes a compatibility
error; it cannot silently produce a successful legacy fallback. The encoder is
measured separately, using the same legacy-produced input values in both arms.

## Sources and boundaries

Two separate evidence packages retain their actual measured references:

| Population | Control | Candidate and measurement harness |
| --- | --- | --- |
| External RPC, full-01 | `204439091142374a12870e88b2b9eac7ca133ccc` | `c5dd2169a8db23fe9ac232f6394eb68e5e0b269e` |
| Codec-only, full-02 | `d9fc1e80405899c6e2efaf1b1369efd61ccfa1a3` | `9a2749f6004372bf6c0c0aa20f045b1f3cacf3b0` |

Typed production behavior is unchanged between the two candidate references.
The later checkpoint contains bounded tooling/schema corrections, comments and
equivalent literal formatting. It does not relabel the earlier RPC binaries or
replace that RPC population. Common probes, inputs, CPU readers, lockfile and
build recipe match within each comparison.

The external population uses actual standalone LSF over loopback RPC and the
unchanged shared client. The no-guest population calls the actual codec in
owned `latent-wasmtime` libtest processes. It creates types but no guest Store,
instance, node or Invoke. Normal and Heaptrack children are separate processes.

| Population | Smoke | Full |
| --- | ---: | ---: |
| External offered calls, including warmup | 140 | 25,256 |
| External validated process owners | 14 | 98 |
| Codec normal and allocation children | 24 | 168 |
| Codec preflight operations | 144 | 1,008 |
| Codec warmup operations | 96 | 6,720 |
| Codec measured operations | 192 | 441,952 |
| Total codec operations | 432 | 449,680 |

The full external total includes 22,960 measured offers and 2,296 warmup calls.
There are 2,800 measured calls per arm in each of the first four cases and 280
per arm near the payload limit. All 25,256 calls succeeded semantically and on
time. Its 98 owned processes comprise 14 measured servers, 14 setup CLI owners
and 70 clients. No hidden prewarm call is added.

Codec full-02 passed full semantic replay of its fixed 168 children; independent
population and cleanup checks account for every operation. Seven pairs per
family and mode give 84 normal and
84 separately profiled children. All type owners were dropped, with zero guest
Stores and Invokes. Smoke validates the protocol and is separate from full
evidence.

## External RPC results

Control and candidate columns are medians of seven process quantiles. Paired
changes are medians of seven within-pair candidate-minus-control values, which
can differ from the difference of arm medians. Lower counts refer to the seven
paired p50 values. No samples are pooled, trimmed or excluded. Units are us.

| Case | Control p50 | Candidate p50 | Paired p50 change | Lower pairs | Paired p95 change | Paired p99 change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Warm Echo | 531.364 | 511.362 | -20.002 | 6/7 | -26.102 | -12.664 |
| Compute | 618.609 | 621.220 | -9.287 | 4/7 | -46.004 | +15.247 |
| Transform | 895.380 | 736.792 | -146.641 | 7/7 | -90.222 | -153.821 |
| 64 KiB payload | 913.112 | 929.890 | +13.713 | 2/7 | -47.983 | -165.067 |
| Near-limit payload | 1,321.994 | 1,275.638 | -97.941 | 5/7 | -156.354 | -358.117 |

Successful latency is distinct from all-offered completion elapsed, which also
includes scheduling delay. The paired all-offered p50 changes are -27.791,
-6.448, -150.991, +14.046 and -97.326 us in the same case order. The
[companion analysis](analysis.md) retains all p50/p95/p99 values, outcomes,
throughput, resource changes and order strata.

Warm successful throughput increases by a paired 67.115 responses/s in all
seven pairs; transform increases by 129.053 responses/s in all seven. The
64 KiB case falls by 4.055 responses/s, with four pairs lower. Its p50 also
depends on observed order: control-first pairs have a median +33.834 us change,
while candidate-first pairs have -60.972 us. Near-limit p99 strata likewise
disagree (+90.923 versus -650.329 us). These small strata describe variation;
they do not identify its cause.

Observed server CPU covers each batch including warmup and observation, at
100 ticks/s. It is not per-call CPU. Across all five cases, totals decrease
from 9.64 to 9.12 s, with each paired run lower. Warm-only totals decrease
1.78 to 1.69 s; transform decreases 2.75 to 2.31 s, while compute rises
2.01 to 2.02 s and 64 KiB rises 2.68 to 2.70 s. Client totals change from
4.69 to 4.62 s with mixed paired directions. Maximum sampled server RSS across
each run's five batches rises by a paired median **143,360 B** (5/7 higher).
Batch RSS maxima are not summed and are not instantaneous peaks.

The [#104 request-ownership report](../../request-ownership/2026-09-09-container-linux-2bd2452/README.md)
retained a warm p50 increase of 37.451 us and warm server CPU increase of 5.7%
over two campaigns. This new comparison improves the direction of that concern
against its own control. Historical values are not subtracted, and these seven
pairs do not prove restoration to an older binary or isolate the old cost to
JSON decoding. Remaining mixed RPC behavior stays relevant to
[#106](https://github.com/KirilsTurkins/latent-service-fabric/issues/106).

## Codec CPU, allocation and peak results

The following normal results passed independent replay of all 84 normal
children and the complete suite passed full semantic replay. Each operation
value is the median of seven process batch averages, not a per-call quantile.
Percentages are medians of paired percentages; lower counts refer to elapsed
time. Units are us per measured decode, including result Drop.

| Family | Control elapsed | Candidate elapsed | Paired elapsed change | Paired change | Lower pairs | Paired thread CPU change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Scalar parameters | 1.754 | 1.271 | -0.585 | -26.070% | 5/7 | -0.585 |
| Byte list | 437.948 | 157.192 | -285.227 | -64.579% | 7/7 | -285.198 |
| Nested record | 70.659 | 48.211 | -24.024 | -33.700% | 7/7 | -24.021 |
| 64 KiB string | 62.850 | 53.962 | -8.888 | -14.141% | 7/7 | -8.881 |
| Near-limit string | 103.162 | 105.782 | +0.693 | +0.660% | 3/7 | +0.699 |
| Escaped Unicode | 231.578 | 238.911 | +6.416 | +2.776% | 3/7 | +6.418 |

The byte list and nested record show the largest reductions. Near-limit and
escaped strings are slightly slower in four of seven pairs. Encoding uses
unchanged source and common legacy-produced inputs, yet has mixed timing:
byte-list encode elapsed rises by 4.268% (6/7 higher), while nested-record encode
falls by 12.153% (7/7 lower). These shifts are not claimed as encoder changes or
isolated decoder effects. Normal pairs interleave with their profile pairs;
the [analysis](analysis.md) preserves both actual order strata.

Whole normal process CPU sums decrease from 4.906433 to 3.162163 s. This broader
scope includes both directions and setup. Memory does not show a general
reduction: paired kernel high-water RSS rises by 384 KiB for scalar parameters,
128 KiB for nested records and 256 KiB for each string family; byte-list's paired
median is zero. These are process observations, not selected codec heap peaks.

All 84 profile attributions are available. The following selected decode values
are identical across all seven repetitions of each arm; every candidate value
is lower in every pair. Counts and allocated bytes are averages per contained
measured decode. Peak bytes are the actual undivided maximum live bytes from
allocations originating in the measured decode frame.

| Family | Allocations per decode, C / N | Allocated bytes per decode, C / N | Decode peak bytes, C / N |
| --- | ---: | ---: | ---: |
| Scalar parameters | 25 / 9 | 2,437 / 733 | 1,294 / 640 |
| Byte list | 8,216 / 4,108 | 731,424 / 458,608 | 333,071 / 196,672 |
| Nested record | 1,180 / 761 | 134,839 / 45,770 | 90,286 / 24,330 |
| 64 KiB string | 3 / 2 | 65,856 / 65,584 | 65,856 / 65,584 |
| Near-limit string | 3 / 2 | 123,200 / 122,928 | 123,200 / 122,928 |
| Escaped Unicode | 17 / 16 | 168,248 / 167,976 | 102,528 / 102,448 |

The selected encode counts, allocated bytes and peaks are equal in every pair
for all six families. The simultaneous union peak of both selected frames
falls for scalar parameters, byte lists and nested records, but stays at
131,076 B for the 64 KiB string and 245,764 B near the limit because encoding
sets their peak. Escaped Unicode's union peak falls by 80 B. All selected
allocations are freed by the end of every profile.

Whole-process profiles also include fixture/type construction, preflight,
warmup, both directions and teardown. These totals are not divided by measured
decode counts. Columns below are medians of seven owners; paired allocated-byte
changes can differ from the difference of the displayed medians.

| Family | Whole allocations, C / N | Whole allocated bytes, C / N | Paired allocated-byte change | Whole peak bytes, C / N |
| --- | ---: | ---: | ---: | ---: |
| Scalar parameters | 150,042 / 84,154 | 11,908,881 / 4,894,736 | -7,014,142 | 142,036 / 142,054 |
| Byte list | 4,911,532 / 2,467,272 | 456,007,488 / 293,684,889 | -162,322,602 | 864,623 / 744,456 |
| Nested record | 3,549,099 / 2,306,764 | 424,595,149 / 160,508,492 | -264,086,656 | 276,359 / 198,236 |
| 64 KiB string | 2,809 / 2,660 | 40,035,840 / 39,998,247 | -37,595 | 612,020 / 611,740 |
| Near-limit string | 2,397 / 2,307 | 45,710,485 / 45,688,936 | -21,553 | 1,070,788 / 1,070,508 |
| Escaped Unicode | 5,435 / 5,328 | 40,331,743 / 40,305,566 | -26,177 | 591,546 / 591,266 |

Whole allocated bytes and counts decrease in every pair. Whole peak rises by
18 B for scalar parameters in all seven pairs, while the other families fall;
it is not a universal whole-process peak reduction. Every whole profile ends
with the same three retained allocations totaling 928 B, separate from the
zero remaining selected allocations. The [analysis](analysis.md) includes
all paired counts, bytes, peaks and unchanged encode values.

Each child preflights three decode and three encode paths outside timing,
comparing public, diagnostic and legacy results against independently generated
fixed canonical bytes. Both arms retain legacy-produced values for encoding.
Warmup bypasses the named measured frames. Each frame is called once per
direction and loops over the declared measured calls, including actual codec
work, constant-time outcome/arity/length checks, `black_box` and result Drop.
There is no per-call deep hash or re-encoding inside the measured loop.

Actual thread CPU and elapsed values describe batch averages, not individual
call quantiles. The high-resolution CPU bracket includes the surrounding wall
clock calls; coarse `/proc` samples lie outside that interval. Normal whole
process CPU/RSS additionally includes setup, preflight, warmup, validation,
teardown and the two fixed 100 ms holds. Profiled CPU/RSS is not normal timing.

Selected allocation origins require exact raw/demangled symbol proofs and
agreement between complete interpreted and folded streams. Missing, ambiguous
or unresolved attribution stays unavailable. Selected totals may be divided
by contained measured codec calls only when attribution is available. Peak
bytes represent maximum simultaneous live allocation origins; frame peaks are
not summed or divided by call count. Whole-process allocation totals, selected
heap, Rust capacity, guest memory and process RSS are separate quantities.

## Retained failures, controls and validation

The first full codec attempt retained 59 children before its 256 MiB next-child
reservation exceeded the original 1 GiB root allowance. The retained root was
820,926,799 B; no children were discarded to make a smaller population. An
independent bounded inspection also found a 9,831,105-record interpreted profile
(59,457,687 B), above the original four-million-record replay limit.

Two complete repetitions retained about 188 MB each. Their seven-repetition
projection plus existing setup evidence and the unchanged reservation was
1,884,865,009 B. The corrected codec-only plan declares 2 GiB and 12 million
records, preserving all 168 children and 449,680 operations. Fresh exact-source
builds and output roots produced full-02. The failed first attempt remains
local diagnostic evidence: its 59 children completed 183,996 operations, but
never qualified as a full population.

Historical modes, including the already completed codec RPC package, retain
their original bounds and identities. Codec files remain at most 256 MiB;
folded streams remain bounded to 128 MiB, lines to 64 KiB and tables to 250,000
entries. The archive still allows at most 5,000 entries, 99 MB monolithic or
198 MB split compressed bytes. Its 2 GiB expanded allowance requires the exact
outer codec aggregate, archived bytes/kind and mandatory full replay.

The observed RPC host is Docker/WSL2 Linux on an i7-11850H with 16 logical CPUs,
a 4-CPU quota and cpuset 0-15. The build uses Rust 1.97.1, Wasmtime 47.0.3 and
the retained release recipe. Shared-host load and allocator/process sampling
remain limitations; seven pairs are descriptive, not a production SLO,
statistical significance result or equivalence claim.

Local validation reported 735 Python tests at the later checkpoint and
214 targeted Rust checks at the earlier measured production checkpoint.
CI uses the repository's scoped format/Clippy policy. A broader optional strict
diagnostic encountered older warnings and is not presented as a passing gate.
All six implementation CI jobs passed at `9a2749f`. Final publication-head CI
and mandatory archive semantic replay results are recorded in
[PR124](https://github.com/KirilsTurkins/latent-service-fabric/pull/124).
Debug functional collections establish
protocol/correctness only and do not enter the paired release results.

## Evidence and reproduction

| Package | Files | Expanded bytes | Gzip stream bytes | Gzip SHA-256 |
| --- | ---: | ---: | ---: | --- |
| RPC | 1,719 | 491,455,111 | 106,539,917 | `0e2f0fb48617e4c8c728944ca5c252928bbe0c413632039e13b598e4dc2f1c15` |
| Codec | 2,751 | 1,619,092,335 | 124,498,938 | `4645cafa392ea7dafbffe3a2eab70c519b448837af1b876d0931bb1067fff59b` |

RPC full semantic replay, Linux packaging and independent Windows archive
replay passed for all 1,719 files. The codec population passed full Linux raw
semantic replay, including all interpreted and folded allocation streams.
Independent Windows codec archive integrity verification also passed all
2,751 members, hashes, outer bindings and exact aggregate bytes using
`verify_package(..., replay=False)`. That Windows check did not replay profile
semantics. Mandatory Linux package roundtrip semantic replay and final-head CI
are merge gates whose recorded results are linked from
[PR124](https://github.com/KirilsTurkins/latent-service-fabric/pull/124).
All qualifying full raw attempts/profiles, source/build identities, helper
receipts and derived aggregate inputs remain in their respective archives.
The codec package uses gzip level 9 and three parts of 50,000,000, 50,000,000
and 24,498,938 B, within the unchanged 198 MB compressed bound.

The [collection method](../../../../docs/testing/phase-1-measurements.md#typed-codec-experiments)
defines one exact-source build, fresh smoke/full copies and separate RPC/codec
collection. The corrected codec full collection executed from the clean
`9a2749f` harness with its retained copied builds:

```sh
python3 tools/run_optimization_backend_revision.py --experiment codec --profile full \
  --builds target/optimization-codec/direct-full-02/backend-builds.json \
  --target-root /workspace/issue105-data-02
```

The corrected build-only pass can be reproduced with the CLI's full option
names below. It retains both output roots; only the corrected codec root was
copied for fresh smoke/full-02 collection. The RPC result remains full-01 at
its earlier references.

```sh
python3 tools/run_optimization_revision_benchmarks.py --experiment codec --profile full \
  --control-ref d9fc1e80405899c6e2efaf1b1369efd61ccfa1a3 \
  --candidate-ref 9a2749f6004372bf6c0c0aa20f045b1f3cacf3b0 \
  --harness-ref 9a2749f6004372bf6c0c0aa20f045b1f3cacf3b0 \
  --target-root /workspace/issue105-builds-02 \
  --output target/optimization-codec/build-only-rpc-02 \
  --backend-build-output target/optimization-codec/build-only-direct-02 --build-only

test ! -e target/optimization-codec/direct-smoke-02 && \
  cp -a target/optimization-codec/build-only-direct-02 target/optimization-codec/direct-smoke-02
test ! -e target/optimization-codec/direct-full-02 && \
  cp -a target/optimization-codec/build-only-direct-02 target/optimization-codec/direct-full-02
python3 tools/run_optimization_backend_revision.py --experiment codec --profile smoke \
  --builds target/optimization-codec/direct-smoke-02/backend-builds.json \
  --target-root /workspace/issue105-data-02
```

Run the full command above after smoke, without overwriting either evidence
root. Independent archive replay:

```sh
python tools/validate_phase1_archive.py \
  "${restored_root}/benchmarks/optimization/typed-codec/2026-09-09-container-linux-9a2749f/rpc"
python tools/validate_phase1_archive.py \
  "${restored_root}/benchmarks/optimization/typed-codec/2026-09-09-container-linux-9a2749f/codec"
```

Archive replay validates retained evidence without executing its binaries.
Build-only and collection have independent 7,200 s limits; build commands have
3,600 s, normal children 90 s, profiled children 180 s and extraction tools
120 s, each clipped to its owning stage. The retained receipts record these
independent elapsed stages; they exclude subsequent offline allocation replay
and archive publication:

| Stage | Elapsed seconds |
| --- | ---: |
| Primary build-only-01 | 472.855184247 |
| Primary RPC full-01 collection | 50.852850023 |
| Corrected build-only-02 | 455.764404385 |
| Corrected codec full-02 collection, including profile extraction | 351.227009993 |

The RPC suite separately records 50.765042962 s inside its measurement window.
These are separate stage receipts, not one shared campaign deadline or a total
that includes the retained smoke and failed attempts.
