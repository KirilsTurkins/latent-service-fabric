# PR #791 transaction startup reconciliation

## Scope and delivered source

PR #791 belongs to [#388](https://github.com/KirilsTurkins/latent-service-fabric/issues/388):
host-owned transaction admission, execution, commit/cancellation and physical
retirement through the shared runtime. #811 owns a related completion/replay
slice; #389 and #718 own the actual guest language integrations. Full #388
acceptance remains open, and this PR closes no issue.

The original PR head is `a129773f52c4fc15c59b4ce62b52744a233cd4cd`. Its hosted
snapshot has 47 successful checks, two failed checks and their failed aggregate,
plus one skipped check. Both native failures are the same catalog cases:
`selected_transaction_import_keeps_the_ordinary_signed_clock_plan` and
`selected_transaction_binding_restart_uses_original_profile_and_current_provider`.
They fail with `binding-denied` during fixture installation.

Development `802bb8e58c7cbbbe4b6aa269792fa7e43ca31b64`, delivered through #790,
already contains the canonical startup and original transaction-owner work,
including the Core memory-owner restoration, later waiter/recovery fixes and
ordinary binding preservation. A normal merge resolves the old branch against
that delivered source. Before the diagnostic follow-up, the entire merged tree
is byte-identical to development. Existing code, tests, ignore lists, source
contracts, resource limits and protected compiler profiles are retained.

The catalog compiler already separates checked native state/intent imports from
ordinary capability definitions for a selected transactional profile. Native
namespace authorization still belongs to transaction admission; the ordinary
clock plan retains its signed definition, grant and current provider checks.
That delivered repair addresses the two old failures without granting state
authority through an ordinary capability binding.

## Snapshot review and useful follow-up

The [central cleanup #850](https://github.com/KirilsTurkins/latent-service-fabric/pull/850),
[integration #959](https://github.com/KirilsTurkins/latent-service-fabric/pull/959)
and [Portable #978](https://github.com/KirilsTurkins/latent-service-fabric/pull/978)
handoffs preserve source and evidence from the stopped work. The Core owner
checkpoint `ebaf5292`, startup/currentness checkpoint `f470e917` and AOT floor
checkpoint `be1d669f` are ancestors of the original PR head. No duplicate
implementation is applied from them. The integration collector and remaining
installed acceptance proofs retain their separate ownership and source heads.

The archived Go-preparation diagnostic checkpoint
`cde3ab8ed99aa4cb62c071b66263d83d870a7afa` is not an ancestor. Its two parent
test helper files are byte-identical to development, and all seven referenced
error constructors remain present. The exact small follow-up is adopted:
the private test recorder distinguishes complete known, nonretryable
`ResourceExhausted` preparation/cache/metadata/lifecycle error shapes.
Wrong codes, retryability, extended messages and unexpected details remain
unclassified. The original error is forwarded once without cloning its message
or retaining arbitrary diagnostic text.

The new regression is registered as the ninth local-service diagnostic case.
All eight original cases, their execution guards and resource bounds remain.
The archived queued Go failure is still a failed qualification attempt; this
observation change does not identify its cause or establish successful guest
execution, an installed profile or a new business permission.

## Delivery boundary

Pinned Rust 1.97.1 Linux validation passes 844 cases across the Core, Activation,
Node, ControlStore and latentd libraries with all features enabled. Their 28
original ignores remain. Both previously failing catalog cases pass, including
restart and current provider checks. All 67 activation lifecycle cases and all
nine diagnostic cases pass without ignores, for 920 native passes in total.
The 47 profile/inventory/discovery/result and migration tests pass on pinned
Python 3.13.5 Linux without skips. Coverage preserves 88 baseline and 274 current
required run blocks with 145 delegated owners. Formatting, repository/foundation
and documentation validation pass.

The scoped ordinary Clippy gate passes. An exploratory warnings-as-errors run
for Wasmtime encounters inherited library warnings; its failed log is retained,
and no lint suppression or policy change is added. Historical evidence stays
attributed to its actual head. Full
installed direct/RPC/HTTP command/query/recovery, physical commit/cancellation
barriers, crash/restart and the actual six-language matrix remain requirements
for #388 and its coordinated children. Hosted CI is required after publication
and is not awaited for this commit/push delivery.

## CI parser vocabulary follow-up

The `60aebeea` hosted run failed both the Python contract lane and the Phase 3
qualification lane at their shared closed-vocabulary parity test. The adopted
Rust recorder contained seven additional reasons while the Python receipt
extractor still listed the old vocabulary. Its explicit allowlist now includes
exactly those seven enum/token pairs, in producer order. The strict parity test,
unknown/malformed-input refusal and original 1 MiB capture, 32 native record and
eight receipt-entry bounds are unchanged. All 51 security parser tests pass on
pinned Python 3.13.5 Linux without skips; reviewed CI coverage also passes.
The complete 3,670-case Python rerun passes with an unprivileged Linux user:
3,652 passes and 18 existing platform/environment skips. No test body, execution
guard, capture grammar or record limit changes. New hosted CI is not awaited.
