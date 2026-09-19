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
python3 tools/run_angular_t1_workflow.py \
  --cli /target/debug/latent --node /target/debug/latentd \
  --compiler /target/tools/latent-aot-compiler \
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

Explicit deployment selectors resolve either the existing capsule record or the
exact tenant-scoped web record. Web normalization returns only the associated
renderer digest, not execution permission or a synthetic capsule entry. Historical
identity remains resolvable for durable operation replay; deployment compilation
and invocation still require the current sealed web-publication authority.

The intended gate covers rejected protected configurations, enforced
publisher/builder/SBOM admission, cold isolated compilation, authenticated native
cache reuse, exact selected deployment/render, cancellation and failure recovery,
cross-principal/tenant isolation, evidence-generation invalidation, independent
publication revocation and exact deployment-CAS rollback. T2/T3 remain rejected.
Native HTTP rendering is not a real-browser hydration claim.

## Current evidence boundary

The actual maintained build and real-clock signed exporter pass locally. CLI,
transport, policy and artifact tests exercise the bounded management surfaces.
The end-to-end T1 compiler/cache/render runner is still under qualification;
the published runtime remains T0-only. No interrupted Docker run is counted as
a pass. Immutable asset delivery depends on #336 integration and the browser
scenario work remains separate. Full #226 completion is not claimed here.
