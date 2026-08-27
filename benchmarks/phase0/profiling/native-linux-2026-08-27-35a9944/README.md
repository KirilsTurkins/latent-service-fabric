# Native-Linux Phase 0 hot-path profile archive

**Status:** pass. This is the accepted issue-40 CPU/allocation evidence for
the fixed Phase 0 configuration, captured on native Fedora Linux on 2026-08-27.
It is observational optimization evidence, not a production SLO,
cross-platform conclusion, or a replacement for issue 39's 3x100k soak.

The measured source is the durable branch commit
[`35a9944`](https://github.com/KirilsTurkins/latent-service-fabric/commit/35a9944f134098d4ea3e1f3859b9e9bf80d9a3ad)
with Git tree `316357dce997c33b25d230a84adbcf11dffc1097`. Every profile and
candidate command records that source identity, its local execution commit,
the fixture/probe paths, and the effective runtime configuration.

## Checked-in entry points

- `PROFILE.md` is the concise human-readable outcome and Phase 1 handoff.
- `aggregate.json` is the compact machine-readable aggregate. Its paths are
  relative to the extracted raw archive, and it retains checksums for every
  referenced item.
- `host-before.json` captures the native-Linux host, kernel, toolchain,
  allocator, power/load, and virtualization context.
- `raw-evidence.parts.json` describes the lossless raw archive and its eight
  ordered sub-1 MB fragments. The reassembler verifies each fragment and the
  completed `raw-evidence.tar.zst` checksum before extraction;
  `raw-evidence.manifest.sha256` then verifies its contents.

The raw archive contains every `perf.data`, symbolized perf report, native
Heaptrack trace and normal/leak-only report, full baseline result/report,
exact command, fixture bootstrap, and all three independent processes for
each worker/cell, allocator, and COW candidate. The archive is split only for
repository transport; its manifest and reassembler retain the same byte-for-
byte zstd payload without discarding or sampling data.

## Inspecting the raw evidence

From this directory, reassemble, verify, and extract without modifying the
checked-in fragments:

```bash
mkdir /tmp/phase0-hot-path-profile
python3 ../../../../tools/reassemble_phase0_hot_path_profile_archive.py \
  --archive-directory . \
  --output /tmp/phase0-hot-path-profile/raw-evidence.tar.zst
zstd -d -c /tmp/phase0-hot-path-profile/raw-evidence.tar.zst \
  | tar -C /tmp/phase0-hot-path-profile -xf -
(cd /tmp/phase0-hot-path-profile && sha256sum -c raw-evidence.manifest.sha256)
```

The `profiles/` and `candidates/` paths in `aggregate.json` and `PROFILE.md`
then resolve below `/tmp/phase0-hot-path-profile`. Re-run the aggregate from a
repository checkout if independent validation is needed.

Heaptrack reports the same 2.82 KiB process-exit total in each of the six
profiles. The retained leak-only reports attribute it to process-lifetime
TLS/JIT/CLI teardown state; the raw Phase 0 cleanup, resource, and runtime
thread checks all pass after every activation. It is preserved as a review
item, not rewritten as zero allocation or treated as an accumulating
activation leak.
