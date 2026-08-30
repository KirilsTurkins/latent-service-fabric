<!-- LSF-WIKI-MANAGED -->
# Development workflow

Use the repository’s pinned toolchain and validation commands. Generated
artifacts belong below `target/` or Cargo `OUT_DIR`; authoritative WIT,
Protobuf, schemas, and handwritten sources must not be overwritten.

## Everyday validation

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make validate
make repository-tests
```

The commands check Rust formatting/build/lint/tests, contracts, component
builds, SDK surfaces, and repository tooling.

## Phase 0 executable checks

```bash
make phase0-spike-demo
make phase0-gate-smoke
make phase0-gate
```

Smoke mode is a deterministic CI-sized correctness check. Full mode is the
completion gate and returns non-zero when that run's receipt is not authorized.
The retained August 30 native-Linux full receipt is authorized for its
canonical execution identity. Never describe a smoke pass as Phase 1
authorization.

## Evidence changes

Raw calibration, profiling, and soak archives are evidence, not decorative
attachments. Do not alter them by hand. A new execution-relevant source,
fixture, configuration, or toolchain change may require fresh compatible
native-Linux evidence. Run the heavyweight evidence scripts only from a clean
native Linux host or VM, and retain their raw data/manifests/checksums.

## Wiki publication

The Wiki is intentionally published locally, not by a GitHub workflow. The
checked-in [Wiki source guide](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/wiki/README.md)
defines a validate-only command, a local diff plan, and an explicit publish
step. The publisher preserves pages outside LSF’s managed set.

The publisher validates every internal Wiki link, local image, and
development-branch repository reference before it can stage a change. It also
refuses a publication whose prominent Phase 0 status conflicts with the
authoritative completion document.

When adding a page, keep it self-contained, start it with the managed marker
and an H1 heading, add it to the sidebar, and use only checked-in accessible
assets with descriptive alt text. The local checks reject orphaned pages,
unreferenced assets, remote images, and unsafe embedded content.

## Contribution discipline

An implementation change should identify its affected contracts, compatibility
impact, security/resource-accounting impact, relevant decision record, and
reproducible validation. See [CONTRIBUTING.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/CONTRIBUTING.md).
