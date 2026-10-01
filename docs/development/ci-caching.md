# CI dependency caching

The [CI workflow](../../.github/workflows/ci.yml) reuses downloaded Cargo
dependencies and compiled host dependencies in its `rust`, `oci-registry`,
`catalog`, `msrv` and `contracts` jobs. The documentation profile does not start
these jobs. Within the full profile, cache hits never select or skip validation
steps: the same checks and tests run after a hit or a miss. A cold or
evicted cache remains a supported build path. Caching does not establish a
measured speedup or change the retained benchmark results.

## Reusing builds within the Rust job

The Rust job builds workspace binaries and test harnesses with one package,
target and feature selection: `--workspace --all-targets --all-features`.
Its ordinary workspace test suite runs once. A fresh Cargo JSON inventory from
the same selection identifies the exact library test executables used for the
two fixture exporters and three native currentness tests. Those later steps
execute the already-built harnesses through
[the artifact runner](../../tools/ci_rust_artifacts.py), which checks source and
package ownership and verifies the expected ignored test names before execution.
Fixtures and receipts are still generated during the current run.

This avoids switching back to narrower linked build graphs after workspace
testing. Independently selected CLI/node and compiler packages still receive
`cargo check`, so workspace feature unification cannot hide missing dependency
features in those builds. The legacy Ed25519 compatibility probe remains
separate. Host versus WebAssembly targets, ordinary versus MSRV toolchains, and
check/Clippy metadata versus linked executable artifacts remain distinct work.
The custom Wasmtime integration harnesses still run through the original full
workspace suite; filtered exporter calls do not rerun those custom harnesses.

The test inventory lives in the runner's temporary directory. It is never
restored from a cache, selected through filename globbing, or reused as proof
that a test ran. This consolidation is separate from dependency caching;
compare actual build steps before attributing a timing change to either.

## Cached files and fresh evidence

The workflow pins
[Swatinem/rust-cache v2.9.2](https://github.com/Swatinem/rust-cache/tree/6323deb102c322ba6fcbdcafc7e3dddab59af2b6)
to its full commit. It uses GitHub's cache service and the action's maintained
dependency pruning instead of a repository-specific artifact cleanup script.
The Cargo registry and Git dependency cache are eligible for reuse. Installed
Cargo binaries and workspace crates are excluded.

The action owns target pruning (`cache-targets: true`). Directly archiving the
fingerprint/build/deps directories bypassed that boundary and could retain
large workspace test executables. No additional target directories are archived.

Before saving, the action removes workspace build outputs, unused dependencies
and incremental artifacts from its workspace target inventory. It keeps the
compiled dependency fingerprints and build-script outputs needed for reuse.
This cleanup runs in the post step, after validation and evidence uploads.
See the pinned [cleanup implementation](https://github.com/Swatinem/rust-cache/blob/6323deb102c322ba6fcbdcafc7e3dddab59af2b6/src/cleanup.ts)
and [save implementation](https://github.com/Swatinem/rust-cache/blob/6323deb102c322ba6fcbdcafc7e3dddab59af2b6/src/save.ts).

The cache paths exclude `target/capsules`, generated contract inventories,
provenance exports, native/raw runtime caches, catalogs, test fixtures,
benchmark receipts and runner temporary directories. Compatible third-party
WebAssembly and release dependencies can be pruned and reused too. Existing fixture
exporters, reproducibility checks and artifact transfers still run for the
current source. In particular, the registry job receives the contracts job's
observed build artifact named with the current `github.sha`.

CI disables incremental compilation and debug symbols for correctness builds.
Workspace code remains unoptimized; debug assertions and overflow checks are
explicitly enabled for both dev and test. Only the third-party Cranelift,
register allocator and Wasm validator are optimized, so actual Angular components
use a fast host compiler while retaining the full runtime checks. The isolated
Angular release compiler has its own dependency cache and still runs Cargo.
Frozen optimization collectors remove these CI environment settings before
building their own inputs. The cache does not preserve incremental directories.

## Identity and write access

The action's automatic key separates operating system, architecture,
installed Rust compiler identities, compiler/Cargo environment, manifests,
lockfiles and Cargo configuration. The additional key identifies Ubuntu 24.04;
the workflow layout itself does not invalidate compiler dependencies.
This includes the virtual workspace's inherited dependency/profile settings.
MSRV artifacts therefore cannot substitute for the primary toolchain's cache.
Compatible jobs share the `host-correctness` key. MSRV uses
`msrv-correctness`, and the isolated release compiler uses
`angular-release-compiler`. No commit SHA or PR number is added. A version-only root
manifest change can cause a cold cache; that is an accepted initial tradeoff.
See the pinned [key construction](https://github.com/Swatinem/rust-cache/blob/6323deb102c322ba6fcbdcafc7e3dddab59af2b6/src/config.ts).

The complete Rust producer, MSRV and isolated compiler save their respective
caches only after successful pushes to `development`. Smaller consumers and
guest qualification jobs only restore, so an incomplete dependency graph cannot
win an immutable shared cache key. PR runs only restore, reducing per-PR storage
growth. Failed jobs do not save these caches. Never add signing
keys, registry credentials, node data or secret files to the archive paths.

Compiler download archives use the same base-branch scope and remain untrusted
inputs that are verified against pinned digests on every use. Seed them with a
manual Developer tools run on `development`; PRs only restore them. The existing
push branch filters stay in place, so ordinary merges do not add six developer
distributions and Windows/portable packaging jobs to the required pipeline.

GitHub scopes cache access by branch and permits PRs to restore their base
branch's caches. A development seed serves PRs targeting development; it does
not make that cache universally available to release-targeting PRs. Leave
`run_catalog_scale` false for ordinary validation: all normal CI validation runs,
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
Developer-tool compiler archives are also written only by development pushes;
restored archives still pass their existing checksum and installation checks.
The TypeScript workflow installs the same pinned wasm-tools binary through the
reviewed setup action instead of recompiling the tool from source on every PR.
Python/npm setup caches retain their existing configuration.
