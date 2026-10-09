# PR 790 duplicate-command reconciliation

[PR #790](https://github.com/KirilsTurkins/latent-service-fabric/pull/790) contributes
bounded command notification, duplicate admission and result recovery to
[#387](https://github.com/KirilsTurkins/latent-service-fabric/issues/387).
The existing `9977333b` head had 51 successful hosted checks. Its normal merge
with development `2c817bbf` includes #787's complete command envelopes, #797's
original shared store capacity, #775's stream owners and #784's current guest
authoring. Those historical checks do not qualify the reconciled source.

## Preserved work and conflict decisions

The [cleanup draft #850](https://github.com/KirilsTurkins/latent-service-fabric/pull/850)
and [Portable handoff #978](https://github.com/KirilsTurkins/latent-service-fabric/pull/978)
identify the original code and qualification checkpoints. The deduplication
checkpoint `6dbbf49f` in
[#853](https://github.com/KirilsTurkins/latent-service-fabric/pull/853), waiter
checkpoint `7ccc3291` and ownership checkpoint `9ba17e05` are already ancestors
of the published PR head. Their implementation is retained; the old interrupted
merge is not reapplied. The separate #959 integration handoff records installed
workflow qualification and keeps its historical receipts at their original heads.

The source merge preserves bounded waiter slots, original attempt and fingerprint
identity, current result-read authorization, prepaid ingress reservations, retained
response ownership, retry associations and the conservative storage/recovery
checks. Development's physical cancellation/commit fences and all original tests
remain. The bounded storage getter shares the existing deterministic age-check
path, retaining both size refusal before copying and the original snapshot expiry
boundary. A merge mismatch in the atomic test seed is corrected without changing
its namespace setup or effect authority.

CI fragments are reconciled through semantic comparison and a lossless case/guard
union. Every original case, ignore, platform predicate, recipe and resource limit
is retained. Development's current compiler-download fingerprint remains enforced;
the additional Rust guest execution job and result-boundary variant are preserved.
One new unignored factory case is registered in exact discovery.

## Binding regression and actual guest checks

The first fresh 23-case guest campaign failed before execution: the merged linker
registered the same scoped transaction imports twice. The linker now installs
them once, after the optional activation-runtime bindings. Transaction support
still requires the explicit configuration flag and invocation authority.

The new supervised factory test initializes both ordinary and transactional
configurations, checks that initialization creates no guest Store/host state or
active invocation, and verifies original worker retirement. It runs in the normal
library suite rather than only in the explicit guest campaign.

All three maintained Rust variants compile with the pinned tools, reproducible
bindings and exact component surface checks. The reconciled components are:

| Variant | Component SHA-256 |
| --- | --- |
| Aggregate | `1be7c58d51a1b8400e5a348f2ee5dd8de13463e2cdba6cc425a543c28e74d5c3` |
| Forbidden HTTP | `44ffed921e3f5a82e99cb2754a403f25afc99f06b606a4deb01c1b67ec60b7cb` |
| Result boundary | `8760add5c91207a7905c6463bf2a982d2cff0ad3b167fe5ae863fc8a26da0e15` |

The original 23 explicit real-component RPC/manager scenarios now pass. Their
actual guest execution/Store counts, commits, result bodies and effect identities
remain the oracles. Coverage includes duplicate/conflicting input, dropped waiters,
lost and rejected responses, current caller/token rotation/revocation, shared and
delegated scopes, compatible rollout, namespace recreation, pending/committed
restart and process loss, retention pressure/expiry, maximum/oversized results,
confirmed-abort retries and preserved attempt history. Fresh cleanup observations
retain their original assertions. The trusted-local component catalog is explicit;
this is not a signed-package or full installed standalone qualification claim.

## Validation and delivery boundary

The ten selected native library suites pass 1,935 cases on pinned Rust 1.97.1
Linux with ext4 scratch storage. Exact discovery matches the unioned case and
ignore sets; all 59 original ignores remain. The full Wasmtime library adds
352 passes with two original ignores and exact 354-case discovery, including
the new factory regression. A relative
catalog-root fixture initially hit the read-only source mount; its unchanged test
passes from owned ext4 scratch. Failed attempts remain in local evidence.

All 104 focused schema, transaction, authoring, compiler, workflow and diagnostic
tests pass on Python 3.13.5 Linux without skips. Windows retains its seven original
platform skips. Ordinary selected Clippy and the repository's four-package
warnings-as-errors gate pass. The exploratory stricter node lint run retains
existing warnings; no lint policy or execution guard is weakened. Formatting,
repository/docs validation and read-only CI coverage pass. Coverage preserves
88 baseline and 274 current required run blocks and 144 delegated script owners.

The PR closes no issue. Full signed admission and installed standalone new-boot,
restore and distribution workflows still require their own current-source
qualification. Current hosted CI is required and is not awaited for publication.
