# On-demand post-Store retirement receipt

## Reproduced regression

Ownership CI run `43309461555` at `12aa36d6` failed seven unchanged
`local_service` lifecycle tests. Signed Go run `43309461902` also refused the
fresh activation after its first deliberately unsettled-root scenario with
`all-cells-quarantined`.

The original logical-finalization veto was correctly independent of guest trap
text, but it never accepted a later physical destruction receipt. A trapped or
cancelled guest cannot run its own settlement callbacks. On the Linux on-demand
backend, destroying its Store nevertheless synchronously retires its mappings
before the original host owner table is destroyed.

## Implementation

The logical result is preserved. A lifecycle failure remains a failure; it is
not changed into guest success or inferred from a diagnostic string. A separate
one-shot physical receipt is available only when all these facts hold:

- The actual engine uses the Linux on-demand allocator selected by this backend,
  not pooled allocation. The backend has no custom linear-memory creator. In
  the pinned Linux allocator, failed `munmap` panics; the patched `into_data`
  retains host owners on such a panic and cannot publish a completed witness.
- The invoking call reached its explicit finalization boundary and canonical
  lifting did not fail. Setup failures and externally abandoned futures have no
  receipt, even when their destructors subsequently run.
- The actual consuming Store teardown completed, followed by destruction of
  HostState and its original owner table. The same original ActivationRuntime
  is retained via an Arc clone; there is no new allocation, reservation, token
  replacement, parallel accounting ledger, or retry worker.
- Native-stack and capability cleanup observers have run. The original runtime
  then retires successfully with no live original owner. Its receipt is consumed
  once: later owner release cannot repair an already-refused disposition.

Earlier capability or native-stack quarantine reasons remain authoritative.
A second Store cannot inherit any earlier receipt. Host-result disposition,
trap/cancellation/deadline outcome, and accounting are preserved unchanged.
The original logical refusal is still recorded even when physical retirement
subsequently proves that this on-demand cell is safe to reuse.

## Executed local evidence

On retained ownership sources with the published source delta applied, the
unchanged runtime selection reproduced seven failures before the fix and passed
all 18 enabled cases after it. The whole `local_service` test target then passed
62 enabled tests, with its existing 37 optional signed-fixture cases ignored.
These ignored cases are not passes and no assertion was relaxed.

All 12 Store-lifecycle tests passed, including the existing custody and panic
controls plus new actual-engine checks for synchronous versus pooled allocation,
live external original ownership, setup/abandonment and incomplete lifting,
prior quarantine, repeated Store entry, and an actual backing-destructor panic.
All 16 source-integrity controls passed. Counts describe observations, not a
fixed required inventory. A fresh exact-head CI run remains required.

```sh
cargo test --locked -p latent-wasmtime --lib backend::store
cargo test --locked -p latent-wasmtime --test local_service
python -m unittest tools.tests.test_host_codec_wasmtime -v
```

## Boundaries

This does not claim pooled per-Store decommit acknowledgement, complete retained
HostState quarantine for pools, non-Linux mapping-reset guarantees, comprehensive
byte accounting, or signed SpiderMonkey/GC qualification. The pending pooled
custody requirements in `typescript-pooled-decommit-custody.md` are unchanged.
No budget, grant, deadline, fixture assertion, ignored-test policy, or supported
runtime profile is expanded.
