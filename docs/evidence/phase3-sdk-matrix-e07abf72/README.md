# Six native clients against the real provider node

Executed on 2026-09-19 from source
`e07abf72cbf78c8c27df7a54cfb2859c007c9397`, after node fix `89d61e14`.
These are actual runner outputs, not edited acceptance flags or test doubles.
The Linux x86-64 build container has a 10 GiB memory ceiling and three CPU
equivalents. This bounded correctness run is not a performance campaign.

The [aggregate](matrix.json) binds identical node, CLI and signed guest fixture
hashes across all six participants. The raw files retain their original bytes
and the aggregate records each raw receipt's SHA-256:

| Client | Executed receipt | Assertions | Authenticated upstream requests | Started and physically closed holds |
| --- | --- | --- | --- | --- |
| Rust | [Rust](rust.json) | 18 | 6 | 4 |
| TypeScript | [TypeScript](typescript.json) | 18 | 6 | 4 |
| Go | [Go](go.json) | 18 | 5 | 4 |
| C | [C](c.json) | 18 | 6 | 4 |
| Java | [Java](java.json) | 18 | 6 | 4 |
| .NET | [.NET](dotnet.json) | 18 | 5 | 4 |

Every participant retains nine activation IDs, its known mutation operation,
all required cancellation/recovery/shutdown assertions, zero unexpected
upstream requests and a clean reaped node with provider owners retired.
The frozen aggregate can be recomputed with:

```sh
python3 tools/verify_sdk_provider_matrix.py docs/evidence/phase3-sdk-matrix-e07abf72
```

Build and execution use the maintained driver, not six ad hoc substituted
clients: `tools/run_sdk_provider_matrix.sh build`, fresh signed fixture export,
then `tools/run_sdk_provider_matrix.sh run CLI NODE FIXTURE`. Pins are Rust
1.97.1, Node 24.19.0, Go 1.27.1, Temurin 21.0.11+10, .NET SDK 8.0.425/runtime
8.0.31, and the existing reviewed native C/nghttp2/protobuf-c profile. The
five-second Java ordinary-call choice does not change the separate
500-millisecond held-deadline check or production client defaults.

Earlier combined attempts remain failed/partial. This result does not qualify
a browser, an installed native bundle, a newer node binary, or future source
changes. The required remote CI and individual SDK acceptance reviews still
govern merging and ticket closure.
