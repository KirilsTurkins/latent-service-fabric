# Java library compiler negatives

`tools/qualify_java_library_failures.py` builds an external JAR with the pinned
JDK, a native method, generic reflection and a real Linux shared-library resource.
It captures and reviews that original JAR through normal dependency resolution,
then removes the original JAR, Java source, classes and shared-library output.
No application startup or native library is loaded on the build host.

The programme compiles two separate entry points that call the native method
and the generic-reflection method. Each must fail at the actual TeaVM compiler,
retain its concrete compiler log and failed-stage record, and emit a validated
source-bound compatibility report. An unrelated failure cannot satisfy either
control. The original accepted closure and SDK remain unchanged.

A third entry point calls an ordinary method from the same captured JAR. It must
compile, package, sign, pass enforced node admission and return its actual result.
The node also checks a declared error followed by another successful call,
complete idle ownership, quota and cell observations, and normal clean shutdown.
This establishes that the presence of native or reflection bytes alone does not
ban the package. It does not establish compiler-proven API elimination.

The existing [Java CI](../../.github/workflows/java-guest-feasibility.yml) runs
this programme after preparing its ordinary default native tuple and exact
compiler dependency cache:

```sh
python tools/qualify_java_library_failures.py \
  --output /outside-checkout/java-library-failures \
  --native-directory /prepared/selected-native \
  --native-tuple /prepared/native/native-tuple.json \
  --read-only-cache /prepared/gradle-home/caches/modules-2 \
  --wasi-sdk /prepared/wasi-sdk-29.0-x86_64-linux
```

The workflow retains `qualification.json`, `FAILED.json`, original capture
identities, compiler logs, source/recipe/compiler inventories and actual node
receipts. Adding the programme is not evidence that a particular run passed.
Compiler failure and diagnostic attribution are separate observations. The
Java recipe preserves its generic `unresolved-behavior` report and retains
`compatibility-java-compiler-report.json` only for exact recognized diagnostics
from a failed TeaVM stage. It checks the retained source, compiler and classpath
against the recipe's in-memory captured inputs. Native methods require a matching
selected class owner and identify its original JAR digest. Missing `java.*`
runtime classes/methods identify the Java runtime owner, rather than claiming a
missing application capability. Unrecognized diagnostics remain unknown.

```sh
python -m tools.guest_compatibility output/compatibility-java-compiler-report.json
```

The actual programme requires target-incompatible native-method and missing
runtime-port reflection observations through this validated report. Neither
report can assert an eliminated API, grant authority or replace the original
compiler failure. Missing or changed evidence emits an unavailable observation.
