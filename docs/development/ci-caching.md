# CI dependency caching

The [CI workflow](../../.github/workflows/ci.yml) reuses downloaded Cargo
dependencies and compiled host dependencies in its `rust`, `oci-registry`,
`catalog`, `msrv` and `contracts` jobs. The documentation profile does not start
these jobs. Within the full profile, cache hits never select or skip validation
steps: the same checks and tests run after a hit or a miss. A cold or
evicted cache remains a supported build path. Caching does not establish a
measured speedup or change the retained benchmark results.

## Cached files and fresh evidence

The workflow pins
[Swatinem/rust-cache v2.9.2](https://github.com/Swatinem/rust-cache/tree/6323deb102c322ba6fcbdcafc7e3dddab59af2b6)
to its full commit. It uses GitHub's cache service and the action's maintained
dependency pruning instead of a repository-specific artifact cleanup script.
The Cargo registry and Git dependency cache are eligible for reuse. Installed
Cargo binaries and workspace crates are excluded.

Whole-target caching is disabled. The only additional archive paths are:

```text
target/debug/.fingerprint
target/debug/build
target/debug/deps
```

Before saving, the action removes workspace build outputs, unused dependencies
and incremental artifacts from its workspace target inventory. It keeps the
compiled dependency fingerprints and build-script outputs needed for reuse.
This cleanup runs in the post step, after validation and evidence uploads.
See the pinned [cleanup implementation](https://github.com/Swatinem/rust-cache/blob/6323deb102c322ba6fcbdcafc7e3dddab59af2b6/src/cleanup.ts)
and [save implementation](https://github.com/Swatinem/rust-cache/blob/6323deb102c322ba6fcbdcafc7e3dddab59af2b6/src/save.ts).

The cache paths exclude `target/capsules`, generated contract inventories,
provenance exports, native/raw runtime caches, catalogs, test fixtures,
benchmark receipts and runner temporary directories. Wasm and release-profile
compilation outputs are also outside this initial cache scope. Existing fixture
exporters, reproducibility checks and artifact transfers still run for the
current source. In particular, the registry job receives the contracts job's
observed build artifact named with the current `github.sha`.

The action disables Cargo incremental compilation when restoring. Existing
scripts that explicitly unset `CARGO_INCREMENTAL` retain their current commands
and build recipes. The cache does not preserve incremental work directories.

## Identity and write access

The action's automatic key separates job ID, operating system, architecture,
installed Rust compiler identities, compiler/Cargo environment, manifests,
lockfiles and Cargo configuration. The additional key identifies Ubuntu 24.04
and hashes this CI workflow, the root `Cargo.toml` and `.cargo/config.toml`.
This includes the virtual workspace's inherited dependency/profile settings.
MSRV artifacts therefore cannot substitute for the primary toolchain's cache.
No shared job key, commit SHA or PR number is added. A version-only root
manifest change can cause a cold cache; that is an accepted initial tradeoff.
See the pinned [key construction](https://github.com/Swatinem/rust-cache/blob/6323deb102c322ba6fcbdcafc7e3dddab59af2b6/src/config.ts).

This workflow saves Rust caches only after successful development pushes or
manual runs on `development` or `release`. PR runs only restore, reducing
per-PR storage growth. Failed jobs do not save these caches. Never add signing
keys, registry credentials, node data or secret files to the archive paths.

GitHub scopes cache access by branch and permits PRs to restore their base
branch's caches. A development seed serves PRs targeting development; it does
not make that cache universally available to release-targeting PRs. A manual
CI run on release can seed that scope once this workflow exists there. Leave
`run_catalog_scale` false for ordinary seeding: all normal CI validation runs,
without opting into the 100,000-release probe. Cache eviction and service
quotas can still cause misses. See GitHub's
[cache scope and security rules](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching#restrictions-for-accessing-a-cache).

## Verification and maintenance

Compare the cache action's hit/miss, archive size and elapsed time in a cold
trusted run and a later PR run. Confirm that the mandatory test steps still
execute and that provenance and gate receipts name the current source and
binaries. Inspect aggregate repository cache usage before expanding the path
list; the initial configuration adds no per-PR Rust cache writes.

Change `prefix-key` to retire this cache family after a layout or pruning
change. Keep the action pinned to a reviewed full commit. Do not use a cache
hit as evidence that a test passed or a current fixture was regenerated.
Python/npm setup caches retain their existing configuration; SDK, Docker-image
and historical measurement cache expansion is outside this change.
