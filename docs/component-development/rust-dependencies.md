# Captured Cargo dependencies

Edit the ordinary application `Cargo.toml` and generate/review its native `Cargo.lock` independently of `sdk-lock.json`. Public registry, exact git revisions and outside-project path crates use Cargo's resolver. Package names identify provenance and do not require LSF catalogue entries. Keep the SDK workspace inheritance and maintained guest/WIT dependency declarations pinned.

Use normal native `add`, `update`, `remove` and `lock` stages for application declarations. These are explicit fetch operations: the pinned Cargo editor and lock generator run in an observed private mirror with the same registry/CA policy as capture. They never run application build scripts, proc macros or a compiler build. Select an exact package version; a local package must declare that same name/version. Then capture and review the exact candidate before the existing build/package/admission flow:

```powershell
python tools/rust_capsule.py add ./my-rust unicode-normalization --version 0.1.24 --cargo ./reviewed-rust/bin/cargo
python tools/rust_capsule.py add ./my-rust my-library --version 1.0.0 --path ../my-library --cargo ./reviewed-rust/bin/cargo
python tools/rust_capsule.py lock ./my-rust --cargo ./reviewed-rust/bin/cargo
python tools/rust_capsule.py resolve ./my-rust --candidate ./cargo-candidate.json --features pure
$candidateDigest = 'sha256:' + (Get-FileHash ./cargo-candidate.json -Algorithm SHA256).Hash.ToLower()
python tools/rust_capsule.py review-lock ./my-rust --candidate ./cargo-candidate.json --expect $candidateDigest
python tools/rust_capsule.py dependencies ./my-rust
python tools/rust_capsule.py build ./my-rust --offline --output ./my-rust/target/build-1 --repository https://github.com/example/application
```

The separate fetch stage runs native `cargo metadata` and `cargo vendor --locked` from an owned working directory and empty Cargo home. It records the complete resolver graph, selected target graph, enabled/default features, native lock, package/source/target/license metadata and tool bytes in `cargo-resolved.lock.json`. Private registry tokens are read only by this explicit resolver and are absent from compilation environments and public evidence. Private registry endpoint configuration must be explicitly supplied to the resolver; ambient home/project Cargo configurations are not consumed.

Authoring supports an explicit dependency section, target, features, optional/default-feature selection and declared registry alias. Native Cargo preserves the manifest syntax; this wrapper supplies no alternative dependency resolver. It observes direct/transitive local path inputs before Cargo runs and maps them into the private mirror, including quoted `path` keys. Original replacement semantics are restored in the published manifest. Project Cargo configurations and uncaptured external workspace pointers fail before native dispatch. SDK workspace inheritance and maintained dependencies cannot be edited. Cargo/rustc, recipe, source, local resources, registry/CA inputs and the accepted capture are rechecked before publication. A partial publication restores only the wrapper's own exact bytes, preserving a concurrent user edit.

`add`, `update`, `remove` and `lock` preserve the previous accepted application capture. A changed declaration/lock invalidates that capture until another resolve and exact review. After editing, repeat the capture/review sequence; frontend `test` and `watch` verify the accepted bytes and retain explicit recipe trust. Apply the same `--registry-config` to authoring and resolution for a private registry. Adding build dependencies still requires separate executable-tool approval at compilation.

The pinned Cargo `remove` command also prunes unused workspace dependencies.
Authoring retains the original immutable SDK workspace sections when Cargo
only deletes unchanged entries. It verifies the complete restored TOML meaning
before publication and still rejects new or modified workspace entries, SDK
settings and unrelated semantic changes. Ambiguous layouts fail closed.

Supply private endpoint configuration outside the project with `--registry-config`.
Select credentials separately through a declared alias's environment slot, such as
`CARGO_REGISTRIES_TEAM_TOKEN`. For a private certificate authority, the same
configuration can explicitly select an application-relative public PEM bundle:

```json
{
  "registries": {
    "team": {"index": "sparse+https://packages.example.test/cargo/"}
  },
  "tlsTrust": {"caFile": "registry-trust/public-roots.pem"}
}
```

The optional bundle contains only public certificates, at most 256 certificates
and 2 MiB. Include all roots needed by the selected registries, including public
registry roots if the selected graph uses them. It becomes an independently
verified native lock input. The resolver uses an owned copy with TLS verification
enabled, rechecks both copies, and records their original digest and policy. It
does not change machine trust or inherit ambient Cargo TLS overrides. Changed
certificate bytes require another explicit resolution and lock review. This
trust input approves no runtime effect and provides no registry token to a guest.
The native graph retains public registry-alias/index mappings so ordinary
`registry = "team"` declarations still resolve against their captured vendor
sources offline. Build configuration contains those mappings and enforced
offline selection, without registry credentials or TLS acquisition policy.

The [private Cargo programme](../testing/rust-private-dependency-ingestion.md)
uses an actual authenticated HTTPS sparse registry, original archives and an
offline signed-node build. Its source and hosted receipts retain their own
qualification boundary; adding the programme does not assert a successful run.

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

The required Rust authoring CI selects `unicode-normalization` and a developer-owned external crate independently through normal add/lock/capture/review. Update/remove must reject the stale accepted capture; restoration of its exact reviewed native inputs must verify again. The application calls both ordinary APIs directly, and the retained fixture receipt requires both native root edges in the complete and selected-target Cargo graphs. The captured closure includes the native `tinyvec`/`tinyvec_macros` transitive graph and immutable UTF-8 bytes. The fixture exercises a root build script and external procedural macro, retains the unapproved denial, then authorizes only that SDK-owned fixture's exact request, removes the original external sources, compiles offline, signs and admits the resulting component, and runs the normal node workflow. Both executable controls assert that ambient files, credentials and network access are unavailable. These are qualification fixtures and never select application behavior. The updated programme requires its own current-head passing receipt; earlier actual pure/generator proof is retained without being relabelled. Additional panic/unwind, async/thread/network profiles and the complete feature/denial matrix keep their separate evidence requirements.

The dependency greeting fixture uses a five-second wall limit in both its signed capsule and deployment, matching the experiment node's existing maximum. Run `36786586820` exhausted the earlier one-second ceiling during cold preparation at 1,001,448 microseconds, with zero guest fuel and memory recorded; this establishes a lower bound, not a successful cold timing. Subsequent receipts retain cold and warm invocation times and the fixture's original and selected ceilings. Ordinary project defaults and the separate 100 ms deadline/cancellation controls retain their existing limits.

When captured application build scripts or proc macros are present, the first
build retains `executable-input-approval-request.json` and fails before executing
them. Review its exact source, recipe, compiler distribution, executable graph and
namespace specification, then pass its `identity` with `--executable-approval` on
the standalone build. For the packaged frontend, add the same flag and identity
to the maintained Rust adapter's `build.argv` in `latent.project.json`, then run
the existing `dev trust` and `dev build` commands. The changed argv changes recipe
trust and cache identity; the compiler independently recalculates the request and
rejects a stale or mismatched identity. Approval is not inherited from capture,
package names, a previous source snapshot or ordinary recipe trust. Unsupported
frontend adapters reject this flag before any build execution.

The maintained captured-library qualification exercises its external crate's
ordinary panic-abort, allocation and computation paths in a signed component.
Normal calls check `Drop`, exact UTF-8 and binary included resources, and fresh
static state. Each observed panic, memory/fuel limit or running cancellation
must retire its owners before a fresh successful call. This finite programme
keeps the original runtime budgets and does not claim panic unwinding or
unqualified standard thread/I/O support. Its hosted result, rather than source
controls alone, establishes execution for the recorded inputs.

The cancellation-only loop requests zero additional Wasm memory pages through
stable `memory_grow::<0>`, with both its zero operand and result passed through
`black_box`. It adds no pages, capability or compiler feature flag. In the
pinned Wasmtime 48.0.6, bulk copying is charged per byte; the earlier copy loop
exhausted its original fuel before the running-state observer could cancel it.
The replacement retains the original fuel, memory, wall-clock, observation and
single-cancellation bounds. Current hosted evidence must still show an actually
running activation, an accepted cancellation, its cancelled terminal result,
retired ownership and a fresh successful call. Source controls do not qualify
that execution.

If actual core-module compilation succeeds but component assembly rejects it,
the Rust builder retains at most 64 MiB of the original core with its source
and byte digests. Supplementary retention cannot replace the original failure.
The captured-library qualification selects a reachable external native symbol
and requires its exact import in the pinned tool's original-core inspection
before attributing that selected path as target-incompatible. It keeps the
original generic compatibility report and does not infer a package-wide ban,
a native implementation, or elimination of untested paths.

The delivered-tool watch programme selects an outside local crate with a
transitive crate and immutable resource through native Cargo add/lock/resolve
and exact review. It requires three independently consented signed test
workspaces: the initial value, an updated transitive value, then dependency
removal. Before each replacement, unreviewed lock inputs, changed recipe trust
and a previous build's signing consent must stop deployment. Every watcher
must finish through normal `down` with a reaped, clean node. Explicit Cargo
fetch may contact its registries; the ordinary captured compiler retains its
network-denied namespace. The programme exports only bounded public results.
Its source is not an executed qualification receipt, and later final-source CI
must preserve the other language gates in the shared developer-tools job.
