# Ordinary Rust WASI HTTP compiler inputs

The maintained Rust builder does not yet install a default WASI HTTP backend. This input control compiles an unseen developer-owned crate calling unchanged independent `waki 0.5.1` and `golem-wasi-http 0.2.0` through ordinary `Client::new().get(...).send()` and status/body APIs. Its coordinates vary; no SDK catalogue registration, library patch, injected transport or application executor is used.

[The owning job](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39511722541/job/118934118602) completed the compiler observation at source `a3454f48be8b3908ebf7dbbcc7dba883b4ab7ec7`. Both clients compiled in 47.874283 seconds. Normal componentization, validation and contract extraction succeeded. The original normal builder then **failed compatibility** because all six WASI imports were undeclared. That `BUILD-FAILED.json` is retained; no compatible build, package, signing, admission or HTTP execution is claimed.

The [source-bound observation](evidence/rust-wasi-http-inputs-2026-10-20.json) binds the complete 58-member artifact, 76 source materials, 69 compiler recipe rows, native products and original build documents. Before isolated offline compilation, normal authoring refused unapproved executable inputs; the campaign reviewed the exact 15 captured build-tool/procedural-macro inputs. Original library sources were removed before the approved build. Native products were reused from the separately authenticated Wasmtime 48.0.7 producer at `fc9b44a6b8dce9effd6b490f1a169a7ad8edbf12`; no native host or engine was rebuilt.

The source was later composed with development `6133f1cdeb01518b1aa00b447939ec8461e70438`. All 69 recipe rows and 75 of 76 source materials remain byte-identical. The shared native reader adds an opt-in protocol tree; its default stays false for the unchanged frozen fc9 wrapper. Later native API changes were not compiled or exercised by this observation.

## Actual graph

The 480,776-byte component contains three core modules and 94 core imports. Raw modules retain both WASI 0.2.2 and 0.2.12 families. The normal componentizer's validated final external graph exposes exactly:

- `wasi:clocks/monotonic-clock@0.2.12`
- `wasi:http/outgoing-handler@0.2.12`
- `wasi:http/types@0.2.12`
- `wasi:io/error@0.2.12`
- `wasi:io/poll@0.2.12`
- `wasi:io/streams@0.2.12`

Its export remains `examples:greeting/api@1.0.0`. The final WIT JSON is identical to the original compatibility inspector's command output. This is normal compiler composition evidence, not permission to manually rename raw resource types. The resolved Golem transitive dependency is `wasip2 1.0.4+wasi-0.2.12`; its manifest's `1.0.2` requirement is a semver range, not the resolved WIT identity.

## Remaining implementation

A selected backend must authenticate the complete final 0.2.12 WIT/profile, implement its actual resource/default/error semantics, and preserve compiler provenance for the raw-to-final composition. Request options, fields, bodies, streams, polling, responses and explicit monotonic time must share the existing bounded activation ownership and provider machinery. HTTP, runtime and monotonic authority remain explicit. Accepted work needs a compiler-owned root drain before result eligibility.

The existing smaller .NET HTTP subset remains a separate profile. This observation neither aliases that subset to standard WASI HTTP nor qualifies threads, an ecosystem executor, synchronous waits, HTTP effects or lifecycle retirement. The signed two-client/developer-crate and adversarial programmes in [#689](https://github.com/KirilsTurkins/latent-service-fabric/issues/689) remain open.

## Reproduce the input control

The dedicated `Rust default WASI HTTP compiler inputs` workflow on the input-control branch produced the historical observation. After native source changes, a new run requires a separately authenticated matching producer; its source-equality guard remains closed. It reuses pinned native products and performs one bounded offline guest compile; it does not sign or run an HTTP component. Six focused controls cover project/SDK invariants, upstream identities, bounded import decoding and exact executable approval. Compiler/import observations and normal compatibility failures are retained separately.
