# Captured application dependencies

## Add a library to your capsule

Start in your application project and choose the guide for its language. The
commands in these guides use the authoring tools from the `development` source
checkout. Keep that checkout separate from your application directory.

| Language | What you add to the project | Walkthrough |
| --- | --- | --- |
| Rust | A Cargo dependency from a registry, Git revision or local crate path | [Add a Cargo dependency, lock it and build offline](rust-dependencies.md) |
| C | An artifact declaration naming the sources or target archive, include directories and transitive inputs | [Add a C library and its headers](c-dependencies.md#capturing-c-libraries) |
| TypeScript | A dependency in `package.json` with its npm lock | [Add, lock and bundle an npm dependency](typescript-dependencies.md) |
| Go | A module requirement in `go.mod`, with a local replacement when appropriate | [Add a Go module, capture its graph and build](go-dependencies.md) |
| Java | A Maven coordinate and scope, or a local JAR | [Add a Maven dependency or capture a local JAR](java-dependencies.md) |
| C# / .NET | A `PackageReference` in `Capsule.csproj` | [Add a NuGet package and build with NativeAOT](dotnet-dependencies.md) |

1. **Declare the dependency.** Use the editor for your input type. For example,
   Java uses `add` for Maven coordinates and `add-local` for a local JAR. Include the transitive
   inputs your library uses. Public, private and local dependencies use the
   same capture mechanism.
2. **Review the lock.** Run the guide's native lock step where applicable, then
   `resolve` to a fresh candidate. Inspect the selected graph, source digests,
   features and build tools. Pass the digest of the candidate you reviewed to
   `review-lock`. Run `dependencies` to inspect the accepted selection.
3. **Build and exercise a real library call.** Call the dependency from your
   capsule's handler and use the result in its response. Build from the accepted
   capture and run the handler through the normal package and deployment path.
   For library data files, declare the [packaged resources](packaged-resources.md)
   the handler reads. For network calls, select the language's supported runtime
   profile and grant the deployed capsule the required destination and operation.
   Inspect the [compatibility report](library-compatibility.md) for an unsupported
   operation. For example, on the closed Rust profile, `Builder::spawn` returns
   an error the application can handle. The signed example records the executed
   fallback as `unsupported-reached` and verifies a fresh invocation after an
   uncaught call.

Each walkthrough's language has run a developer-owned dependency in a signed
greeting capsule. All six preserved the declared error on blank input and
succeeded on a fresh call. The installed Linux C toolkit also built two
independent private library declarations offline. Each signed package fetched
a price card, read its own immutable resource and returned the same result.
[Installed C commands and results](../testing/c-installed-library.md)

The private C worker example calls libfetch on a transitive library's pthread,
joins it and returns the parsed card to the caller. Two distinct sets of
package names and a fresh project built from the guide each passed signed
execution with the same component bytes.
[Build the private C worker example](../../examples/guides/c-private-card/README.md)

The installed Java toolkit built two local-JAR dependency graphs offline. Each signed
application read the transitive JAR resource and passed 13 HTTP cases. The
installed Rust toolkit ran Waki and Golem with two outside crates in two tenants.
Each crate compared a fetched price card with its embedded copy.
[Java package evidence](../testing/java-installed-library-inputs.md) and
[Rust package evidence](../testing/rust-private-dependency-ingestion.md)

The Go example
ran Sling and Requests with their default clients and a private module that
read a `//go:embed` resource from a goroutine. Both Go module coordinates
passed all 30 HTTP cases after capture. The installed Linux Go toolkit then
rebuilt both projects offline. Each signed package passed the same 30 cases
and its peer recorded 24 requests, two mutations and no rejected requests.

Two independently captured TypeScript packages used Ky and Wretch through
global Fetch. Both clients returned their ordinary HTTP errors for a 404
when the capsule selected `latent:http/phase-timing@0.4.0`, which exposes
the peer's status text. With `latent:http/streaming@0.3.0`, Wretch handled
the 404 and Ky reported that status text was unavailable. The phase run also
exercised cancellation and a fresh call from a second tenant on the same node.
An installed Linux TypeScript toolkit then built the private resource and
timer project offline. Its signed package passed 27 guest executions and four
pre-I/O refusals across the primary, missing-provider and two-tenant cases.

The installed .NET toolkit first refused the Refit generator. After approval of
that exact compiler request, it built the same captured application offline.
The signed Flurl and Refit package passed 20 guest executions and two pre-entry
refusals. The peer saw 15 connections and one mutation. All 20 guest executions
passed the physical retirement check.

The
[six-language execution record](../testing/evidence/sdk-private-library-invocations-2026-11-23.json)
includes the dependency locks, tool and component identities, grants, results
and node measurements.

All six languages also ran on the same Linux node build from development
commit `269fe85b`. Across the private application and published client cases,
105 signed cases and eight additional pre-entry refusals passed. Each group
shut down cleanly. The guest toolkits and components came from the revisions
recorded for each language.
[Common runtime and per-language results](../testing/evidence/sdk-private-libraries-common-native-2026-11-24.json)

### Review a compiler execution request

The packaged Linux CLI exercised this workflow with Refit 16.4.0 in two
clean workspaces. Both used the same eight captured NuGet packages and
produced the same generator output manifest. The approved build in each
workspace stayed within the 4 GiB attempt limit, and explicitly selecting the
approval again reused the same attempt. Omitting it returned a new refusal.
The component and package digests differed between the independent builds.
The second component ran 20 signed calls through Flurl, Refit and the private
library on the matching node. Two additional invocations were refused before
guest entry, and the peer closed every connection.
[Packaged commands, build measurements and signed results](../testing/evidence/dotnet-installed-refit-approval-2026-11-24.json)

A captured Cargo build tool, Java annotation processor or NuGet source generator
can require explicit approval. In a project created from a matching installed
toolkit, first run the ordinary trusted build. If it stops at
`executable-input-approval`, use the same workspace to inspect the private
request after the compiler exits.

```powershell
$review = latent-dev --state-root $StateRoot dev executable-approval-request --workspace $Workspace | ConvertFrom-Json
$review.result.request.specification | ConvertTo-Json -Depth 32
```

Review the selected executable inputs, original and transformed bytes, compiler,
source and isolation policy. If you authorize this exact request, pass its digest
to a fresh build.

```powershell
$approved = $review.result.request.identity
latent-dev --state-root $StateRoot dev build --workspace $Workspace --project $Project --executable-approval $approved
```

The same digest can be passed explicitly to `dev up --watch` or to the language
authoring tool's `watch` command. A change to any bound input requires fresh
review. Keep the private specification in the developer workspace.

### Choose an HTTP client

Select a client that uses the standard API supported by the capsule's runtime
profile. Grant its destination and operations when you deploy it. These signed
runs exercised two published clients per language on the source revisions in
the linked records.

| Language | Clients called through their ordinary APIs | Runtime and signed results |
| --- | --- | --- |
| Rust | Waki 0.5.1 and golem-wasi-http 0.2.0 | [WASI HTTP requests, response parsing and pending operations](../testing/evidence/rust-wasi-http-signed-2026-10-21.json) |
| C | FreeBSD libfetch and libucl's URL includes, at the two pinned upstream commits | [libfetch reads and libucl parsing on the same C backend](../testing/evidence/c-http-pair-signed-2026-10-31.json) |
| TypeScript | Ky 2.2.0 and Wretch 3.0.9 | [Global Fetch, JSON parsing and each client's 404 behavior](../testing/typescript-published-fetch.md) |
| Go | Sling 1.4.0 and Requests 0.24.3 | [Default HTTP clients, domain results and private workers](../testing/evidence/go-http-tenant-catalogue-signed-2026-10-20.json) |
| Java | http-request 6.0 and DavidWebb 1.3.0 | [URLConnection factories and DavidWebb's transitive JSON parser](../testing/java-published-http.md) |
| C# / .NET | Flurl.Http 4.0.2 and Refit 16.4.0 | [HttpClient, generated Refit methods and parsed responses](../testing/evidence/dotnet-published-http-signed-2026-10-20.json) |

### Try a private JAR

From a directory alongside the SDK checkout, start with a JDK 25 library of
your own. This example calls `outside.sdkdemo.Library.calculate(25)` from the
generated greeting handler and expects `42`. Put the following in `Library.java`.

```java
package outside.sdkdemo;

public final class Library {
    public static int calculate(int value) {
        return value + 17;
    }
}
```

In PowerShell, build the library, create the application and review its capture.
Set `$sdk` to the path of your SDK checkout.

```powershell
$sdk = (Resolve-Path ../latent-service-fabric).Path
$author = Join-Path $sdk tools/java_capsule.py
New-Item -ItemType Directory -Path classes | Out-Null
javac --release 25 -d classes Library.java
jar --create --file outside-library.jar -C classes .
python $author new ./my-java
python $author add-local ./my-java --id outside-demo --jar ./outside-library.jar
python $author resolve ./my-java --candidate ./candidate.json
Get-Content -Raw ./candidate.json
$digest = 'sha256:' + (Get-FileHash ./candidate.json -Algorithm SHA256).Hash.ToLowerInvariant()
python $author review-lock ./my-java --candidate ./candidate.json --expect $digest
python $author dependencies ./my-java
```

In `my-java/src/dev/latent/app/Capsule.java`, use
`return Result.ok(Integer.toString(outside.sdkdemo.Library.calculate(25)));`
as the successful return in `greet`. Follow the offline build and package steps
in the [Java dependency guide](java-dependencies.md). Invoke the deployed
`greet` with a nonempty name and check that the response is `"42"`.

## How the capture is stored

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

The developer workflow derives `dependencyInputs` when it loads
`latent.project.json`. The approval identity includes the dependency manifest,
reviewed lock, compiler/runtime/feature selection and executable-input identities.
Source edits can retain approval; a changed reviewed dependency lock or selected
profile requires a fresh `latent-dev dev trust`. An explicitly supplied stale
`dependencyInputs` binding is rejected instead of silently replaced.

The manifest, reviewed lock, native lockfiles and captured object directory are
automatically included in source/watch snapshots. Required dependency inputs
cannot be excluded. Snapshot acceptance and every build/cache-reuse check verify
the closed graph, original object bytes, patch preimages and native locks offline
before updating the accepted project or build. Capture metadata never authorizes
execution of package hooks or generators.

For the maintained frontend layout, keep the dependency manifest, reviewed lock
and objects alongside `latent.project.json`, with editable application sources
under the descriptor's exact `build.workingDirectory` (normally `app/`). Native
lock paths in the outer manifest are relative to that outer project, for example
`app/Cargo.lock` or `app/packages.lock.json`. The build receipt preserves those
original paths and projects their exact bytes to the application's owned build
directory. An inner dependency manifest, lock or project descriptor is rejected
as an ambiguous selection. A second descriptor cannot redirect the approved
application directory.

The common recipe helper verifies the descriptor association and captured graph
before materialization. It binds the outer manifest, lock, descriptor and native
path projection into the existing source observation, then rechecks the same
inputs after the build. The CAS remains outside the compiler's ordinary source
namespace; only selected materialized dependency files enter it. Staged recipes
include the descriptor, capture and authoring-state module closure and verify
selected bytes without importing a checkout or reopening the original source.
These input controls do not establish language compiler, node invocation or
watch qualification for a new library.

The developer controller retains its smaller transport bounds: 64 input roots,
2,048 files, 16 MiB per file and 64 MiB in a source snapshot. Captures exceeding
those bounds fail explicitly; use the standalone build workflow for a larger
reviewed closure. The helper includes the same capture verifier and can inspect
an offline snapshot from outside the repository without reaching private sources.

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

Offline verification also binds each lock artifact's public source record to the
manifest: an exact repository alias and relative path, or `captured-local` without
the original local path. Changed origins, extra private configuration and
malformed source records fail with `dependency-lock-source-drift` before
materialization or receipt publication, even when the artifact bytes still match.

Normal recipes materialize the reviewed closure from content-addressed objects
without resolution or provisioning. Missing, changed and uncaptured inputs fail
with a concrete dependency diagnostic. Builds recheck manifests, native locks,
original objects and materialized bytes after compilation. The post-build check
reconstructs each selected artifact from the captured original bytes and reviewed
transformation chain, including original directory-file preimages and intermediate
replacement objects. Missing or changed cache bytes fail even when the final
materialized file is unchanged; no original source path is reopened and no fetch
is attempted. Their receipt records selected inputs, transformations and the
resulting input identity. Signing,
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

Language authoring commands delegate tests and watch updates to the maintained
frontend. A source command may use the controller only from its own observed
source tree. A staged compiler recipe omits that controller and requires an
explicit standalone frontend path and exact `sha256:<64 hex>` byte identity;
it never selects a controller through `PATH` or another Python installation.
Use the frontend from the already authenticated developer installation. The
executable digest selects those bytes and does not grant recipe, publisher or
application dependency trust.

The standalone delegate holds protected input handles, rechecks the executable
and pathname after execution, omits ambient production credentials, and retains
only bounded output. Its finite wrapper deadline and local process cleanup do
not settle a remote operation. Frontend exit 5 remains uncertain and exit 130
remains interrupted; inspect the original workspace status before continuing.
Receipt-write failure preserves that original outcome and never permits replay.
