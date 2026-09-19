# Actual Angular T1 management qualification

This #226 workflow is separate from #236 browser hydration and #44's optional
broker call during rendering. The current fixture uses only the sealed context
import, has zero outbound/child-call ceilings, and grants no provider authority.
It must not be presented as broker-during-render acceptance.

## Shared fixture interface

Build the maintained application with `tools/build_angular_package.py`, using
`examples/angular-application` as `--input-root`, `examples/renderer-profile` as
`--toolchain-root`, and the built `latent` binary as `--cli`. The exact locked
toolchain and build inputs are described in
[Angular build packaging](../component-development/angular-build.md). The output
directory must be under the supplied `--target-root`; it contains `package/`,
`inputs/` and the actual `observation.json`. Never substitute a synthetic receipt
or rewrite the produced component to match an earlier digest.

The Linux exporter consumes that directory and creates a fresh private root:

```sh
LSF_ANGULAR_BUILD_DIR=/target/angular-build/actual \
LSF_ANGULAR_T1_FIXTURE_ROOT=/target/angular-fixture \
cargo test -p latentd --test phase3_angular_fixture --locked -- \
  --ignored --exact export_actual_angular_t1_fixtures
```

It exports `policy.json`, `observation.json`, `fixture.json`, and three fixtures:
`angular`, `alternate`, and `missing-sbom`. Each fixture has `package/`,
`evidence/index.json`, `renewed-evidence/index.json`, `no-publisher-evidence/index.json`
and `no-builder-evidence/index.json`. The two admitted publications share actual
renderer bytes but have independently signed package identities. The negative
SBOM variant removes embedded inventory without changing the observed web build
outputs. Fresh test-only signing keys bind the actual Angular observation; they
are not build-child credentials. The exporter enforces the current deliberately
limited `not-checked` reproducibility and `declared-inputs-incomplete` statements.

The fixture's `/`, `/exception`, `/spin`, `/large-hydration` and `/offline`
behavior is retained while browser scenarios extend the application separately.
The selected public contract is `latent:web/application@0.1.0`, function `handle`,
using the canonical WIT JSON positional request and buffered response.

## Separate client/node runner

```sh
cargo build -p latent-wasmtime --bin latent-aot-compiler --release --locked \
  --target-dir /target/angular-compiler
python3 tools/run_angular_t1_workflow.py \
  --cli /target/debug/latent --node /target/debug/latentd \
  --compiler /target/angular-compiler/release/latent-aot-compiler \
  --fixture-root /target/angular-fixture
```

The compiler is the actual approved isolated compiler, with its exact digest
bound in protected configuration. The runner reuses the existing process,
configuration, audit and ownership helpers; it does not replace the provider
workflow or give the CLI a node-state path. It owns fresh temporary node/client
directories, at most 256 CLI processes over 1200 seconds, finite audit/status
queries, bounded response captures and a compact redacted receipt. A cold
`web prepare` may wait at most 300000 milliseconds. Guest invocations remain
bounded to five seconds; preparation does not allocate an application Store.
The optimized compiler avoids the observed cold debug-compiler timeout without
increasing that fixed preparation allowance. A changed adapter/profile digest
requires new produced bytes and native qualification, not an old cache receipt.

Explicit deployment selectors resolve either the existing capsule record or the
exact tenant-scoped web record. Web normalization returns only the associated
renderer digest, not execution permission or a synthetic capsule entry. Historical
identity remains resolvable for durable operation replay; deployment compilation
and invocation still require the current sealed web-publication authority.

The verified metadata retains a catalog-only web-projection marker, including
denied historical rows on restart. Only that path validates the exact public
web world and mandatory context import against the tenant's deployment. The
optional `scoped-http-get-v1` projection uses only its exact public web-http world
and mandatory context plus HTTP v0.2 imports; deployment ceilings still apply.
This validator support is not evidence of backend invocation during rendering.
Ordinary capsule input retains its
tenant-world namespace requirement. Copying metadata or verifying component bytes
does not create this marker, and the marker itself supplies no execution grant.

The intended gate covers rejected protected configurations, enforced
publisher/builder/SBOM admission, cold isolated compilation, authenticated native
cache reuse, exact selected deployment/render, cancellation and failure recovery,
cross-principal/tenant isolation, evidence-generation invalidation, independent
publication revocation and exact deployment-CAS rollback. T2/T3 remain rejected.
Native HTTP rendering is not a real-browser hydration claim.

The asset checks request each exact publication's declared browser bytes before
renderer preparation, verify content digests and bounded GET/HEAD/conditional
responses, and deny foreign tenants and private renderer/source/SBOM paths.
Revoked publications stay denied for GET and conditional HEAD after restart.
These checks do not derive a self-publication locator from rendered HTML and do
not substitute for #236's real-browser application qualification.

## Current evidence boundary

The complete protected T1 workflow passed on Linux x86-64 on 2026-09-19 after
integrating startup dependency `3a1f6189`. The qualified code is
`c767d0a624172e72c1f44bb3d7064bb2c382231e`; the
[unaltered run-12 receipt](../evidence/phase3-226-angular-t1.json) has SHA-256
`451ae67ca62d9359203712b51a1acce1580460dad267a5ed16445d5bee5682ef`.
Only this observed selected-publication path enables Angular under the explicit
protected `external-capsule-v1` profile. It does not convert web identity into
capsule authority or enable unsupported T2/T3 profiles.

The retained execution used container `lsf-phase3-226-build`, its exclusive
`lsf-phase3-226-target` volume, and these actual binaries:

| Binary | Path in the owned container | SHA-256 |
| --- | --- | --- |
| CLI | `/target/debug/latent` | `8ad264f81ba482d2273e9324c3349c38a2942e25eb54dd4c3dca1defda099fb3` |
| Node | `/target/debug/latentd` | `5c1bd294f9931d072a1867c205e1fadb0facf37287fb860cdb004464818654a6` |
| Optimized compiler | `/target/phase3-226-release/release/latent-aot-compiler` | `4d736bd8b7a48f8ed7ff5175efd9b85fd56d5ef707520915b7aa8119f18c7b51` |

The actual build is `/target/phase3-angular-t1-build/actual-selected-01`; a fresh
real-clock signed export is `/target/phase3-angular-t1-fixture-12`. Neither is
the separate #236 reference application. The immutable build observation is
`sha256:3538f5810c2c53d012cded8e734cf0291f8d765553b4a37cf4ffbdc620e8a8e2`.
The admitted renderer contains 23956338 bytes. Its package and component digests
are retained in the native-cache observations, not inferred from a T0 run.

Run 12 observes all of the following within the existing finite bounds:

- Sixteen rejected protected-configuration commands and three enforced
  publisher/builder/SBOM admission failures; exact durable publication replay.
- Cold isolated preparation in 23703 milliseconds, then actual selected cold
  and warm Angular renders. This timing is not release-performance evidence.
- Render exceptions, hydration limits, explicit cancellation and client
  disconnect, followed by successful renders and reclaimed cell/quota owners.
- Evidence renewal invalidating old preparation and deployment generations,
  independent revocation of a second package sharing the same component, and
  exact deployment-CAS rollback without substituting a staged web canary.
- Exact immutable client asset URLs and bytes, private-path and foreign-tenant
  denial, principal isolation, and trigger deletion with its retained generation.
- A restart cache hit at audit sequence `35`, strictly newer than the
  pre-restart high-water mark `19`, with unchanged native blobs and receipts.
  Revocation remains effective; both node processes report clean, reaped shutdown.

The runner used 103 of its maximum 256 CLI processes. CI now builds its own
optimized compiler, exports the current job's actual Angular build through the
exact Cargo harness inventory, runs this workflow, and retains its compact
receipt. It never shares a Cargo target with another worktree or substitutes
cached test evidence. Exact-head CI and central review remain separate gates.

Additional local validation: 563 CLI/node/Wasmtime library tests pass with 29
explicitly ignored tests; the fresh signed exporter passes separately; 47
workflow/inventory/schema/native-boundary tests pass. Strict all-target app
Clippy and workspace formatting checks pass. No 100000-release workload ran.

This evidence is not real-browser hydration, backend invocation during render,
a true staged web canary, production hostile-multitenancy certification, or
full #226/Phase 3 completion. Those parent-owned integration boundaries remain
separate. Build reproducibility remains `not-checked`, and dependency inventory
remains `declared-inputs-incomplete`.

## Earlier attempts and corrections

Run 09 completed actual T1 rendering, but did not require a strictly newer
restart cache-hit sequence. Runs 10 and 11 reached the selected HTTP/lifecycle
checks and then failed the restart deadline; their empty receipts are not
passes. Run 12 uses the integrated audit/provider pre-enqueue startup fixes
and the stronger post-restart observation check without retries of admitted
work or increased compiler/guest ceilings.

After integrating the provider startup fixes and optional backend profile,
11 manifest and 115 wire tests pass, as does strict app-scope Linux Clippy.
The initial fresh build rejects the stale installed npm tree against the merged
lockfile; it does not publish a package. Reprovisioning that exact lock in a
dedicated Linux tool directory produces a new actual package successfully.
An exporter launched before the output existed also failed and supplies no
admission evidence. The later selected-publication context change required
another build and native qualification against its changed profile digest;
run 12 uses that rebuilt `actual-selected-01` output, not the earlier artifact.

The repository-contracts job on `ffea4260` rejects the optional backend ABI
because its source tripwire still expects one unconditional generator. The
updated tripwire accepts only the two exact, mutually exclusive reviewed
generators and retains the single generated wasm-only unsafe allowance.
The real source plus negative selector/world/import/handwritten-code cases pass
18 focused boundary and workflow tests; the build-foundation validator passes.

The later Rust job at `da00b9f6` reaches the maintained public-renderer fixture
and fails because its copied WIT tree omits HTTP v0.2, now referenced by the
optional adapter world. After adding that dependency, actual componentization
also identifies the fixture's missing private `prepare` export. The fixture now
returns an explicit null backend plan and copies the complete reviewed WIT
dependency tree; it still has no HTTP import or provider authority. The corrected
actual Angular fixture componentizes to 23752438 bytes with no imports. These
fixture-only changes do not alter the production adapter or qualified package.
