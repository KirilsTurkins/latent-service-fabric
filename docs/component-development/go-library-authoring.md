# Go application module inputs

Keep ordinary module declarations in `go.mod` and their exact native checksums in
`go.sum`. The SDK's `sdk-lock.json`, `vendor/lsf` and component compiler locks stay
immutable. The maintained authoring command captures the native selected graph,
verifies an explicit review and builds from the offline closure. Module names
describe provenance and never determine application eligibility.

Use the prerequisites in the [toolchain guide](../development/toolchain.md) and
the pinned `go1.27.1` module resolver. Capsule execution uses the separately
reviewed `go-component-async-v1` component compiler, runtime patches and tools.
Native Go execution cannot replace that component qualification.

Create an application with the [Go authoring guide](go-authoring.md), or select
the authenticated Go frontend template in
[application development](../start/application-development.md). The commands
below use an existing project and source-owned tools. An installed recipe uses
the captured Python executable and recipe path from its reviewed installation.

## Add and resolve

Edit the application's normal Go declarations and source imports. For an
independent local module, use the pinned native manager:

```bash
set -euo pipefail
umask 077
: "${LSF_CHECKOUT:?Set the maintained authoring checkout}"
: "${GO_MODULE_RESOLVER:?Set the absolute pinned module resolver executable}"
: "${MODULE_PATH:?Set the independent module coordinate}"
: "${MY_MODULE_DIR:?Set its absolute source directory}"
GOTOOLCHAIN=local GOWORK=off GOENV=off "$GO_MODULE_RESOLVER" mod edit \
  "-require=$MODULE_PATH@v0.0.0" "-replace=$MODULE_PATH=$MY_MODULE_DIR"
```

Produce the exact native `go.sum` through an explicit configured native lock
operation. Select the intended target, build tags, proxy/checksum policy and
private authorization when preparing it; never put credentials in module URLs
or source files. Resolution requires those native declarations to be locked and
does not silently repair them, update SDK modules or run `go generate`.

Capture a fresh candidate:

```bash
mkdir -p target/dependency-review
python3 "$LSF_CHECKOUT/tools/go_capsule.py" resolve "$PWD" \
  --go "$GO_MODULE_RESOLVER" --tag my_application_tag \
  --candidate "$PWD/target/dependency-review/add.json"
```

Resolution is an explicit acquisition stage. It uses an owned module cache,
forces `GOTOOLCHAIN=local`, `GOWORK=off`, `GOENV=off`, `CGO_ENABLED=0` and read-only
native declarations, and disables ambient Git configuration and prompts. It
records MVS edges, replace/exclude directives, original `h1` archive and manifest
checksums, local source bytes, selected versions and exact resolver identity.
Local replacements are relocated in separately captured derived `go.mod` bytes;
their original source declaration and SDK remain unchanged.

For an authenticated frontend project with an `app` subdirectory, edit native
inputs in `app` and pass either directory to the authoring command. The outer
project owns the capture declaration, accepted lock and immutable object store.
Native input names retain the `app/` prefix. An inner application descriptor or
second capture is rejected.

Use a fresh candidate path for each attempt. It must be outside original local
module roots and project sources, or beneath the project's `target` directory.
Resolution preserves the accepted lock and writes separate bounded successful
or failed receipts. Failed operations retain their original outcome.

## Review exact bytes

Inspect the candidate, native graph and `.receipt.json` sibling. Review target,
tags, proxy/checksum policy, selected module graph and original/derived bytes.
Accept the exact reviewed digest:

```bash
candidate="$PWD/target/dependency-review/add.json"
expected=$(python3 - "$candidate" <<'PY'
import hashlib, pathlib, sys
print('sha256:' + hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)
python3 "$LSF_CHECKOUT/tools/go_capsule.py" review-lock "$PWD" \
  --candidate "$candidate" --expect "$expected"
python3 "$LSF_CHECKOUT/tools/go_capsule.py" dependencies "$PWD"
```

Review verifies native declarations, module/selected-root identities, captured
originals and transformations, target/tags and immutable SDK bytes before atomic
lock acceptance. Changed or missing inputs fail before acceptance. Upstream
feeds and original local directories are unnecessary for review or a captured
offline build. Capturing a generator directive never executes it; Go tool
declarations require their separate approved isolated execution stage.

## Build, test and watch

Use the existing `build` command with a fresh output directory. Its maintained
recipe validates the offline download/source closure and captured local
relocations, generates its reviewed vendor tree and inspects actual final WIT.
Follow the ordinary Go guide's package/sign/admit/node steps. Tags select source
inputs without installing an unqualified runtime operation or granting authority.

For a frontend project, connect, install authenticated tools, trust the current
recipe/dependency identity, build and prepare the maintained node fixture through
[application development](../start/application-development.md). Then delegate
to the same test/watch operations:

```bash
: "${GO_PROJECT:?Set the outer frontend project}"
: "${GO_WORKSPACE:?Set the connected workspace}"
: "${LATENT_FRONTEND:?Set the absolute authenticated latent-dev executable}"
: "${LATENT_FRONTEND_SHA256:?Set its exact reviewed sha256 digest}"
python3 "$LSF_CHECKOUT/tools/go_capsule.py" test "$GO_PROJECT" \
  --workspace "$GO_WORKSPACE" --select greeting \
  --frontend "$LATENT_FRONTEND" --frontend-sha256 "$LATENT_FRONTEND_SHA256"
python3 "$LSF_CHECKOUT/tools/go_capsule.py" watch "$GO_PROJECT" \
  --workspace "$GO_WORKSPACE" --select greeting \
  --frontend "$LATENT_FRONTEND" --frontend-sha256 "$LATENT_FRONTEND_SHA256"
```

The selected frontend is a regular executable outside the project, held and
rechecked by its exact digest. Its finite wrapper lifetime defaults to 600
seconds; `--frontend-timeout` accepts 1..3600 without changing remote budgets.
Unknown exit 5 and interrupted exit 130 remain intact even if local receipt
writing fails. Inspect status and recover the original operation; no automatic
mutation replay occurs.

A contributor source tree can delegate to its own observed controller. Staged
compiler recipes omit that controller and require explicit frontend selection.
An executable digest does not replace publisher authentication or installation
integrity checks.

## Update, remove and private inputs

Use the native manager to update/remove normal requirements or replacements and
produce a fresh native lock. Resolve a new candidate, review it and explicitly
trust the resulting frontend identity. A local or embedded resource change also
requires new capture/review when the module version stays unchanged. The prior
accepted lock remains intact until review and fails against changed native
inputs. Watch observes the reviewed captured identity before new builds.

Keep private policy in a separate file outside the project:

```json
{"proxy":"https://proxy.example.invalid","sumdb":"off","private":["team.example.invalid/*"],"authorizationEnv":"TEAM_GO_TOKEN","username":"token"}
```

Pass `resolve --proxy-config /absolute/private-proxy.json` and provide the named
authorization value only to the explicit resolver environment. The resolver
writes a private owned netrc and treats its value as an opaque credential; it
cannot replace Go control flags or ambient credential paths. Checksum policy is
explicit, native `go.sum` identities remain required, selected configuration and
resolver bytes are rechecked, and public outcomes contain credential-free
digests and static failure categories.

## Qualification boundary

Source controls perform real capture, graph/native/inventory verification,
offline review/materialization, path/descriptor/tamper denial and staged imports.
Go process outputs and remote frontend dispatch are deliberately modelled.
The [source-control receipt](../testing/evidence/go-library-authoring-source-2026-10-02.json)
records the exact checked source, test inventory and remaining acceptance work.
These controls do not establish actual private-proxy interoperability, signed
module execution, embedded-resource execution or installed frontend/watch
qualification. Those gates require their actual compiler, package, invocation
and cleanup receipts. Runtime/default networking and approved generators retain
their separate qualification requirements.
