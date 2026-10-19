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

Subsequent qualification supersedes the pending MemoryPack plan, while retaining
that failed SmartFormat attempt as historical evidence. [PR #1028](https://github.com/KirilsTurkins/latent-service-fabric/pull/1028)
qualifies the captured MemoryPack 1.21.4 generated serialization path and developer
assembly resources. [PR #1054](https://github.com/KirilsTurkins/latent-service-fabric/pull/1054)
adds selected native/PInvoke asset refusal. [PR #1126](https://github.com/KirilsTurkins/latent-service-fabric/pull/1126)
qualifies authenticated private-feed capture, offline builds, identity variation,
update/removal and signed execution without retaining feed credentials.

The [descriptor reflection run](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39307965194)
passed on fixture `37aff00e5fe850c2f4058f2485ab1591dcee2931`.
Its fresh offline NativeAOT component executed 31 signed calls: the original 27
node cases and four descriptor/refusal/fresh-state cases. The descriptor is 142
bytes, SHA-256 `9616165318c375ecc16ffabfeffa0026183a1ce9bfe9cd3752faa7af4c21f445`.
Every invocation was known and reaped; the node stopped cleanly and all three
peer holds closed. This replay authenticated and reused the five native products
compiled at `03a3f74598f2abfd0224169ae2871818f6c8419d`; it did not recompile them
or rerun their complete language matrix. Production fixture and qualifier bytes
match the tested source, and the shared runner's exercised path is unchanged.
See [the programme](../../docs/testing/dotnet-reflection-qualification.md) for the
explicit noncrypto entropy grant and supported/refused boundary. These results
do not establish a complete CLR, arbitrary reflection or default HttpClient.
