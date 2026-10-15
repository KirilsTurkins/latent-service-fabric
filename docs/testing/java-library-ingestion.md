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
application state and recovery after a declared error. The earlier baseline
receipt retains the separate private-feed, installed update/remove/watch,
processor and trap/exhaustion/cancellation gates; a successful run does not close
#682.

The [15 October native control](evidence/java-dependency-ingestion-2026-10-15.json)
retains the actual qualifier, component and ordinary native-product identities.
Its separate approved annotation-processor control retains source-owner denials,
host containment and signed generated-source execution. These finite observations
do not establish release qualification or the remaining issue requirements.

The current control additionally invokes intentional uncaught Java heap
allocation exhaustion, an uncaught exception, a 64 KiB Wasm memory limit and a
10,000,000-fuel spin. It observes the original cancellation activation running
before sending one cancellation. Every case must retire activation owners,
quotas and cell reservations, then execute a fresh actual library invocation.
The [recovery receipt](evidence/java-dependency-recovery-2026-10-15.json) binds the
offline component, both qualifier sources and unchanged ordinary native products.

The allocation control checks the bounded heap and cleanup after an uncaught
failure. An earlier attempt to catch `OutOfMemoryError` instead produced an
unreachable-code guest trap. That failed attempt remains recorded; this control
does not establish catchable allocation failure semantics for the selected TeaVM
C runtime. The independent runtime implementation owner is #741.
