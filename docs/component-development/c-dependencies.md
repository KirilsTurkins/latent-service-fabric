# Captured C libraries

C projects use the [shared dependency manifest and lock](application-dependencies.md)
for original source directories, bounded archives and target-correct static
archives. Add `cSources`, `includeDirectories` and `defines` to each application
artifact's metadata. These are finite captured selections, with transitive
artifact IDs in `dependencies`; arbitrary configure/shell/compiler hooks are not
executed.

```json
{
  "id": "developer/pure-library/1.0.0",
  "role": "application",
  "format": "directory",
  "mount": "dependencies/pure-library",
  "source": {"path": "../pure-library"},
  "dependencies": ["developer/pure-headers/2.0.0"],
  "metadata": {
    "cSources": ["src/pure.c"],
    "includeDirectories": ["include"],
    "defines": {"PURE_FEATURE": "1"},
    "license": "MIT"
  }
}
```

Select the maintained `wasm32-wasi` target in the manifest. Capture explicitly,
review the candidate lock, then use the existing C build/package/admit workflow.
The C authoring commands edit application declarations and preserve the SDK lock.
Save each complete artifact declaration in its own JSON file. Add transitives in
the same operation so the graph stays closed:

```bash
python3 tools/c_capsule.py add ./my-c \
  --artifact ./pure-library.json --artifact ./pure-headers.json
python3 tools/c_capsule.py resolve ./my-c --candidate ./c-lock-candidate-1.json
# Inspect the candidate's source digests, files, transitives and selected profile.
C_REVIEWED_LOCK=$(python3 -c 'import hashlib; print("sha256:" + hashlib.sha256(open("c-lock-candidate-1.json", "rb").read()).hexdigest())')
python3 tools/c_capsule.py review-lock ./my-c \
  --candidate ./c-lock-candidate-1.json --expect "$C_REVIEWED_LOCK"
python3 tools/c_capsule.py dependencies ./my-c
python3 tools/c_capsule.py build ./my-c --output ./my-c/target/build-1 \
  --repository https://github.com/example/application
```

`pure-headers.json` must declare the example's `developer/pure-headers/2.0.0`
artifact, including its captured source, mount and licensing metadata. The
resolver rejects an omitted transitive rather than fetching an undeclared input.
For example, when those public headers live in `../pure-headers`:

```json
{
  "id": "developer/pure-headers/2.0.0",
  "role": "resource",
  "format": "directory",
  "mount": "dependencies/pure-headers",
  "source": {"path": "../pure-headers"},
  "dependencies": [],
  "metadata": {"includeDirectories": ["."], "license": "MIT"}
}
```

The digest passed to `review-lock` must be the digest you actually reviewed;
computing a digest does not establish source trust. Acceptance verifies all
captured original/transformed bytes and native locks offline before atomically
installing the candidate. An existing candidate or its receipt requires a new
attempt path. Candidate outputs belong outside the project or under `target/`.

Each add, update, remove, resolution, review and dependency-status command retains
an immutable bounded receipt under `target/c-dependency-authoring/`. Resolution
also writes a sibling `.receipt.json` or `.failed.json`. Receipts contain reviewed
input digests, the selected profile and fixed outcome codes; original private
locations, repository configuration and credentials stay outside those receipts.
Component and archive builds retain their own compiler, ABI, patch, source,
component and successful/failed observations. A reviewed library lock does not
approve an executable generator or grant a guest capability.

To update a declaration, keep its ID and provide its complete replacement JSON:

```bash
C_MANIFEST_REVIEW=$(python3 -c 'import hashlib; print("sha256:" + hashlib.sha256(open("my-c/latent.dependencies.json", "rb").read()).hexdigest())')
python3 tools/c_capsule.py update ./my-c \
  --id developer/pure-library/1.0.0 --artifact ./pure-library-updated.json \
  --expect-manifest "$C_MANIFEST_REVIEW"
python3 tools/c_capsule.py resolve ./my-c --candidate ./c-lock-candidate-2.json
```

Review and accept the new candidate explicitly, then build into a fresh output.
Use add/remove to change an artifact ID. Remove dependent artifacts together:

```bash
python3 tools/c_capsule.py remove ./my-c \
  --id developer/pure-library/1.0.0 --id developer/pure-headers/2.0.0
```

Update and removal preserve the old lock as evidence. Builds and frontend loads
reject it as stale until the changed manifest has a newly captured reviewed lock.
Neither operation edits `sdk-lock.json`, vendored SDK files or compiler locks.
`--expect-manifest` is also available on add and remove to reject a stale editor
review before changing the declaration. Conflicting source edits and failed
atomic replacement preserve the prior declaration and lock.

For private HTTPS artifacts, declare a repository alias, exact archive/file
digest and relative artifact path. Pass `--repositories` only to resolve. The
private configuration maps the alias to an HTTPS URL and an `authorizationEnv`
variable whose value supplies the authorization header. Keep that configuration
and environment outside project snapshots and compiler inputs. Embedded URL
credentials, query tokens, redirects, absent credentials and changed response
bytes fail with fixed diagnostics. Review, build, test and watch consume the
verified cache without reopening the private feed. Local source directories use
the same explicit capture and review flow.

For an authenticated project created with the existing
[packaged developer workflow](../start/application-development.md), run the
dependency commands against the outer directory containing `latent.project.json`.
The maintained C app and immutable SDK lock remain under `app/`; dependency
declarations, reviewed lock and transport cache stay at the outer root. The
component and archive recipes capture those exact reviewed inputs into their
observed source inventory. A second dependency lock under `app/` is rejected as
ambiguous. Direct projects from `c_capsule.py new` keep their existing flat layout.

After a reviewed dependency update, explicitly refresh the workspace's normal
recipe trust, build and deploy through the maintained frontend. The following
uses an already provisioned disposable test workspace from that workflow:

```bash
latent-dev dev trust --workspace test-c --project ./my-c
latent-dev dev build --workspace test-c --project ./my-c
latent-dev dev deploy --workspace test-c
python3 tools/c_capsule.py test ./my-c --workspace test-c --select greeting-0
python3 tools/c_capsule.py watch ./my-c --workspace test-c --select greeting-0
```

Pass the same `--state-root` to each command when using a custom controller state
directory. Test and watch delegate to the existing latent-dev CLI, preserving its
foreground ownership, cancellation, exact deployment target, uncertainty and
recovery behavior. Watch rebuilds and tests only the latest captured source; a
changed dependency lock requires fresh trust. Existing confirmed deployments
remain available after a failed edit/build. An uncertain mutation is inspected
through the normal workspace recovery commands before any retry. These commands
require an authenticated frontend project descriptor; a flat direct capsule uses
the signing and node workflow in [C authoring](c-authoring.md).

The [October 2 lifecycle controls](../testing/evidence/c-dependency-authoring-lifecycle-2026-10-02.json)
record 19 new authoring cases and 47 existing C/static/dependency regressions on
pinned Linux Python 3.13.5, with no skips. They exercise real declaration edits,
capture, lock verification, private HTTPS success/denial, trust invalidation and
the nested recipe's input consumer. Their component/archive tests explicitly
stop at the compiler boundary; final-source compilation and signed-node/watch
qualification remain necessary before those paths are considered complete.

The build materializes only the verified offline closure, compiles actual
captured sources through the maintained Zig C/component recipe and binds its
source/include/configuration, compiler, runtime and library identities to
`c-libraries.json`. Includes stay beneath each captured artifact. Definitions
apply to the selected compilation as a whole; independently configured objects
require a separately captured compatible archive. Unknown package names use the
same source/build policy and require no LSF catalogue entry.

Captured builds require the managed Linux compiler host with Bubblewrap. The
compiler process receives an empty home, no network and only the owned workspace,
selected compiler distribution and observed shared runtime libraries. Absolute
`#include`/`#embed` paths cannot reach ambient host files. The maintained
preprocessor records every read and rejects inputs outside those captured
roots. `compiler-inputs.json` binds the full Zig headers, libc/sysroot, tool
executables, shared host libraries and actual preprocessor input digests; these
are rechecked before accepting the build. A host without the isolation profile
fails with a concrete diagnostic. This is a trusted single-user build host
boundary; it does not qualify hardened multitenant compiler isolation.

Static archives use the regular GNU/BSD archive format. Thin archives, host-native
members, traversal, duplicate member names, unbounded contents and nonrelocatable
Wasm modules fail. Actual linking/target-feature sections are inspected. Strong
global definitions are checked across every member and every selected archive,
including members that ordinary lazy extraction would leave unused. Local, weak,
common and undefined symbols retain their distinct linking semantics. Each core
member is also validated with the pinned Wasm validator with threads and memory64
disabled before final linking. A
prebuilt archive additionally needs an `archiveProfile` binding the exact
compiler/runtime digest, target, closed synchronous checkpoint profile and each
inspected member identity. This profile is a reviewed source/build-policy
assertion; it does not provide publisher authority or qualify threading ABI.
Stale or absent profiles require a source rebuild. The linker and final exact
WIT/engine-profile inspection still reject unresolved/ambiguous symbols and
unsupported authority. Thread/shared-memory/object profiles remain gated by
their actual runtime implementation and qualification.

To produce an archive from already resolved library sources, use the finite
captured source recipe on the same managed compiler host:

```bash
python3 tools/c_capsule.py archive ./my-c \
  --output ./my-c/target/library-1 \
  --repository https://github.com/example/application
```

The recipe compiles the declared `cSources` with their captured includes and
definitions, observes every preprocessor input, and invokes the pinned compiler
and archiver in the same namespace. It writes `library.a`, `archive-profile.json`,
`compiler-inputs.json` and `STATIC-ARCHIVE-COMPLETE.json`; failures retain
`STATIC-ARCHIVE-FAILED.json` and command logs. It grants no publisher authority.
After reviewing those outputs, declare the archive as an application artifact
with `format: "file"`, a mount ending in `.a`, and the exact generated profile in
`metadata.archiveProfile`. Capture public headers and immutable resource inputs
as separate transitive artifacts, then explicitly resolve/install the new lock
and run the ordinary component build. Source, archive and final component
receipts remain separate. A changed compiler, sysroot, runtime, checkpoint
profile or archive member invalidates the profile and requires another source
build.

The maintained compiler retains its 64-source, 256-KiB-per-source bounds. The
shared capture store independently bounds original artifacts and total closure.
Generators require the separate approved executable-input stage, and generated
headers/source must be captured before building. Library resources remain
immutable attributed bytes; packaging them does not expose writable POSIX files.

Source and member-format tests do not establish signed/admitted library execution.
Pure third-party/transitive/resource component runs and error/fuel/cancellation
cleanup acceptance remain separate observed qualification work.

The C authoring CI runs the actual namespace denial and deadline/descendant
cleanup tests, then signs, admits and runs the greeting component using
[jsmn 1.1.0](https://github.com/zserge/jsmn/tree/v1.1.0), an outside-project
developer library and an immutable included-byte resource. The original local
sources are removed after capture. The application calls both jsmn and the
developer library directly; the developer library also calls jsmn and reads the
captured immutable resource. The same qualification then compiles the library
sources to an observed static archive, explicitly captures its public headers
and resources under a different unknown library identifier, rebuilds the component
offline, and runs a separate signed node
workflow. `node/workflow.json` and `node-static/workflow.json` retain their own
invocation, fault, resource and shutdown evidence. A passing retained
qualification receipt is required before treating either component case as
observed; it does not qualify POSIX resource lookup or thread scheduling.

The maintained workflow also runs `tools/c_dependency_controls.py` against the
captured static-library project. Its 21 compiler and generator controls use the
pinned tools and real namespace isolation. They reject unused duplicate or
invalid members, host-native and memory64 objects, member-count overflow, stale
profiles, changed or missing inputs, ambient headers and credentials, and stale
generator approvals. Deadline and output-limit failure receipts report `reaped`
only after the ordinary process owner has physically retired; cleanup and
ownership failures retain `unconfirmed`. A later independent generator stage
must still succeed after the deadline case.

The [October 1 observation](../development/c-capsule-qualification.md#captured-library-observation-on-october-1-2026)
records actual source and static-archive component runs and these controls at
their exact inputs. Full maintained SDK, printed-guide and final-source CI
qualification remain separate requirements.
