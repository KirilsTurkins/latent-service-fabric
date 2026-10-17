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
application state and recovery after a declared error. Private-feed,
trap/exhaustion/cancellation and delivered update/remove/watch controls have
separate maintained programmes and source-bound receipts, described below.
One programme's success does not substitute for the complete #682 checklist.

The [15 October native control](evidence/java-dependency-ingestion-2026-10-15.json)
retains the actual qualifier, component and ordinary native-product identities.
Its separate approved annotation-processor control retains source-owner denials,
host containment and signed generated-source execution. These finite observations
remain bound to their recorded source and do not establish release qualification.

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
are unavailable. The recovery and delivered update/remove/watch programmes
exercise the remaining lifecycle boundaries separately; the private receipt
does not substitute for those observations.

The [15 October private control](evidence/java-private-dependency-ingestion-2026-10-15.json)
retains six actual authentication/trust/integrity denials, the reaped peer and
the subsequent network-disabled signed private-library/resource execution.
It records the earlier fixture setup failures without bypassing certificate
verification or rewriting their outcomes.

The maintained workflow also selects `private` in a separate dependency matrix
job using [the suite owner](../../tools/qualify_java_dependency_suite.py). It
builds and freezes the ordinary five native products, compiles a normal greeting
to acquire the pinned compiler closure, then supplies only its verified read-only
cache to the private programme. Exact source/native/compiler/cache identities
are checked before and after; private keys and signing directories are excluded
from the new artifact allowlist. The existing Java job retains its 55-minute
limit and commands. Each separate attempt has a 35-minute job bound and an
1800-second suite deadline. Historical successful receipts retain their source
scope; each changed selected source needs its own hosted qualification.
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

The maintained workflow also selects `recovery` in a separate dependency matrix
job using [the suite owner](../../tools/qualify_java_dependency_suite.py). It
builds and freezes the ordinary five native products, compiles a normal greeting
to acquire the pinned compiler closure, then supplies only its verified read-only
cache to the recovery programme. Exact source/native/compiler/cache identities
are checked before and after; signing directories are excluded from the new
artifact allowlist. The existing Java job retains its 55-minute limit and
commands. Each separate attempt has a 35-minute job bound and an 1800-second
suite deadline. The earlier successful native receipt remains historical; each
changed selected source needs its own hosted qualification.

The [delivered dependency-watch control](java-dependency-watch.md) uses captured
local/transitive JARs after removing their originals, then reviews, trusts and
signs each initial, updated and removed selection in a fresh test workspace. Its
`703f4148b39273e91c097af05674500860afa5f8` source receipt passed three actual
deployments and three normal clean, reaped shutdowns in
[hosted job 117193495390](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/38966294350/job/117193495390).
That receipt verifies all 99 delivered helper source/resource paths and the
qualifier/probe identities. The same source's separate private and recovery
jobs also passed. These observations remain source-scoped when the public
diagnostic projection changes; the corrected current head still needs its own
native, watch, general CI and security gates before the final #682 checklist and
merge. The dated evidence files keep their original partial-scope claims.
