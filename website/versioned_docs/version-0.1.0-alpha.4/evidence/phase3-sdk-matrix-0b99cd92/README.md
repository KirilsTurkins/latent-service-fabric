# Six-client qualification after development integration

Executed on 2026-09-20 at source
`0b99cd92a455c79f9343c54ec00acd3607063a02`, including development
`8d0db1055857e18aca2e05aef2f25728ec2094bd`. The Linux x86-64 container used
three CPU equivalents and a 10 GiB memory ceiling. This is bounded correctness
qualification, not a resource or latency campaign.

The [unmodified aggregate](matrix.json) and its raw
[Rust](rust.json), [TypeScript](typescript.json), [Go](go.json), [C](c.json),
[Java](java.json) and [.NET](dotnet.json) receipts retain 108 passing assertions,
54 actual activation IDs, six operation receipts, 24 started and physically
closed upstream holds, zero unexpected requests and six cleanly reaped nodes.
All clients consumed identical node, CLI and freshly signed fixture digests.

Recompute the aggregate with:

```sh
python3 tools/verify_sdk_provider_matrix.py docs/evidence/phase3-sdk-matrix-0b99cd92
```

The maintained `tools/run_sdk_provider_matrix.sh build` compiled all six
participants under Rust 1.97.1, Node 24.19.0, Go 1.27.1, Temurin 21.0.11+10,
.NET SDK 8.0.425/runtime 8.0.31 and the pinned Zig/nghttp2/protobuf-c profile.
The C participant's controlled peer and allocation-failure tests passed during
that build. Fresh Rust/C guest generation and all ten executable guest SDK
tests passed before the actual provider fixture export and complete matrix.

The integrated repair retains one blob call while shared worker maintenance
briefly owns its task table. Every admission attempt checks the original
deadline and cancellation; no physical operation or mutation is replayed.
All 89 capability tests passed, including deterministic contention,
cancellation, abandonment, true capacity exhaustion and physical-owner cleanup.
The cancellation regression first exposed a missing admission checkpoint; the
retained code checks stop state before accepting the worker. Focused Clippy
completed with the existing crate warnings; it is not reported as warning-free.

Earlier failed or historical attempts keep their original status. This receipt
does not establish browser, installed-bundle, performance or later-source
qualification. Required PR CI and each client's full acceptance review remain
the merge and ticket-closure gates.
