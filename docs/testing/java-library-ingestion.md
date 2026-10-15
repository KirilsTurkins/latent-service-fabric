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

For authenticated private Maven input, use the separate private-feed control.
It first preserves the local-JAR control, then serves those exact original JARs
under new private Maven coordinates with a real transitive POM. The finite HTTPS
peer uses an isolated synthetic TLS identity from the selected native tuple.
Missing/wrong credentials, an incomplete credential pair and an untrusted CA
must fail without replacing the prior accepted capture. Resolver credentials
and the private TLS key must be absent from captured application bytes.

```bash
: "${JAVA_PRIVATE_RUN:?Set another fresh output directory outside the checkout}"
python3 tools/qualify_java_private_dependencies.py --resolve-only \
  --output "$JAVA_PRIVATE_RUN" \
  --native-directory "$NATIVE_DIRECTORY" --native-tuple "$NATIVE_TUPLE"
```

After the peer has been physically reaped, disable external networking and run
the same ordinary component/package/signing/node boundary on that exact private
closure:

```bash
python3 tools/qualify_java_private_dependencies.py --offline \
  --output "$JAVA_PRIVATE_RUN" \
  --native-directory "$NATIVE_DIRECTORY" --native-tuple "$NATIVE_TUPLE" \
  --wasi-sdk "$WASI_SDK_PATH" --read-only-cache "$JAVA_COMPILER_CACHE"
```

Certificate or captured private-JAR drift must fail, and restoring the exact
preimage must restore the captured identity. The ordinary node executes the
private direct/transitive code and its resource after originals and the peer
are unavailable. These controls retain installed update/remove/watch and the
full trap/exhaustion/cancellation lifecycle as separate acceptance gates.

The [15 October private control](evidence/java-private-dependency-ingestion-2026-10-15.json)
retains six actual authentication/trust/integrity denials, the reaped peer and
the subsequent network-disabled signed private-library/resource execution.
It records the earlier fixture setup failures without bypassing certificate
verification or rewriting their outcomes.
