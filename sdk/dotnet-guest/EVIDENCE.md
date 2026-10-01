# NuGet runtime coverage observations

The 1 October 2026 local control compiled an ordinary SmartFormat JSON extension,
Newtonsoft.Json/ZString transitives and an independently selected developer DLL
with managed embedded-resource lookup through the captured NativeAOT recipe.
NativeAOT exited successfully in 73.80 seconds with upstream trimming/AOT
warnings. Composition failed with both the bundled WAC 0.10.0 and reviewed
0.10.1; no package signing, admission or guest invocation followed this attempt.

The retained raw component is 30,463,363 bytes, with identity
`sha256:dc9dac40ba449c4590e33b811964957d9549290e865a4d761c09b3446aabf5cb`.
An actual wasm-tools 1.254.0 metadata control compared that component with the
original compiled adapter. The [original coverage receipt](evidence/nuget-original-runtime-coverage.json)
records 23 missing types, methods and interfaces, including WASI HTTP imports.
The [proposed source coverage receipt](evidence/nuget-proposed-runtime-coverage.json)
records the repaired IO/filesystem WIT's remaining two HTTP interfaces. That
second observation explicitly covers source WIT; the repaired adapter has not
yet been compiled or executed by this control.

Raw bytes, authoritative WIT JSON, command outputs and the original adapter
remain in the local attempt directory. This local control did not retain the
full source snapshot, so these checked-in receipts are limited metadata
observations. They do not replace a source-bound build observation, the final
WIT inspection or exact-head signed-node qualification. Member names alone do
not establish type compatibility, reachable behavior, resource retirement,
reflection support or ordinary HttpClient operation. Issue #687 remains open.
