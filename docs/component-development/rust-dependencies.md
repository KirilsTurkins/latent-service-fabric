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

A build with application executable inputs first retains `executable-input-approval-request.json` and a failed-stage receipt before compiling them. Review that request's exact source, dependency graph, executable bytes, recipe, compiler/sysroot and containment profile. Then pass its `identity` to a fresh build output:

```powershell
Get-Content ./my-rust/target/build-1/executable-input-approval-request.json
# After reviewing the exact specification and choosing to authorize these tools:
$executablePolicy = Get-Content ./my-rust/target/build-1/executable-input-approval-request.json | ConvertFrom-Json
python tools/rust_capsule.py build ./my-rust --offline --executable-approval $executablePolicy.identity --output ./my-rust/target/build-2 --repository https://github.com/example/application
```

An approval becomes stale when any bound input changes. Source, selected dependency and compiler distribution mounts are read-only during tool execution; generated output goes to the owned target directories and is digest-bound in `executable-input-outputs.json`. Finite command deadlines reap the namespace and its descendants. This boundary targets a trusted single-user compiler host and does not claim hardened multitenant or fully hermetic execution.

The existing Wasm target and panic-abort profile remain authoritative. This ingestion path does not qualify a new standard-library, threading, executor or networking implementation; those changes require the exact runtime/profile and actual component evidence. Source-only builds retain their existing behavior. Final WIT inspection, signing/admission and invocation budgets remain independent of successful capture. The builder binds `application-dependencies.json`, `cargo-inputs.json` and `rust-compiler-inputs.json` and rechecks them before accepting the component.

The required Rust authoring CI selects `unicode-normalization` and a developer-owned external crate independently in the application's ordinary `[dependencies]`. The application calls both ordinary APIs directly, and the retained fixture receipt requires both native root edges in the complete and selected-target Cargo graphs. The captured closure includes the native `tinyvec`/`tinyvec_macros` transitive graph and immutable UTF-8 bytes. The fixture exercises a root build script and external procedural macro, retains the unapproved denial, then authorizes only that SDK-owned fixture's exact request, removes the original external sources, compiles offline, signs and admits the resulting component, and runs the normal node workflow. Both executable controls assert that ambient files, credentials and network access are unavailable. These are qualification fixtures and never select application behavior. A passing receipt for the exact commit is required before claiming that qualification; additional panic/unwind, async/thread/network profiles and the complete feature/denial matrix keep their separate evidence requirements.

The dependency greeting fixture uses a five-second wall limit in both its signed capsule and deployment, matching the experiment node's existing maximum. Run `36786586820` exhausted the earlier one-second ceiling during cold preparation at 1,001,448 microseconds, with zero guest fuel and memory recorded; this establishes a lower bound, not a successful cold timing. Subsequent receipts retain cold and warm invocation times and the fixture's original and selected ceilings. Ordinary project defaults and the separate 100 ms deadline/cancellation controls retain their existing limits.
