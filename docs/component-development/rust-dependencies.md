# Captured Cargo dependencies

Edit the ordinary application `Cargo.toml` and generate/review its native `Cargo.lock` independently of `sdk-lock.json`. Public registry, exact git revisions and outside-project path crates use Cargo's resolver. Package names identify provenance and do not require LSF catalogue entries. Keep the SDK workspace inheritance and maintained guest/WIT dependency declarations pinned.

Resolve explicitly, review the application candidate, then use the existing build/package/admission commands:

```powershell
python tools/rust_capsule.py resolve ./my-rust --candidate ./cargo-candidate.json --features pure
Copy-Item -LiteralPath ./cargo-candidate.json -Destination ./my-rust/latent.dependencies.lock.json
python tools/rust_capsule.py build ./my-rust --offline --output ./my-rust/target/build-1 --repository https://github.com/example/application
```

The separate fetch stage runs native `cargo metadata` and `cargo vendor --locked` from an owned working directory and empty Cargo home. It records the complete resolver graph, selected target graph, enabled/default features, native lock, package/source/target/license metadata and tool bytes in `cargo-resolved.lock.json`. Private registry tokens are read only by this explicit resolver and are absent from compilation environments and public evidence. Private registry endpoint configuration must be explicitly supplied to the resolver; ambient home/project Cargo configurations are not consumed.

Outside-project path manifests receive an automatic path-relocation transformation. Original source and original manifest bytes remain in the content store; the selected adapted bytes, preimages, recipe and selection are captured separately. A native path/source change requires resolve and lock review. Ordinary builds need only the captured bytes, so deleted original local paths and absent network caches do not resolve a new graph.

Captured compilation requires the managed Linux host with Bubblewrap and the pinned Rust and Zig distributions. The namespace contains the owned workspace, complete selected compiler/sysroot/runtime headers, selected tools and observed host libraries. It has no network, empty home and no inherited production credentials. SDK-owned binding macro inputs remain separately attributable compiler materials. Additional application `build.rs` or proc-macro packages are recorded as executable inputs and require the separate explicit isolated tool-approval stage; capture alone does not authorize their execution. A host without the maintained containment profile fails concretely.

The existing Wasm target and panic-abort profile remain authoritative. This ingestion path does not qualify a new standard-library, threading, executor or networking implementation; those changes require the exact runtime/profile and actual component evidence. Source-only builds retain their existing behavior. Final WIT inspection, signing/admission and invocation budgets remain independent of successful capture. The builder binds `application-dependencies.json`, `cargo-inputs.json` and `rust-compiler-inputs.json` and rechecks them before accepting the component.

Current controls cover path relocation, graph closure, executable denial, owned offline Cargo configuration and native source-only regressions. Cold resolver, signed third-party/transitive/resource execution and the full panic/fuel/cancellation/runtime matrix still require retained actual qualification receipts.
