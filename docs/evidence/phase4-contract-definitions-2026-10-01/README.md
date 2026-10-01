# Phase 4 compiler definition and HTTP preparation observations

All six maintained compiler owners successfully generated and compiled the shared
transaction/query/intent contract at PR #766 head
`a26b5bd5e8371950fcba9654ee9699efb4dfb5f4`. Their actual checkout was the clean
GitHub pull-request merge `29771c51dfbb83181a083f7bcc78bd99266c724d`; all six
retained source archives have digest
`sha256:af80fff1466f574c388b83868687c792a976fc8722191b6f9bcfb34877b34f35`.

[The observation index](observation.json) records the exact job, artifact,
report, component, source and profile digests. The reports below are the original
CI bytes. The original artifact digests were checked against GitHub metadata;
component bytes and shared source files were independently hashed after download.
This observation does not qualify a later source revision.

| Language | Maintained compiler owner | Successful CI job | Original definition receipt |
| --- | --- | --- | --- |
| Rust | Rust 1.97.1; wit-bindgen 0.62.0 | [Standalone authoring](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36797413820/job/110163921644) | [Rust](rust/report.json) |
| C | Zig 0.16.0; wit-bindgen 0.62.0 | [Capability ownership](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36797413872/job/110163921704) | [C](c/report.json) |
| TypeScript | Node 24.19.0; Jco 1.34.0 and the maintained componentize-js closure | [Value and ownership boundary](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36797413880/job/110164345903) | [TypeScript](typescript/report.json) |
| Go | Maintained patched Go 1.27.1 and componentize-go | [Runtime and capsule qualification](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36797413965/job/110163922359) | [Go](go/report.json) |
| Java | JDK 25.0.4.1+1; TeaVM 0.15.0; WASI SDK 29 / LLVM 21.1.4 | [Actual Java authoring](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36797413886/job/110163921615) | [Java](java/report.json) |
| C#/.NET | Linux .NET SDK 10.0.100; maintained preview00011 NativeAOT closure | [NativeAOT component qualification](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36797413878/job/110163921868) | [.NET](dotnet/report.json) |

The definition probes use the authoritative imported resource owners, reused
types, option/result/record/list values and async signatures. Each receipt records
independent generated binding inventories and the validated compiled component.
Generator projections preserve the original nominal owners and authoritative
async contract; no language gets a different public protocol.

The Rust lane also ran the real Wasmtime 48.0.3 type-plan checks under the
[HTTP-enabled preparation profile](../../../sdk/profile/transaction-preparation-v1.json).
[Its preparation receipt](rust/preparation.json) qualifies all 13 operations,
including eight asynchronous operations and 26 parameter/result plans. The largest
predicted lift is 33,557,384 bytes, below the existing 67,108,864-byte limit; the
2,097,152-byte hostcall wire limit is unchanged. The lane also passed the nested
page amplification regression and unknown resource-owner rejection tests.

`compilerDefinitionQualified` and `preparationQualified` describe these measured
boundaries. Every retained receipt explicitly leaves `runtimeExecutionQualified`
and `externalClientExecutionQualified` false. Even where the same job qualifies
older stateless components, that does not turn this transaction probe into signed
node execution. #389/#718, #401, #388/#408 and #409 retain their own execution gates.

To reproduce the definition inputs, run
`python tools/generate_transaction_contracts.py --check`, then the maintained
language lane or `tools/qualify_transaction_contracts.py`. Use the exact source,
tool pins and ABI/preparation identities from the receipts. Fresh compiler
receipts must name their own actual checkout and component bytes.
