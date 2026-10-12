# TypeScript application library inputs

Keep ordinary application dependencies in `package.json` and a native npm v2/v3
`package-lock.json`. The SDK's `sdk-lock.json` and its compiler package lock stay
immutable. The maintained authoring command captures an exact candidate,
verifies an explicit review and builds from the captured module tree. Library
names describe provenance and never determine eligibility.

Use the pinned Node 24.19.0 and Python 3.13.5 prerequisites from the
[toolchain guide](../development/toolchain.md). Create an application with the
[TypeScript authoring guide](typescript-authoring.md), or select its authenticated
frontend template from [application development](../start/application-development.md).
The commands below use an existing application and source-owned tools. An
installed recipe uses its captured Python executable and recipe path from the
same reviewed SDK installation.

## Add and resolve

Edit normal npm declarations and create the native lock without running hooks.
For an independent local module, use:

```bash
set -euo pipefail
umask 077
: "${LSF_CHECKOUT:?Set the checkout containing the maintained authoring tools}"
: "${MY_MODULE_DIR:?Set the absolute directory of your independent module}"
npm install --package-lock-only --ignore-scripts --install-links=true \
  --bin-links=false --no-audit --no-fund "$MY_MODULE_DIR"
mkdir -p target/dependency-review
python3 "$LSF_CHECKOUT/tools/typescript_capsule.py" resolve "$PWD" \
  --candidate "$PWD/target/dependency-review/add.json"
```

Resolution is an explicit acquisition stage. It installs an owned copy of the
native lock with lifecycle scripts and executable links disabled, checks original
archives against their native integrity hashes, and captures the physical
transitive/peer/optional graph and selected module files. Local source inputs,
conditional exports/imports, immutable JSON/text/binary bytes and exact resolver
identities remain attributable. Project `.npmrc` files and linked local roots
are rejected. Captured component builds use the verified offline closure.

The installed profile is `spidermonkey-public-sync-v1`. Repeat
`resolve --condition NAME` for explicit module conditions; the compiler preserves
the default neutral selection. Choosing conditions does not install a missing
Node API, enable pending Promise exports, or grant filesystem/network authority.

For an authenticated frontend project with an `app` subdirectory, edit npm
inputs in `app` and pass either that directory or the outer project to the
authoring command. The outer project owns the declaration, accepted capture
lock and immutable object store. Native lock paths retain the `app/` prefix.
An application descriptor or second capture inside `app` is rejected.

Use a fresh candidate path for every attempt. It must be outside original
library directories and outside project sources, or beneath the project's
`target` directory. Resolution preserves the accepted lock and writes separate
bounded success/failure receipts. A failed or uncertain operation is retained.

## Review exact bytes

Inspect the candidate and its `.receipt.json` sibling. Review selected module
conditions, native graph, original archives/local sources and ignored hooks.
Select the exact bytes:

```bash
candidate="$PWD/target/dependency-review/add.json"
expected=$(python3 - "$candidate" <<'PY'
import hashlib, pathlib, sys
print('sha256:' + hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)
python3 "$LSF_CHECKOUT/tools/typescript_capsule.py" review-lock "$PWD" \
  --candidate "$candidate" --expect "$expected"
python3 "$LSF_CHECKOUT/tools/typescript_capsule.py" dependencies "$PWD"
```

Review verifies the current application/native declarations, graph, selected
module inventory, cached original bytes, conditions and immutable SDK before
atomically accepting the lock. Changed or missing inputs fail before acceptance.
Original feeds and library directories are unnecessary for review or a captured
offline build. The accepted capture grants neither compiler-hook execution nor
runtime capabilities. Bundler plugins and application generators remain denied
until their separate exact isolated execution stage is implemented and qualified.

## Build, test and watch

Use the existing `build` command with the separate reviewed compiler installation
and a fresh output directory. It consumes captured modules in the maintained
namespace and rechecks the closure, selected bundle, source maps and compiler
inputs. Follow the ordinary TypeScript guide's package/sign/admit/node steps.

For a frontend project, connect and install its authenticated tools, trust the
current recipe and dependency identity, build, and prepare the maintained node
fixture through [application development](../start/application-development.md).
Then delegate to the same test/watch operations:

```bash
: "${TYPESCRIPT_PROJECT:?Set the outer frontend project directory}"
: "${TYPESCRIPT_WORKSPACE:?Set the connected workspace}"
: "${LATENT_FRONTEND:?Set the absolute authenticated latent-dev executable}"
: "${LATENT_FRONTEND_SHA256:?Set its exact reviewed sha256 digest}"
python3 "$LSF_CHECKOUT/tools/typescript_capsule.py" test "$TYPESCRIPT_PROJECT" \
  --workspace "$TYPESCRIPT_WORKSPACE" --select greeting \
  --frontend "$LATENT_FRONTEND" --frontend-sha256 "$LATENT_FRONTEND_SHA256"
python3 "$LSF_CHECKOUT/tools/typescript_capsule.py" watch "$TYPESCRIPT_PROJECT" \
  --workspace "$TYPESCRIPT_WORKSPACE" --select greeting \
  --frontend "$LATENT_FRONTEND" --frontend-sha256 "$LATENT_FRONTEND_SHA256"
```

The selected frontend is a regular executable outside the project, held and
rechecked by its exact digest. Its finite wrapper lifetime defaults to 600
seconds; `--frontend-timeout` accepts 1..3600 seconds without changing remote
budgets. Unknown exit 5 and interrupted exit 130 remain intact even if local
receipt writing fails. Inspect status and recover the original operation;
the wrapper never automatically replays it.

A contributor source tree can delegate to its own observed controller. Staged
compiler recipes omit that controller and require explicit frontend selection.
Executable selection does not replace publisher authentication or adjacent
installation integrity checks.

## Update and remove

Use pinned npm's normal update/removal commands with scripts disabled, then
resolve into a new candidate, review it and trust the new frontend identity:

```bash
: "${MODULE_NAME:?Set the npm module to remove}"
npm uninstall --package-lock-only --ignore-scripts --no-audit --no-fund "$MODULE_NAME"
python3 "$LSF_CHECKOUT/tools/typescript_capsule.py" resolve "$PWD" \
  --candidate "$PWD/target/dependency-review/remove.json"
```

A resource change also requires a new capture and review when its npm version
is unchanged. Until review, the old accepted lock remains and fails against
changed declarations/native inputs. Watch observes the maintained descriptor
and captured identity; dependency changes require explicit trust before a new
build and deployment.

## Private inputs

Use a separate configuration file outside the project:

```json
{"registries":[{"scope":"@team","url":"https://registry.example.invalid/npm/","authorizationEnv":"TEAM_NPM_TOKEN"}]}
```

Pass `resolve --registry-config /absolute/private-registries.json` and supply
`TEAM_NPM_TOKEN` only in the explicit resolver environment. Omit `scope` to select
a default registry. Credentials never belong in npm source URLs, project files
or source-controlled configuration. The resolver disables ambient Git/npm
configuration and prompting, rechecks selected configuration and executable
bytes, and passes only declared authorization values as opaque npm token inputs.
Public outcomes contain static failure categories and credential-free digests.
Compiler invocations use their independently curated environment.

## Qualification boundary

Source controls perform real capture, graph/inventory verification, offline
review, descriptor/path/tamper denial and staged imports. Native Node/npm outputs
and remote frontend dispatch are deliberately modelled. The
[source-control receipt](../testing/evidence/typescript-library-authoring-source-2026-10-02.json)
records the exact checked source, test inventory and remaining acceptance work.
These controls do not
establish actual private-feed interoperability, signed module execution or
installed frontend/watch qualification. Those gates retain their actual compiler,
package, invocation and cleanup receipts. Async runtime/default fetch support
requires its separately qualified profile and explicit grants.
