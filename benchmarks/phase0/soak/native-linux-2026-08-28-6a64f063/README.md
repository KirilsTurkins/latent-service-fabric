# Native-Linux Phase 0 resource-soak evidence

**Status:** PASS (matched #38 calibration and complete lifecycle evidence)<br>
**Issue:** #39<br>
**Published final configuration/source:** `6a64f0630cee9afa080d33f376aabadac724fa72`<br>
**Published source tree:** `d27ff38ebbd891c5be949f54a0047522ed893d20`

This is a retained native-Linux resource-plateau observation for the selected
ordinary Phase 0 configuration: a one-entry bounded prepared-component cache,
on-demand Wasmtime allocation, and initialized-memory COW enabled. It is
observational evidence, not a production SLO, capacity guarantee,
cross-platform claim, or proof of arbitrary-duration leak freedom.

The archive retains three independent bare-metal Fedora Linux processes on an
AMD Ryzen 3 3200G host. Each completed 1,000 excluded warm-up activations,
100,000 normal measured fresh-store activations, 100 at-capacity batches, and
100 bounded-queue batches. All hard invariants, topology checks, explicit
prepared-component release, and runtime-shutdown checks passed.

Contents:

- [`SOAK.md`](SOAK.md) is the concise plateau report, including the exact
  commands, environment, configuration, sampling schedule, analysis method,
  limits, terminal observations, and unsupported conclusions.
- [`aggregate.json`](aggregate.json) is the machine-readable aggregate. It
  records the matched calibration identity, raw-file hashes, host context,
  configuration identity, plateau analysis, release/shutdown snapshots, and
  all retained run-level outliers.
- [`raw-evidence.tar.zst`](raw-evidence.tar.zst) losslessly retains the raw
  batch samples, command statuses, and before/after host observations for all
  three processes. Its compressed payload avoids checking in repetitive raw
  JSON twice.
- [`raw-evidence.tar.zst.sha256`](raw-evidence.tar.zst.sha256) verifies the
  compressed archive; [`raw-evidence.manifest.sha256`](raw-evidence.manifest.sha256)
  verifies every extracted raw file.

To inspect the raw `runs/run-01` through `runs/run-03` paths without modifying
the checked-in archive:

```bash
mkdir /tmp/phase0-resource-soak
zstd --test raw-evidence.tar.zst
tar --use-compress-program=zstd -xf raw-evidence.tar.zst -C /tmp/phase0-resource-soak
(cd /tmp/phase0-resource-soak && sha256sum -c raw-evidence.manifest.sha256)
```

The strict aggregation result is `pass`: host/toolchain/fixture/configuration
identity matches the fresh seven-process calibration; raw process environment
reconciles with before/after host observations; all descriptor lifecycle
baselines pass; and no calibrated material RSS, PSS, private-memory, or VM
growth was detected. The retained raw series remains available for diagnosis;
the result does not widen an allowance or make any production claim.
