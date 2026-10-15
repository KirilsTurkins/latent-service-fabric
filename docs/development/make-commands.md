# Make commands

Run GNU Make from the repository root with Bash and the selected
[toolchain](toolchain.md) on `PATH`. Bare `make` prints help; it does not compile,
install dependencies or run tests. The Makefile delegates to maintained owners;
[VALIDATION.md](../../VALIDATION.md) determines which checks a change needs.
On Windows, use the supported Linux environment for native profiles. The Python
entry points remain available directly for portable metadata/documentation work.

## Select a check

| Command | Scope |
| --- | --- |
| `make validate-source` | Repository/foundation, docs/SVG/command links, CI command contracts and action pins; no Rust build or executable test discovery. |
| `make check-rust` | Shared CI formatting, locked workspace and independent production/binding checks, both Clippy policies, deterministic helper/race/example checks. |
| `make check-msrv` | The declared MSRV already installed; no automatic compiler installation. |
| `make repository-tests` | Complete Python suite with its declared Linux/process/tool prerequisites. |
| `make contracts` | All maintained contract lanes, including their explicit fixture preparation and Python suite. |
| `make contracts-bindings` | One named contract lane; also available for `python`, `runtime`, `standalone`, `sdk-provider` and `measurements`. |
| `make sdks` | Six external-client SDK validators; guest authoring and live-node acceptance are separate. |
| `make website-check` | Prepared website source and TypeScript checks. |
| `make website-validate` | Prepared website unit checks, both production mounts and built-site/browser checks. |

`make help` lists the individual targets. `make fmt` explicitly modifies Rust
formatting. `make toolchain-check` checks the full pinned SDK toolchain without
installing it. Shared Cargo recipes use the pinned `cargo` found on `PATH`;
the old Make-only `CARGO` override is no longer a second recipe configuration.
`PYTHON` and `NODE` select the frontend executables. Delegated scripts retain
their own pinned-tool checks and use the active environment.

## One registered suite or case

```bash
make test-list FORMAT=json
make test-plan SUITE=latent-core.lib.latent-core FORMAT=json
make test-prepare SUITE=latent-core.lib.latent-core INVENTORY=target/local-tests/core.jsonl
make test-check SUITE=latent-core.lib.latent-core INVENTORY=target/local-tests/core.jsonl
make test-run SUITE=latent-core.lib.latent-core INVENTORY=target/local-tests/core.jsonl
```

Use the same `CASE=exact::case::name` and `INVENTORY=...` for every step when
selecting one case. `test-explain` and `test-plan` inspect metadata only.
`test-check` validates inputs; an omitted inventory can diagnose that preparation
is needed. `test-prepare` explicitly builds registered inputs. `test-run` never
builds, installs or widens a selection. Unsupported owners remain unsupported.
Paths with spaces must be quoted as one Make assignment, for example
`'INVENTORY=target/local-tests/my core.jsonl'`.

For a recorded failure, use `make test-reproduce REPORT=path/to/report.json
INVENTORY=path/to/owned.jsonl`. This forwards the original replay without a
changed-checkout override. The [local runner](local-tests.md) owns diagnostics,
exit categories and advanced controls. GNU Make itself reports a failed recipe;
use the direct CLI when consuming its structured exit codes.

## Broad clean-checkout Linux validation

```bash
make validate WORKSPACE_ROOT=target/make/my-review-run
```

Choose a fresh owned root under `target/` and a clean tracked checkout. The
preflight refuses an existing test-report directory or dirty tracked source
before compilation. While editing, use focused checks appropriate to the owner;
the [AOT input contract](aot-test-inputs.md) still requires a clean tracked source
identity and Linux x86_64. Make never commits, stashes or resets source for you.

The aggregate runs source checks, Rust checks, all contracts and client SDKs,
then the shared workspace producer, authenticated AOT preparation and complete
test execution. Preparation follows the other fixture writers. Workspace/custom
harness execution, compile-fail doctests and signing compatibility each retain
their original recipes and result checks. A successful Cargo producer or a
discovery receipt is not a test pass.

The same steps can be selected explicitly:

```bash
make workspace-prepare WORKSPACE_ROOT=target/make/my-review-run
make aot-prepare WORKSPACE_ROOT=target/make/my-review-run
make workspace-discover WORKSPACE_ROOT=target/make/my-review-run
make test WORKSPACE_ROOT=target/make/my-review-run
```

`make test` requires prepared inputs and never builds them implicitly. It obtains
validated AOT selectors from the existing owner while leaving Cargo's runtime
environment to Cargo. Fresh discovery and the three execution logs live below
`WORKSPACE_ROOT/test-results/`. Existing logs are never overwritten; retain the
failure and choose a fresh root for another run. Existing AOT inputs are validated
for reuse, never silently replaced after source or byte changes.

Make recipes sharing these roots run serially even under `make -j`. This does
not serialize separate Make processes or change bounded concurrency inside a
maintained runner. Do not start competing fixture writers against the same root.
There is no automatic cleanup target that deletes source, caches or evidence.

This aggregate is not the complete CI matrix or native/application/packaged
acceptance. Website checks, security workflows and explicitly selected scale,
profiling, resource and release campaigns retain their own gates. It replaces
the obsolete `phase1-foundation` entry point; frozen release guides keep their
original commands and source.

## Website preparation and execution

```bash
make website-prepare
make website-browser-install
make website-validate
```

Preparation explicitly acquires the reviewed npm bundle and installs locked
dependencies with lifecycle scripts disabled. Only that bootstrap uses
`BOOTSTRAP_NPM` (default `npm`); validation calls the repository-prepared npm
entry point and verifies it first. Browser installation is also explicit.
Ordinary website checks never install missing dependencies or browsers.

`website-build` and `website-build-root` select the two production mounts;
`website-test-build` checks existing outputs without building them.
[Website development](website.md) owns pinned inputs, clean-source build guards,
browser journeys and the separate human guide review.
