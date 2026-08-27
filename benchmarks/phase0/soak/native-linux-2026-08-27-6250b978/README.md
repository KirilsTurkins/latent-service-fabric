# Native-Linux Phase 0 resource-soak evidence

**Status:** INCONCLUSIVE (strict #38 applicability and full descriptor-lifecycle provenance are incomplete)<br>
**Issue:** #39<br>
**Measured final configuration/source:** `6250b9782ffc4174676d2d72bd023dbfc38c39d7`<br>
**Measured source tree:** `65ba341221ea89e107a3e0e3c4b0aed7e26efd9b`

This is a retained native-Linux resource-plateau observation for the ordinary
Phase 0 configuration: one bounded prepared component cache, on-demand
Wasmtime allocation, and initialized-memory COW enabled. It is observational
evidence, not a production SLO, capacity guarantee, cross-platform claim, or
proof of arbitrary-duration leak freedom.

The archive retains three independent native-Linux processes on an AMD Ryzen 3
3200G host running Fedora Linux without WSL or a container. Each process
performed 1,000 excluded warm-up activations, 100,000 normal measured
fresh-store activations, 100 at-capacity batches, and 100 bounded-queue
batches. Every retained hard invariant passed, including explicit
prepared-component release and runtime shutdown.

Contents:

- [`SOAK.md`](SOAK.md) is the concise plateau report.
- [`aggregate.json`](aggregate.json) is the machine-readable aggregate,
  including calibration applicability, raw-file hashes, host context,
  configuration identity, explicit release/shutdown snapshots, and all robust
  run-level outliers.
- [`raw-evidence.tar.zst`](raw-evidence.tar.zst) losslessly retains the raw
  batch samples, exact command statuses, and before/after host observations
  for all three completed processes. Its 49 KiB compressed payload replaces
  6.46 MiB of repetitive JSON without discarding a sample.
- [`raw-evidence.tar.zst.sha256`](raw-evidence.tar.zst.sha256) verifies the
  compressed archive; [`raw-evidence.manifest.sha256`](raw-evidence.manifest.sha256)
  verifies every extracted file.

To inspect the raw `runs/run-01` through `runs/run-03` paths without modifying
the checked-in archive:

```bash
mkdir /tmp/phase0-resource-soak
zstd --test raw-evidence.tar.zst
tar --use-compress-program=zstd -xf raw-evidence.tar.zst -C /tmp/phase0-resource-soak
(cd /tmp/phase0-resource-soak && sha256sum -c raw-evidence.manifest.sha256)
```

The raw paths and hashes in `aggregate.json` and `SOAK.md` refer to that
extracted tree. The deterministic resource-soak aggregation test performs the
same zstd, extraction, and manifest checks in CI; the native-Linux collection
itself remains manual.

All raw hard invariants, measured topology, explicit release, runtime shutdown,
and retained measured-window/release-to-shutdown FD checks pass. Strict
revalidation deliberately does **not** apply issue-38's bands: that calibration
does not record the selected prepared-cache, Wasmtime allocator, or COW
configuration; the historical host captures omit `systemd-detect-virt --vm`
and allocator provenance; and raw documents predate the pre-runtime and
post-warm-up FD baselines plus raw virtualization kind. The raw RSS/PSS/private/VM series and
run-03 PSS peak remain available for diagnosis, but #39 stays open until a
fresh selected-configuration calibration and three-process archive from the
updated runner record complete matched-host and descriptor-lifecycle evidence.
