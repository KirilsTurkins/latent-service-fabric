# Java application JARs

The Java recipe accepts developer-selected Maven and local/private JARs through
the [captured dependency contract](application-dependencies.md). Resolution uses
the pinned Gradle/JDK pair and an SDK-owned finite task. Application Gradle
plugins, arbitrary Maven scripts and annotation processors do not execute.

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
native POM/module metadata, `latent.dependencies.json` and lock candidate:

```powershell
python tools/java_capsule.py resolve ./my-java --candidate ./java-lock-candidate.json
Copy-Item -LiteralPath ./java-lock-candidate.json -Destination ./my-java/latent.dependencies.lock.json
python tools/java_capsule.py build ./my-java --output ./my-java/target/build-1 --repository https://github.com/example/application --wasi-sdk ./wasi-sdk-29 --offline-cache ./reviewed-gradle-modules-2
```

`compile` and `runtime` declarations participate in the captured runtime graph.
Exact releases are required; changing/dynamic versions and snapshots fail.
Gradle's selected conflict/exclusion decisions and variant attributes enter the
native resolution lock. Original POM and Gradle module descriptors remain
captured independently of JAR bytes. Local JAR declarations have `id`, `path` and
`dependencies` fields. Their declared transitive edges must name another captured
artifact. A compatible new JAR requires no LSF source edit or catalogue entry.

For a repository alias such as `private`, configure
`LSF_REGISTRY_PRIVATE_USERNAME` and `LSF_REGISTRY_PRIVATE_PASSWORD` only during
resolution. URLs with userinfo/query credentials are rejected. Credentials are
not copied into manifests, native locks, compiler environments or public
diagnostics. The compiler never contacts these application repositories and
requires a separately reviewed offline compiler cache.

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
