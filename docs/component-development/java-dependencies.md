# Java application JARs

The Java recipe accepts developer-selected Maven and local/private JARs through
the [captured dependency contract](application-dependencies.md). Maven resolution
uses the pinned Gradle/JDK pair and an SDK-owned finite task. Local-only JAR
capture reads the selected bytes without starting Gradle or a host JVM.
Application Gradle plugins, arbitrary Maven scripts and annotation processors
do not execute.

These commands use the source-owned Java tool from an LSF checkout. Keep its
compiler and immutable SDK inputs pinned as described in
[Java authoring](java-authoring.md). They apply to a standalone project or the
outer project created by `latent-dev dev init`: the latter keeps declarations
under its authenticated `app/` directory and the captured manifest, reviewed lock
and objects alongside `latent.project.json`. Either entrypoint selects the same
application. An inner descriptor or dependency lock cannot override it.

Declare an exact release with the maintained editor:

```powershell
python tools/java_capsule.py add ./my-java org.apache.commons:commons-text:1.15.0 --scope runtime
```

Create `java-dependencies.json` in your standalone Java project:

```json
{
  "formatVersion": 1,
  "dependencies": [{
    "group": "org.apache.commons",
    "name": "commons-text",
    "version": "1.15.0",
    "scope": "runtime",
    "exclusions": []
  }],
  "localJars": [],
  "repositories": [{"id": "central", "url": "https://repo.maven.apache.org/maven2/"}],
  "selection": {"release": 25, "runtimeProfile": "java-teavm-c"}
}
```

Resolve explicitly and review the resulting `java-resolved.lock.json`, captured
native POM/module metadata, `latent.dependencies.json` and lock candidate. Accept
the exact reviewed candidate digest before building:

```powershell
python tools/java_capsule.py resolve ./my-java --candidate ./java-lock-candidate.json
$reviewed = 'sha256:' + (Get-FileHash -Algorithm SHA256 -LiteralPath ./java-lock-candidate.json).Hash.ToLowerInvariant()
python tools/java_capsule.py review-lock ./my-java --candidate ./java-lock-candidate.json --expect $reviewed
python tools/java_capsule.py dependencies ./my-java
python tools/java_capsule.py build ./my-java --output ./my-java/target/build-1 --repository https://github.com/example/application --wasi-sdk ./wasi-sdk-29 --offline-cache ./reviewed-gradle-modules-2
```

`resolve` leaves the previous reviewed lock intact and refuses to reuse a
candidate path. `review-lock` verifies the manifest, native graph, object bytes
and current SDK before atomically replacing that lock. Editing a declaration
requires another capture and review; a failed attempt retains a bounded static
receipt and never substitutes a new approval. Keep the captured object directory
with the project for offline builds.

`compile` and `runtime` declarations participate in the captured runtime graph.
Exact releases are required; changing/dynamic versions and snapshots fail.
Gradle's selected conflict/exclusion decisions and variant attributes enter the
native resolution lock. Original POM and Gradle module descriptors remain
captured independently of JAR bytes. Local JAR declarations have `id`, `path` and
`dependencies` fields. Their declared transitive edges must name another captured
artifact. A compatible new JAR requires no LSF source edit or catalogue entry.

Capture developer-selected JARs with unchanged Java package names and explicit
transitive edges:

```powershell
python tools/java_capsule.py add-local ./my-java --id developer/helper/1 --jar ./private/helper.jar
python tools/java_capsule.py add-local ./my-java --id developer/library/1 --jar ./private/library.jar --depends developer/helper/1
python tools/java_capsule.py resolve ./my-java --candidate ./local-java-candidate.json
```

Review and accept that candidate with `review-lock` as above. The original JARs
may then be removed or unavailable; the verified captured closure supplies their
bytes. A JAR kept inside the application is accepted only when its exact path
and digest match the current reviewed declaration. Undeclared JARs, classfiles
and application build scripts remain rejected.

Updates and removals preserve the old reviewed lock until the new graph is
captured and explicitly accepted:

```powershell
python tools/java_capsule.py update ./my-java org.apache.commons:commons-text --version 1.15.0
python tools/java_capsule.py update ./my-java developer/library/1 --jar ./private/library-next.jar
python tools/java_capsule.py remove ./my-java developer/library/1
```

Use the exact release you intend to select; the update editor does not fetch or
choose a version. Remove or update dependent edges too when removing a local JAR.
Resolution rejects an incomplete graph before publishing its manifest or candidate.

For a repository alias such as `private`, configure
`LSF_REGISTRY_PRIVATE_USERNAME` and `LSF_REGISTRY_PRIVATE_PASSWORD` only during
resolution. URLs with userinfo/query credentials are rejected. Credentials are
not copied into manifests, native locks, compiler environments or public
diagnostics. The compiler never contacts these application repositories and
requires a separately reviewed offline compiler cache.

For a new private repository, `add` accepts `--repository-id private` and
`--repository-url https://your-host.example/maven/`. Supply credentials through
the matching environment variables separately. Only those declared credential
slots enter the finite resolver environment, and failed resolver output is
discarded from public receipts. Repository aliases that normalize to the same
credential slot are rejected.

For the outer project created by `latent-dev dev init` in a connected,
authenticated development workspace with prepared node test fixtures, trust the
reviewed project and delegate the normal test/watch flow. A standalone project
created by `java_capsule.py new` uses the direct build/sign/node guide and needs
an authenticated development descriptor before it can delegate these actions:

```powershell
latent-dev dev trust --workspace java-test --project ./my-java
python tools/java_capsule.py test ./my-java --workspace java-test --select greeting
python tools/java_capsule.py watch ./my-java --workspace java-test --select greeting
```

Source delegation uses only the observed frontend in that same checkout. A
staged recipe requires an explicit authenticated standalone executable supplied
with `--frontend` and its exact `--frontend-sha256`; its digest selects the bytes
and does not replace publisher verification. Watch snapshots include the exact
outer manifest, lock and objects. A dependency/profile change needs fresh
project trust. Unresolved or interrupted frontend operations retain their exit
and uncertainty receipts; inspect `latent-dev dev status`/`dev recover` before
doing more work. The authoring wrapper does not replay the operation.

Classpath order follows the reviewed captured inventory. Duplicate classes and
lookup resources fail even when their bytes match. Legal/signature/manifest/module
metadata remains local to each JAR, with explicit captured classpath precedence.
Multi-release JARs select the
highest version at or below the pinned Java release. Shaded names remain unchanged;
the recipe performs no implicit relocation. Service-provider files keep exact
UTF-8 provider metadata without executing library startup on the host. Native
assets remain attributed inputs; their presence does not establish reachable JNI
compatibility. Platform/JDK/SDK class overrides and too-new or malformed bytecode
fail concretely.

TeaVM compiler extension services are host executable inputs and fail closed
until a separately approved isolated tool stage supplies them. Ordinary guest
service-provider resources are preserved; annotation processing is disabled.

`java-classpath.json` binds original JARs to deterministic selected JARs, every
class/resource entry, selection rules and classpath order. Original vendor
signatures apply to original bytes only. Selected JARs compile through the actual
TeaVM C/component pipeline with `-proc:none`. The recipe rechecks both original
closure bytes and selected JARs before issuing a successful build receipt.

Resolution also captures every selected classpath lookup resource as a separate
`resource` artifact. Its parent JAR retains a graph edge and records the original
JAR digest, logical lookup name, original ZIP entry and selected multi-release
version. The child owns the exact raw bytes, digest and size; a whole-JAR digest
cannot stand in for a resource digest. Re-resolve and review older resource locks
that lack these children before building them with this recipe.

Package assembly verifies the child bytes against the selected original JAR,
materialized closure and captured store. Only those verified bytes enter resource
asset layers and `resource-index.json`, which binds the source inventory,
dependency lock and resulting component. Resource names, count, per-file bytes
and aggregate bytes have fixed limits; ambiguous names and duplicate lookup
resources fail. The index preserves opaque bytes and grants no filesystem or
scratch access. This packaging observation does not establish Java runtime
lookup. TeaVM's C class-library resource implementation and ordinary
`Class.getResourceAsStream`/`ClassLoader.getResourceAsStream` calls still require
emitted-component qualification.

This delivers captured JAR ingestion; it does not independently qualify every
Java library API. Actual classpath lookup, reflection/native/runtime compatibility,
signed-node library execution and resource/cleanup acceptance still require
emitted-component tests. Runtime concurrency and default HTTP profiles have their
own implementation and qualification tickets. No host JVM service is deployed.
