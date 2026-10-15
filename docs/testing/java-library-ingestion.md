# Java library ingestion native controls

Use the pinned Linux compiler prerequisites from the
[Java authoring guide](../component-development/java-authoring.md).
The maintained native dependency control repeats the pure-library and resource
boundary on the selected source. It resolves Commons Text and Commons Codec,
retains Text's Commons Lang edge, compiles two independent local JARs and deletes
their originals before the offline stage. Acquisition and execution use separate
commands and preserve distinct failed attempts:

```bash
: "${JAVA_DEPENDENCY_RUN:?Set a fresh output directory outside the checkout}"
python3 tools/qualify_java_dependencies.py --resolve-only \
  --output "$JAVA_DEPENDENCY_RUN"
```

After acquisition, run the following in the maintained Linux environment with
external networking disabled. Supply a current ordinary native tuple and a
verified read-only compiler cache; each compilation uses its own mutable Gradle
home. The tuple must contain the actual default products and their source and
byte identities, as required by the
[native tuple verifier](../../tools/qualify_java_server_lifecycle.py).

```bash
: "${NATIVE_DIRECTORY:?Set the directory containing the five ordinary native products}"
: "${NATIVE_TUPLE:?Set their completed native-tuple.json receipt}"
: "${JAVA_COMPILER_CACHE:?Set the verified modules-2 compiler dependency cache}"
: "${WASI_SDK_PATH:?Set the pinned WASI SDK directory}"
python3 tools/qualify_java_dependencies.py --offline \
  --output "$JAVA_DEPENDENCY_RUN" \
  --native-directory "$NATIVE_DIRECTORY" --native-tuple "$NATIVE_TUPLE" \
  --wasi-sdk "$WASI_SDK_PATH" --read-only-cache "$JAVA_COMPILER_CACHE"
```

The control rejects missing or changed transitive JARs, builds the actual
component, signs an isolated fixture, checks unsigned publication and missing
runtime-grant denial, invokes library and resource paths, and observes owner
retirement after each call and node shutdown. Repeated calls check fresh static
application state and recovery after a declared error. Its receipt explicitly
retains the separate private-feed, installed update/remove/watch, processor and
trap/exhaustion/cancellation gates; a successful run does not close #682.

The [15 October native control](evidence/java-dependency-ingestion-2026-10-15.json)
retains the actual qualifier, component and ordinary native-product identities.
Its separate approved annotation-processor control retains source-owner denials,
host containment and signed generated-source execution. These finite observations
do not establish release qualification or the remaining issue requirements.
