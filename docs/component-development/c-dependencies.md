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
review/install the candidate lock, then use the existing C build/package/admit
workflow:

```powershell
python tools/c_capsule.py resolve ./my-c --candidate ./c-lock-candidate.json
Copy-Item -LiteralPath ./c-lock-candidate.json -Destination ./my-c/latent.dependencies.lock.json
python tools/c_capsule.py build ./my-c --output ./my-c/target/build-1 --repository https://github.com/example/application
```

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
