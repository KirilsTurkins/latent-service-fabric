# Author your first capsule

## Outcome

Understand and build a small real Rust guest, distinguish its declared result
from platform failure, and identify the exact inputs that become a package.
Use the maintained echo implementation rather than inventing another SDK example.
The next step is an actual [first-node invocation](../start/first-node.md), then
[trusted delivery](deliver-and-recover-a-capsule.md).

## Supported version, prerequisites and full source

Use a private development checkout and its [pinned build tools](../development/toolchain.md).
The component builder needs the maintained Rust and wasm-tools versions; do not
substitute a generated SDK from another checkout. The complete guest is
[component.rs](../../tools/toolchain-smoke/examples/echo_capsule/component.rs),
its domain logic is [logic.rs](../../tools/toolchain-smoke/examples/echo_capsule/logic.rs),
and the authoritative export is [echo.wit](../../examples/echo-contract/wit/echo.wit).
The [build instructions](../../examples/echo-contract/README.md) own the source,
fixture outputs and reproducibility boundary.

A **guest SDK** implements the imported/exported WIT contracts inside an activation.
A **network client** invokes a node from a separate process. Rust syntax alone
does not identify which one a snippet is. This example is a guest; it does not
start an HTTP server, read ambient credentials or install the LSF runtime.

## Read the maintained implementation

The following block is extracted from the registered source region. Its source
link and verification label come from the [existing registration](../../examples/guides/rust-echo/example.json),
not a manually copied program or a new passing badge:

<!-- lsf-example: guest/rust-echo echo -->

The guest implements `examples:echo/api@0.1.0`. Nonempty messages up to 65,536
UTF-8 bytes are returned unchanged; empty input and excessive length are declared
`empty-message` and `message-too-large` variants. The limit counts bytes, not
Unicode characters. The WIT-generated types remain authoritative.
The guest reads activation context and makes one best-effort bounded log call;
a logging rejection does not replace its declared echo result.

Do not assume a global variable or process-local heap survives the next activation.
Only declared capabilities are available. Node, deployment and capsule limits
intersect; a client-requested ceiling grants no authority and cannot raise an
operator limit. The [generated deployment template](../../examples/echo-contract/deployment.json)
declares context/log grants and finite resources. Do not expand those budgets
merely to make a failure disappear. Later persistent state/workflow semantics are
not part of this guest.

## Build, inspect and deliberately fail

From the repository root:

```bash
set -euo pipefail
umask 077
export CARGO_TARGET_DIR="$PWD/target"
make echo-capsule
"$CARGO_TARGET_DIR/debug/latent" --output json validate capsule \
  "$CARGO_TARGET_DIR/capsules/echo/capsule.json"
"$CARGO_TARGET_DIR/debug/latent" --output json validate deployment \
  "$CARGO_TARGET_DIR/capsules/echo/deployment.json"
```

The two validation commands require the CLI built in the
[first-node prerequisites](../start/first-node.md#build-the-exact-inputs).
Expected: a Component Model artifact plus computed-digest manifest, typed contracts,
deployment and input. The builder compiles a self-contained core and componentizes
it; it is not an arbitrary package-script runner or a node activation.
`make echo-capsule-reproducibility` separately checks two clean builds under the
fixture's documented same-host/source/toolchain boundary. Do not infer
cross-platform reproducibility from one successful build.

For a small source edit, change only the fixed log message in your own guest
worktree, then rebuild and rerun the first-node sequence. Preserve the export,
result semantics and budgets. Commit your edit on your own feature branch before
repeating the clean-checkout commands. Any displayed snippet identity must follow the
changed bytes; an earlier evidence record cannot qualify a changed source.
For an unchanged-checkout acceptance run, use the original maintained fixture.

The first-node walkthrough sends `[""]` as a separate known activation and requires
`declared-error` (CLI exit 3), while `["hello"]` requires success. Malformed
capsule JSON must fail local validation before network dispatch. A trap or exhausted
budget is instead a platform outcome, and a lost transport response may leave the
outcome unknown. See [WIT values](../protocol/wit-values.md) and
[CLI outcome semantics](../reference/operator-cli.md#output-and-exits); never treat
all nonzero exits as an application error or an automatic retry instruction.

## From component to trusted publication

A component digest identifies executable bytes. A package digest additionally
binds package metadata/layers; a tenant publication and routed revision are
separate identities. The raw locally trusted publication in the first-node guide
is not the production signing/admission workflow.

The [package contract](../component-development/packaging.md) owns the explicit
source descriptor, selected build-input root, typed contracts, pinned WIT and
SBOM inputs. The packager consumes existing files; it does not compile, sign
or manufacture builder provenance. Use a new output directory and inspect it
before transfer. Inspect does not evaluate trust, and local verify does not grant
node execution authority.

Continue with [Deliver, invoke and recover a capsule](deliver-and-recover-a-capsule.md)
for the executable maintained package/sign/provenance/SBOM/verify/OCI sequence,
publisher versus independent builder policy, tenant publication, managed
preconditions, denial, promotion and rollback. Its signed observations are
explicitly synthetic fixtures; actual observed-build provenance has its own
owner. Never install the fixture's credentials or policy on a real server,
replace independently provisioned trust with package-supplied roots, or mistake
an OCI container format for an LSF runtime installation requirement.

## Cleanup and validation

The builder's outputs stay under your selected target directory and do not run a
service. The first-node runner removes its own temporary state; a manually started
node must be stopped by its owner before removing that run's files. Preserve
historical benchmark/signature bytes and never publish private signing inputs.

The snippet registration deliberately has no matching runtime evidence record:
source extraction is not compilation, and compilation is not an activation.
The [guide validation record](../development/core-guide-validation.md) links the
existing backend/CLI tests and the new first-node runner. A successful run must
retain its actual source/toolchain/artifact identities; rendering alone cannot
complete this learning path's execution review.
