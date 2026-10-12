# PR 784 guest authoring reconciliation

[PR #784](https://github.com/KirilsTurkins/latent-service-fabric/pull/784) contributes
the common six-language authoring work to
[#389](https://github.com/KirilsTurkins/latent-service-fabric/issues/389).
[#718](https://github.com/KirilsTurkins/latent-service-fabric/issues/718) owns the
Java guest execution and HTTP/recovery qualification slice. Both issues remain
open: authoring and compiler checks do not complete signed stateful guest workflows.

## Source and checkpoint decisions

The published `b43ab914` source is reconciled through a normal merge with
development `be4a8f2d`, including the completed #775 stream work. Every development
suite, case and execution guard is retained. The additional original CLI recovery
case raises its exact discovery floor from 155 to 156. Conflicting workflow and
Python contract fragments have identical semantics apart from review text; the
compiler-download owner now retains development's actual reviewed fingerprint.
Suite serialization and all other discovery expectations stay intact.

The [cleanup draft #850](https://github.com/KirilsTurkins/latent-service-fabric/pull/850)
and [Portable handoff #978](https://github.com/KirilsTurkins/latent-service-fabric/pull/978)
identify the original source, continuation checkpoints and historical checks.
The Rust ownership and guest-profile checkpoints `faeb66f7` and `7758fcd0` already
match the maintained ownership files; their feature selections are present in
the current source. No duplicate implementation is imported from those snapshots.

[Integration handoff #959](https://github.com/KirilsTurkins/latent-service-fabric/pull/959)
and [collector draft #879](https://github.com/KirilsTurkins/latent-service-fabric/pull/879)
record a separate installed query preparation failure. The collector and runtime
integration remain with #823/#828; their failed signed-node attempt is not promoted
to guest acceptance here. The #851 manifest checkpoint and #932/#915/#920 SDK
profile candidates retain their separate scopes and qualification boundaries.
Historical receipts and preserved source branches are unchanged.

## Resulting behavior

All six authored forbidden-HTTP variants stage the aggregate write and intent
before making their actual SDK HTTP call. Only the exact typed `permission-denied`
error produces the declared business rejection. An HTTP success or another error
traps. The captured profile, companion, original state/view/key-version identities,
zero HTTP budget and owned resource cleanup remain enforced.

The C variant is repaired for the current affine frame template. It uses the
current three-argument aggregate return and inserts the HTTP phase after the
original intent subtask retires. It preserves original command/query/scan logic
and releases a returned HTTP response during cancellation cleanup. Its generator
continues to refuse source drift instead of silently creating a different fixture.

The CLI accepts the empty or fully pruned original trigger-operation journal's
floor one past its high watermark, with saturating full-width arithmetic. It
preserves receipt scope, disposition/currentness checks, decimal counters and
`executionPermission=false`. The real RPC regression rejects malformed floors
and contradictory receipts, covers the maximum unsigned counter, and forbids
mutation, selector changes or scanning during recovery.

The retained website timeout diagnostic reports the selected command and existing
budget before terminating its original process group; budgets are unchanged.

## Validation and remaining acceptance

The reconciled code passes exact Linux CLI discovery and all 156 CLI library
tests without ignores, formatting, and all-target/all-feature CLI Clippy with
warnings as errors. All 52 focused transaction contract, authoring, compiler
receipt, workflow, ownership and Go capture tests pass without skips on Windows
and Python 3.13.5 Linux. Repository and documentation validation pass.
Read-only CI coverage preserves 88 baseline and 273 current required run blocks
and 144 delegated owners. The website wrapper passes the pinned Node 24.19.0
syntax check.

Both current C projects compile with pinned Zig 0.16.0, wit-bindgen 0.62.0 and
wasm-tools 1.254.0. Generated binding comparison, exact component surface checks
and component validation pass. The aggregate component is
`sha256:e0e558333fcc844146a1f39d62225e196bc9717c5edded1ebd8c7f3d5f9de665`;
the forbidden-HTTP component is
`sha256:9f4b763cc4d03464f5e28160a168e429717597feb4c73e76b8b1b52d00f941b2`.
These local compiler receipts capture the reconciled working source and explicitly
leave signing, node execution and admission rejection unqualified. The initial
container Git-path setup failure is retained separately from the successful build.

The maintained six compiler workflows remain required. Full signed six-language
transaction/query/intent execution, rollback, provider call counters, committed
response loss and recovery, failure cleanup, and installed Java HTTP/recovery
scenarios still require their runtime and qualification owners. This PR closes
no issue, confers no new authority and does not wait for hosted CI.
