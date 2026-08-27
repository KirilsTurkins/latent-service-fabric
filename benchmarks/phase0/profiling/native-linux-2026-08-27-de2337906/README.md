# Native-Linux Phase 0 hot-path profile archive

**Status:** pass. This is the accepted issue-40 CPU/allocation evidence for
the fixed Phase 0 configuration, captured on native Fedora Linux on
2026-08-27. It is observational optimization evidence, not a production SLO,
cross-platform conclusion, or a replacement for issue 39's 3x100k soak.

The measured source is the durable branch commit
[`de2337906`](https://github.com/KirilsTurkins/latent-service-fabric/commit/de2337906a4942e47611124a1c2217949abb58dc)
with Git tree `0a32896faa58da7f34662cbf3be97670d6d1de4c`, reachable from
`benchmark/phase-0-hot-path-profiling` at collection time. Every profile and
candidate command records this source identity, the resolved ref head, the
fixture/probe paths, and the effective runtime configuration. The recorded
local `execution_commit` is `78c153c186f4a2b0bdd3cdbd297a47943eda3738`; its
`execution_tree` is exactly the durable published tree above. This distinction
is intentional and auditable: the runner rejects execution unless the local
tree equals the published commit's resolved tree.

Every raw full, targeted, and candidate baseline also retains its own runtime
environment. Aggregation requires its OS, architecture, kernel, Rust/Cargo
toolchain, CPU/memory fields, target/profile, Wasmtime pin, and execution
commit to match both the captured host and the full-invariant proof.

## Checked-in entry points

- `PROFILE.md` is the concise human-readable outcome and Phase 1 handoff.
- `aggregate.json` is the compact machine-readable aggregate. Its paths are
  relative to the extracted raw archive, and it retains checksums for every
  referenced item.
- `host-before.json` captures the native-Linux host, kernel, toolchain,
  allocator, power/load, and virtualization context.
- `raw-evidence.parts.json` describes the lossless raw archive and its nine
  ordered sub-1 MB fragments. The reassembler verifies each fragment and the
  completed `raw-evidence.tar.zst` checksum before extraction;
  `raw-evidence.manifest.sha256` then verifies every extracted file.

The raw archive contains the separate uninstrumented full-invariant proof,
eight scenario-selective `perf` and Heaptrack processes (cold preparation,
direct cache reuse, first activation, warm execution, failure containment,
cleanup, at-capacity contention, and queued contention), and all three
independent full processes for each worker/cell, allocator, COW, and
cache-disabled candidate. It retains every `perf.data`, symbolized report,
native Heaptrack trace/report, exact command, fixture bootstrap, host context,
and raw result. The archive is split only for repository transport; its
manifest and reassembler retain the same byte-for-byte zstd payload without
discarding or sampling data.

## Interpretation

Unprofiled candidate runs use the calibrated cooperative `yield_now()`
coordination method (`--coordination-poll-interval-ms 0`). Only targeted
profiler processes use the one-millisecond poll interval. The candidate sets
contain three runs, and their source tree differs from the issue-38 calibration,
so every issue-38 comparison is explicitly **inconclusive**—never labelled
inside or outside an advisory band and never used for adoption.

The aggregate quantifies CPU self/inclusive percentages and Heaptrack
allocation calls/peak bytes per required contributor category for every
workload, including `unmatched_or_unknown`. Heaptrack folded stacks are read
root-to-leaf but classified from the allocation leaf toward the root: allocator,
generic-container, dynamic-loader, and async/runtime plumbing are skipped, and
only the first remaining owner frame is eligible for category precedence. An
outer `Result`, `PlatformError`, or `GuestOutcome` type therefore cannot
override a direct preparation, store, or other owner frame. It does not treat
generic `memcpy`, `memmove`, or the word `component` as WIT/payload-copy
evidence. Payload input/output counters are retained separately;
`copy_bytes_claimed` remains an unclaimed zero when no narrow canonical
WIT/copy symbol supports a byte claim; that sentinel is not a measurement of
zero copied bytes. Categories without direct profiler samples are labelled
**not observed at profiler resolution**, not measured zero cost.

Heaptrack records the same 2.82 KiB process-exit residue in all eight targeted
profiles. The retained leak-only reports attribute it to process-lifetime
TLS/JIT/CLI teardown state; the full proof's cleanup, resource-reclamation,
and runtime-thread checks pass after every activation. It remains a review item
and is not represented as zero allocation or as a proven accumulating
activation leak. Issue 39 remains the required long-duration plateau proof.

## Inspecting the raw evidence

From this directory, reassemble, verify, and extract without modifying the
checked-in fragments:

```bash
mkdir /tmp/phase0-hot-path-profile
python3 ../../../../tools/reassemble_phase0_hot_path_profile_archive.py \
  --archive-directory . \
  --output /tmp/phase0-hot-path-profile/raw-evidence.tar.zst
zstd --test /tmp/phase0-hot-path-profile/raw-evidence.tar.zst
tar --use-compress-program=zstd -xf /tmp/phase0-hot-path-profile/raw-evidence.tar.zst \
  -C /tmp/phase0-hot-path-profile
(cd /tmp/phase0-hot-path-profile && sha256sum -c raw-evidence.manifest.sha256)
```

The `profiles/` and `candidates/` paths in `aggregate.json` and `PROFILE.md`
then resolve below `/tmp/phase0-hot-path-profile`. The deterministic Phase 0
workflow runs this full reassembly, zstd, extraction, and manifest check in CI;
the native profiling collection itself remains manual.
