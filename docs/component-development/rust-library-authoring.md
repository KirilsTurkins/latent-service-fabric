# Rust application library inputs

Keep application libraries in the application's Cargo manifest and lockfile.
The SDK's `sdk-lock.json`, `rust-toolchain.toml` and `vendor/lsf` stay immutable.
The maintained `rust_capsule.py` command captures a separate dependency closure,
accepts an exact reviewed candidate and verifies it before compilation. Library
names are provenance; they are not an eligibility catalogue.

Use the pinned Rust 1.97.1 toolchain and Python 3.13.5 from the
[toolchain guide](../development/toolchain.md). Create a capsule with the
[Rust authoring guide](rust-authoring.md), or use the authenticated Rust template
from [application development](../start/application-development.md). The examples
below use an existing application and the source-owned authoring command. An
installed recipe uses its captured Python executable and recipe path instead.
That recipe must belong to the same reviewed SDK installation as the application.

## Add and resolve

Use normal Cargo operations to edit `Cargo.toml` and `Cargo.lock`. For example,
from a direct capsule's directory:

```bash
set -euo pipefail
umask 077
: "${LSF_CHECKOUT:?Set the checkout containing the maintained authoring tools}"
: "${MY_LIBRARY_DIR:?Set the directory of your independent Rust library}"
rustup run 1.97.1 cargo add --path "$MY_LIBRARY_DIR"
mkdir -p target/dependency-review
python3 "$LSF_CHECKOUT/tools/rust_capsule.py" resolve "$PWD" \
  --candidate "$PWD/target/dependency-review/add.json"
```

Resolution is an explicit acquisition step. It runs pinned Cargo metadata and
vendoring commands, captures the native lockfiles and closes the dependency
graph. It records target, features, native revisions/checksums, exact original
and relocated manifests, resources and executable-input identities. It does
not run application build scripts or procedural macros.

The supported selection is `wasm32-unknown-unknown` with the maintained
`wasm32-unknown-unknown-panic-abort-v1` profile. Repeat `--features NAME`, or select
`--all-features` or `--no-default-features`, on `resolve` when needed. Changing
these choices requires a fresh capture, review and frontend trust decision.

For a frontend project with an `app` subdirectory, edit Cargo inputs in `app` and
pass either the outer project or its selected `app` to the authoring command.
Application dependency declarations, the accepted lock and the content-addressed
store belong to the outer project. Native lock paths retain the `app/` prefix.
A second descriptor or dependency capture inside `app` is rejected.

Every attempt needs a fresh candidate path. `resolve` preserves the accepted
lock. It writes a separate bounded success or failure receipt; errors do not
overwrite an earlier receipt or automatically repeat a remote operation.

## Review exact bytes

Inspect the candidate and its `.receipt.json` sibling. Check the native graph,
selected features, original and transformed inputs, licences and executable
input list. Then select the exact candidate bytes:

```bash
candidate="$PWD/target/dependency-review/add.json"
expected=$(python3 - "$candidate" <<'PY'
import hashlib, pathlib, sys
print('sha256:' + hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)
python3 "$LSF_CHECKOUT/tools/rust_capsule.py" review-lock "$PWD" \
  --candidate "$candidate" --expect "$expected"
python3 "$LSF_CHECKOUT/tools/rust_capsule.py" dependencies "$PWD"
```

Review verifies the closed lock, cached original and transformed bytes, native
locks, current root Cargo manifest and build-script identity. A changed
candidate, source manifest, native lock, SDK or missing/tampered cached object
fails before acceptance. Original feeds or library directories are not needed
for review, verification or a captured offline build.

An accepted dependency lock does not grant compiler execution or runtime
capabilities. If it selects build scripts or procedural macros, the builder
requires its separate exact compiler/profile approval and an isolated stage.
Unsupported execution remains a failure with retained diagnostics.

## Build, test and watch

Use the existing build command with a fresh output directory and `--offline`.
The builder verifies captured inputs, uses the private selected Cargo closure
and records the original and relocated source identities. The package retains
the existing contract, compatibility and signature checks. Follow the
[Rust signing and node steps](rust-authoring.md) for direct capsule admission.

For a frontend project, connect and install the authenticated tools with the
[maintained workflow](../start/application-development.md). Trust the current
recipe and dependency identity, build it and prepare the existing node fixture
before testing. The Rust authoring command delegates to those same operations:

```bash
: "${RUST_PROJECT:?Set the outer frontend project directory}"
: "${RUST_WORKSPACE:?Set the connected workspace}"
: "${LATENT_FRONTEND:?Set the absolute authenticated latent-dev executable}"
: "${LATENT_FRONTEND_SHA256:?Set its exact reviewed sha256 digest}"
python3 "$LSF_CHECKOUT/tools/rust_capsule.py" test "$RUST_PROJECT" \
  --workspace "$RUST_WORKSPACE" --select greeting \
  --frontend "$LATENT_FRONTEND" --frontend-sha256 "$LATENT_FRONTEND_SHA256"
python3 "$LSF_CHECKOUT/tools/rust_capsule.py" watch "$RUST_PROJECT" \
  --workspace "$RUST_WORKSPACE" --select greeting \
  --frontend "$LATENT_FRONTEND" --frontend-sha256 "$LATENT_FRONTEND_SHA256"
```

The selected frontend must be a regular executable outside the project. Its
exact bytes are held and rechecked through dispatch. The wrapper's finite
default lifetime is 600 seconds; `--frontend-timeout` accepts 1..3600 seconds.
Remote command budgets stay unchanged. An unknown outcome remains exit 5, and
an interrupt remains exit 130, including when writing a local receipt fails.
Inspect workspace status and recover the original operation through the
maintained workflow; the wrapper does not replay it.

A contributor source tree can delegate to its own observed frontend controller
without those options. A staged compiler recipe omits that controller and
requires explicit frontend selection. Executable hashes bind selected bytes;
publisher authentication and adjacent installation integrity remain the
responsibility of the authenticated frontend installation.

## Update and remove

Use normal pinned Cargo commands to update or remove application dependencies,
then resolve into a new candidate, review its exact digest and trust the new
frontend input identity. For example:

```bash
: "${LIB_PACKAGE:?Set the Cargo package to remove}"
rustup run 1.97.1 cargo remove "$LIB_PACKAGE"
python3 "$LSF_CHECKOUT/tools/rust_capsule.py" resolve "$PWD" \
  --candidate "$PWD/target/dependency-review/remove.json"
```

Updating a library resource also requires a new capture and review even if its
Cargo version did not change. Until review, the old accepted lock is preserved
and fails verification against changed declarations/native inputs. Watch uses
the maintained descriptor and captured input identities; a changed dependency
identity requires explicit trust before it can build and deploy.

## Private inputs

Declare private registry aliases in a separate JSON file outside the project:

```json
{"registries":{"team":{"index":"sparse+https://registry.example.invalid/index/"}}}
```

Pass it through `resolve --registry-config /absolute/private-registries.json`.
Select that registry with the ordinary Cargo manifest. Supply its credential
only in the explicit resolver environment as `CARGO_REGISTRIES_TEAM_TOKEN`.
The resolver copies credentials only for selected aliases, disables ambient
Git configuration and prompting, and uses an owned Cargo home. Do not put
credentials in Cargo source URLs, application manifests or copied source files.
The lock and public authoring outcomes contain no resolver token values.
Compiler processes use the existing curated environment and isolated captured
closure, independently of resolver credentials.

## Qualification boundary

Source controls exercise real capture, path transformations, offline review,
tamper rejection, nested descriptors and staged recipe imports. Their Cargo
metadata outputs and frontend dispatch boundaries are deliberately modelled.
The [75-case source replay](../testing/evidence/rust-library-authoring-source-2026-10-02.json)
records the exact committed inputs, pinned environment and retained outcomes.
Those controls do not establish native Cargo execution, signed library
invocation, private-feed interoperability, scheduler support or end-to-end
watch qualification. Those acceptance checks retain their own actual compiler,
package, node, failure and cleanup receipts. HTTP and asynchronous runtime
support also require their separately qualified profiles and explicit grants.
