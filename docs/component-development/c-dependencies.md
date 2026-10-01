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
Wasm modules fail. Actual linking/target-feature sections are inspected. A
prebuilt archive additionally needs an `archiveProfile` binding the exact
compiler/runtime digest, target, closed synchronous checkpoint profile and each
inspected member identity. This profile is a reviewed source/build-policy
assertion; it does not provide publisher authority or qualify threading ABI.
Stale or absent profiles require a source rebuild. The linker and final exact
WIT/engine-profile inspection still reject unresolved/ambiguous symbols and
unsupported authority. Thread/shared-memory/object profiles remain gated by
their actual runtime implementation and qualification.

The maintained compiler retains its 64-source, 256-KiB-per-source bounds. The
shared capture store independently bounds original artifacts and total closure.
Generators require the separate approved executable-input stage, and generated
headers/source must be captured before building. Library resources remain
immutable attributed bytes; packaging them does not expose writable POSIX files.

Source and member-format tests do not establish signed/admitted library execution.
Pure third-party/transitive/resource component runs and error/fuel/cancellation
cleanup acceptance remain separate observed qualification work.

The C authoring CI runs the actual namespace denial and deadline/descendant
cleanup tests, then signs/admit/runs the greeting component using
[jsmn 1.1.0](https://github.com/zserge/jsmn/tree/v1.1.0), an outside-project
developer library and an immutable included-byte resource. The original local
sources are removed after capture. A passing retained qualification receipt is
required before treating that component case as observed; it does not qualify
POSIX resource lookup or thread scheduling.
