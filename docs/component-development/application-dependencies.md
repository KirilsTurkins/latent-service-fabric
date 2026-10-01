# Captured application dependencies

Application dependency capture is separate from the immutable SDK and compiler
locks. The shared capture store accepts a selected, closed native ecosystem
graph; package identity supplies provenance and never grants application or
runtime authority. Unknown public, private and local packages use the same
contract.

Keep `latent.dependencies.json`, `latent.dependencies.lock.json`, native
lockfiles and `dependency-inputs/objects/` with your project. The objects directory
is a verified transport cache. The application lock and compiler/runtime
selection require source/build-policy review even when every object is cached.
There is no invocation-time resolution.

The version 1 manifest has six required fields:

```json
{
  "formatVersion": 1,
  "language": "c",
  "selection": {
    "target": "wasm32-unknown-unknown",
    "compiler": "zig-0.15.2",
    "runtimeProfile": "closed-c-v1",
    "features": [],
    "conditions": []
  },
  "nativeLocks": ["libraries.lock.json"],
  "artifacts": [{
    "id": "developer/pure-library/1.0.0",
    "role": "application",
    "format": "directory",
    "mount": "dependencies/pure-library",
    "source": {"path": "../pure-library"},
    "dependencies": [],
    "metadata": {"license": "MIT", "scope": "runtime"}
  }],
  "transformations": []
}
```

Native metadata belongs in `metadata` and the captured native lock: versions,
repositories by alias, scopes, exclusions, features, conditions, framework/RID,
module branches, transitive edges, compiler flags and resolver inputs must survive
the language resolver. The common capture layer does not resolve those semantics
or establish compatibility by itself. Roles are `application`, `sdk`, `compiler`,
`runtime`, `build-tool`, `generated` and `resource`.

Capture explicitly, inspect the complete candidate and then install it under the
reviewed lock name:

```powershell
python tools/application_dependencies.py ./my-project --candidate ./candidate.json
Copy-Item -LiteralPath ./candidate.json -Destination ./my-project/latent.dependencies.lock.json
```

The command refuses to replace an existing candidate. It captures local file or
directory inputs and immutable ZIP/tar inputs. A remote source has
`repository`, relative `path` and exact `digest` fields. Separately supplied
`--repositories` configuration maps that alias to an HTTPS base `url` and optional
`authorizationEnv`. Supply the credential through that environment variable;
never put a password, token, URL userinfo or credential query in a lock or command
argument. Redirects are denied so authorization cannot move to another origin.
Only resolution reads this configuration. Local/private source paths are omitted
from public dependency receipts.

Normal recipes materialize the reviewed closure from content-addressed objects
without resolution or provisioning. Missing, changed and uncaptured inputs fail
with a concrete dependency diagnostic. Builds recheck manifests, native locks,
original objects and materialized bytes after compilation. Their receipt records
selected inputs, transformations and the resulting input identity. Signing,
admission and final exact WIT/profile checks still apply.

Automatic transformations identify the selected artifact, original tree digest,
resulting tree digest, exact per-file preimages and replacements, tool version
and selection configuration. Original package bytes and checksums remain in the
store. Wrong or missing preimages and changed transformed bytes fail. This layer
supplies exact captured replacement operations; it never invokes an unobserved
patch command or permits an automatic patch to grant a new import.

Archive paths, links, case collisions and file/directory collisions are rejected.
The store permits 64 MiB per object, 8,192 entries and 256 MiB expanded bytes per
archive, and 32,768 files/512 MiB for the entire selected closure. A packaged
developer host can impose a smaller source-transfer limit. Writes use atomic
creation, verify existing objects and retain no abandoned temporary object after
a failed or competing write.

Package hooks, processors, plugins, proc macros and generators are executable
build inputs. They cannot execute through ordinary dependency ingestion. The
separate `tools.application_dependency_tools.execute` API requires an approval
binding the executable bytes, version, arguments, exact input tree and restricted
environment. It uses Bubblewrap with separate Linux namespaces, read-only
inputs/tool/system directories, an owned output directory, a fresh home/tmp,
network denial and the existing bounded process/reaping helper. Windows and Linux
hosts without working unprivileged namespaces fail closed. This is namespace
containment on a trusted single-user build host; it does not establish a hardened
hostile-tenant VM. Generated outputs must be captured and reviewed before use.

`application-dependencies.json` is a selected-input inventory with recorded
license metadata and provenance. Its SBOM boundary covers declared application
inputs. It does not claim a complete runtime SBOM, hermeticity, reproducibility,
library compatibility or runtime authority. Native/generated/tool inputs and
compiler/sysroot/runtime locks require their own attributable inventories.
