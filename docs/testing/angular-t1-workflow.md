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

The actual maintained build and real-clock signed exporter pass locally. CLI,
transport, policy and artifact tests exercise the bounded management surfaces.
Protected configuration, enforced evidence admission, isolated native preparation
and exact selected deployment have also passed in the separate-process runner.
The end-to-end T1 compiler/cache/render runner is still under qualification;
the published runtime remains T0-only. No interrupted Docker run is counted as
a pass. The #336 asset implementation is integrated; its new actual workflow
checks are pending the complete T1 run. The browser scenario work remains
separate. Full #226 completion is not claimed here.

After integrating the provider startup fixes and optional backend profile,
11 manifest and 115 wire tests pass, as does strict app-scope Linux Clippy.
The initial fresh build rejects the stale installed npm tree against the merged
lockfile; it does not publish a package. Qualification must provision that exact
lock and build new bytes. An exporter launched before the output existed also
failed and supplies no admission evidence.
