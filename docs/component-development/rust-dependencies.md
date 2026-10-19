# Captured Cargo dependencies

Edit the ordinary application `Cargo.toml` and generate/review its native `Cargo.lock` independently of `sdk-lock.json`. Public registry, exact git revisions and outside-project path crates use Cargo's resolver. Package names identify provenance and do not require LSF catalogue entries. Keep the SDK workspace inheritance and maintained guest/WIT dependency declarations pinned.

Captured path relocation follows parsed Cargo dependency fields: ordinary,
development, build, workspace and target-specific dependencies, plus patch and
replace entries. Table, inline and dotted declarations retain their original
syntax; only selected path string values change. Comments, quoted examples,
package metadata and source-file paths remain byte-identical. External crate
paths must still belong to the native resolver's selected graph. This does not
copy or authorize unrelated paths mentioned by the manifest.

The relocation pass uses the existing original/transformed artifact identities
and tool receipt. It reads at most 1 MiB of manifest bytes and, when dependency
paths require inspection, at most 131,072 tokens with nesting depth 32. Invalid
TOML, unrepresentable paths, unsupported or ambiguous syntax, and exhausted
inspection bounds fail with closed diagnostics. They do not produce a partial
transformation or a compatibility verdict. No dependency initializer, Cargo
build, process or network request runs during this syntax inspection.

Use normal native `add`, `update`, `remove` and `lock` stages for application declarations. These are explicit fetch operations: the pinned Cargo editor and resolver run in an observed private mirror with the same registry/CA policy as capture. Native `cargo metadata --format-version 1` resolves changed declarations against the existing lock, retaining compatible selections instead of refreshing every unrelated SDK/compiler dependency. It also creates a missing lock. Necessary dependency changes still require capture and review; executable inputs still require their separate exact approval. These operations never run application build scripts, proc macros or a compiler build. Select an exact package version; a local package must declare that same name/version. Then capture and review the exact candidate before the existing build/package/admission flow:

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

Before vendoring or publishing a candidate, capture checks both native metadata
documents for unique package/node IDs, closed edges and bounded feature lists.
The filtered graph must share the actual application root and unchanged common
package records with the full graph. The pinned native filter may omit target-only
packages from its package list. Its enabled features, renamed edges and observed
dependency kinds/target expressions must occur in that full graph. Target
expressions are retained as Cargo observations; the capture tool does not evaluate
them or resolve features itself. Validation preserves the input records, including
unknown fields, and the existing stored graph projection and metadata digests.
The field shapes follow the [Cargo metadata format](https://doc.rust-lang.org/cargo/commands/cargo-metadata.html#output-format).

Duplicate JSON fields, malformed/foreign/duplicate graph observations and
inconsistent filtered selections fail with closed `cargo-native-*` or
`cargo-selected-graph-*` diagnostics. Each native JSON document has a 16 MiB cap;
graphs permit at most 1,024 package/node rows, 1,024 items in each feature/edge/kind
list and 65,536 aggregate observed feature/edge/kind items. These are source-capture
admission controls. They do not establish which host/target feature instances a
compiler actually built, executable-tool containment, reproducibility or signed
component compatibility; those require their own evidence.

Authoring supports an explicit dependency section, target, features, optional/default-feature selection and declared registry alias. Native Cargo preserves the manifest syntax; this wrapper supplies no alternative dependency resolver. It observes direct/transitive local path inputs before Cargo runs and maps them into the private mirror, including quoted `path` keys. Original replacement semantics are restored in the published manifest. Project Cargo configurations and uncaptured external workspace pointers fail before native dispatch. SDK workspace inheritance and maintained dependencies cannot be edited. Cargo/rustc, recipe, source, local resources, registry/CA inputs and the accepted capture are rechecked before publication. A partial publication restores only the wrapper's own exact bytes, preserving a concurrent user edit.

`add`, `update`, `remove` and `lock` preserve the previous accepted application capture. A changed declaration/lock invalidates that capture until another resolve and exact review. After editing, repeat the capture/review sequence; frontend `test` and `watch` verify the accepted bytes and retain explicit recipe trust. Apply the same `--registry-config` to authoring and resolution for a private registry. Adding build dependencies still requires separate executable-tool approval at compilation.

For an explicit HTTPS Git source, normal `add` and `update` accept `--git` and
`--rev` alongside the required exact package `--version`. Select a full lowercase
40-hex commit, independently of the package version:

```powershell
python tools/rust_capsule.py add ./my-rust ordinary-library --version 1.2.3 --git https://example.org/developer/library.git --rev 1111111111111111111111111111111111111111 --cargo ./reviewed-rust/bin/cargo
```

Use the actual reviewed URL and commit. The Git selector excludes `--path` and
`--registry`; credentials, queries, fragments and moving/abbreviated references
are refused before native work. Cargo receives its ordinary Git arguments rather
than a registry version selector. Before publication, the wrapper checks the
direct native package's exact version, Git URL and revision against the request,
its resulting declaration and its native lock entry. Existing source/tool/policy
rechecks and transaction rollback still apply. An existing manifest version
constraint must also equal the requested version. Repeat capture and exact review
after a revision update; authoring does not certify signed component execution,
private Git authentication or catalogue-removal qualification.

The Rust workflow also has a separate, bounded Git source campaign:

```powershell
python tools/qualify_rust_git_dependencies.py --cargo ./reviewed-rust/bin/cargo --output ./target/git-closure
```

It uses the normal project creator and authoring/capture/review functions for
the published `unicode-xid` 0.2.5 and 0.2.6 release commits. The selected crate is
absent from the initial SDK lock and needs no catalogue registration. A revision
update must reject the old accepted closure without replacing its bytes; the new
candidate requires an exact digest review. Each phase then materializes verified
objects into a fresh source directory and Cargo home, runs only locked offline
native metadata, and rejects Git/registry source-cache payloads. Empty directories
and Cargo's exact bounded `CACHEDIR.TAG` bookkeeping file are permitted; a tag
does not establish a cached package. Receipts bind the actual
lock, graph, candidate, object tree, Cargo/rustc and owning source identities.
The two existing signed Rust jobs keep their original commands and deadlines.
This campaign establishes source/offline observations when it passes; it does
not compile an application, run build hooks, invoke a signed component, remove
catalogue data or claim a hermetic build host.

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
the standalone build. A matching current frontend/helper also supports a detached
selection on `dev build`, `dev up --watch` and `rust_capsule.py watch`. Keep the
descriptor's `build.argv`, source and SDK locks unchanged: the descriptor is itself
part of the request's source identity, so inserting an approval into it makes that
approval stale.

After an ordinary maintained Rust build refuses executable inputs and its owner
has confirmed reaping, explicitly inspect the last owned failed attempt:

```powershell
$failedRequest = latent-dev --state-root $StateRoot dev executable-approval-request --workspace $Workspace | ConvertFrom-Json
# Review the full private specification before choosing to authorize it.
$executableApproval = $failedRequest.result.request.identity
latent-dev --state-root $StateRoot dev build --workspace $Workspace --project $Project --executable-approval $executableApproval
```

This read-only operation accepts no path or attempt selector. It verifies the
current source snapshot, trusted maintained recipe, failed/reaped owner, captured
executable graph, producer source/recipe inventories and compiler receipt. Missing,
unsafe, stale or oversized retained inputs refuse observation. The full request
contains private dependency metadata; it is returned only by this explicit
command, never by ordinary status or public qualification diagnostics. The command
does not grant approval or modify the project. A reaped attempt retained across a
guest reboot remains inspectable only in the same owned workspace with the exact
current saved source and recipe trust. Running, uncertain or foreign ownership
refuses this read-only view; inspecting history does not authorize its execution.
The operation requires matching current frontend, helper and Rust tool bundle:
the helper must expose the `executable-approval-request` protocol feature, and the
retained producer inventory must contain the current exact Rust recipe name set
and pinned bytes. Older helpers fail negotiation; older or different compiler
inventories refuse observation without fallback.

The detached digest is bound into the build cache and successful receipt only
when explicitly selected. An absent or different selection cannot reuse that
approved entry; default cache identities remain unchanged. The actual compiler
recalculates its input, recipe, compiler and containment request on execution and
rejects a stale or mismatched digest. Watch carries only the selected identity:
a source or bound-tool change refuses the build and retains the prior deployment,
without automatic reapproval, promotion or mutation replay. Stop watch, review the
new failed request and explicitly choose another identity before restarting it.
Approval is not inherited from capture, package names, a prior source snapshot,
test-fixture consent or ordinary recipe trust. Other languages, custom recipes,
duplicate options and malformed digests reject this selection before dispatch.
The detached route's source controls do not establish a successful current hosted
watch or identify the unretained executable package in an earlier refusal.

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
declared as an explicit wasm32 `env` import, without supplying an implementation
or changing production linker flags. The observed reachable bare declaration
failed at `rust-lld`; that earlier compiler failure cannot satisfy this component-stage
control. The programme requires its exact import in the pinned tool's original-core inspection
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
fetch may contact its registries. The exact owned crate revision is restored
while native update/removal loads its manifests; its original directories are
deleted again before every captured compilation. The ordinary captured compiler
retains its network-denied namespace. The programme exports only bounded public results.
Each command uses the smaller of its existing deadline and the remaining
2,400-second programme budget. The separate 2,450-second process ceiling remains
unchanged. Atomic checkpoints retain elapsed milliseconds and the last eight
completed command timings under hashed labels; the final public report retains
the completed timing list. A timeout is still a failed qualification. These
observations distinguish work already completed from the active phase; they do
not by themselves establish a deadlock, capacity cause or clean shutdown.
During a watched build, source observation waits at least half a second after
the preceding observation and any cancellation request complete. A slow captured
snapshot therefore cannot trigger another full scan on the next transport poll.
Unusable or changed source still supersedes only the current build identity;
an unaccepted cancellation can be retried after the same gap. The final complete
source check before returning the build and before deployment remains mandatory.
This removes redundant polling work without extending the watch deadline or
establishing that the complete three-stage qualification fits its budget.
Its source is not an executed qualification receipt, and later final-source CI
must preserve the other language gates in the shared developer-tools job.

The separate `git-components` Rust workflow job consumes only the same run's
identity-checked public native binaries and observed companion signer inputs.
Its exporter excludes compiler caches, original source directories and signing
keys. Every original signed authoring stage and its 35-minute bound remains;
the additional Git job has its own 20-minute bound and does not rebuild the
native workspace.

The Git fixture uses ordinary `unicode-xid` 0.2.6 APIs from upstream commit
`5d50587f19713cd35f1f48e5d4d011aa9c54dbff`, through normal Cargo add, capture
and exact review. An outside-project crate includes UTF-8 and binary resources
and is removed after review. Fresh-home locked-offline metadata must confirm
the same Git identity before two ordinary isolated offline component builds.
The existing strict demo signer and enforced node then check observable results,
admission denials and physical cleanup under their original limits. No build
script or proc macro is approved by this fixture; unexpected executable inputs
stop before review.

The Git selection adds three signed calls after every original tutorial check.
The external crate's ordinary APIs classify dynamic request characters, and the
outside library returns distinct start/continuation counts with its captured
UTF-8 and binary resource values. Two different inputs and a fresh warm repeat
must return their exact distinct payloads; the original greeting cannot satisfy
this gate. Actual quiescent ownership sampling follows every added call. This
test-runner selector is Rust-only, defaults off and changes no ordinary template,
runtime grant or invocation ceiling.

Source controls alone do not establish that this job passed. Its retained
component, source, graph, tool and node receipts define any actual qualification.
This finite pure Git case does not claim private Git support, catalogue removal,
complete host hermeticity, reproducible components, Rust thread/I/O compatibility
or successful dependency watch. Those acceptance items retain separate evidence.
