# Pooled decommit refusal: backing and allocation-guard custody

## Scope

This continuation belongs to #1931, targeting `feat/typescript-runtime-745` for
#1852. It changes the vendored Wasmtime pool's handling of a failed operating
system decommit. It does **not** complete #745 or establish whole-activation
physical retirement.

The source preimages are from ownership head
`b1d535399b40d6a1389693652ccb855521fec5fa`; subsequent head
`143fbc7f570986bd5f02967d32f20a7d5741daa3` only adds the temporary dependency
capture used to reproduce the source. This patch removes that completed
temporary capture workflow. Existing budgets, grants, dependency pins and slot capacities are
unchanged.

## Implemented behavior

Previously the queue consumed a failed decommit batch, returned its memory,
table and stack slots, and dropped the tables' original allocation guards.
The table zeroing fallback did not establish an operating-system decommit.

A failed call now leaves the entire batch intact: original raw ranges,
`MemoryImageSlot` values, tables and their allocation guards, and native stacks.
Partial syscall success also retains the complete batch; a retry decommits the
same still-unused mappings. Slots reach their free lists only after every range
in that batch has been acknowledged. Successful retirement releases the actual
original allocation guard once, without a replacement reservation.

Immediate-flush failures transfer the same entities into the existing sharded
queue. Entries occupy their original finite pool slots, so repeated failures
cannot admit additional entries beyond those slots. Allocation pressure retries
these shards. The operating-system operation holds the shard lock, but owner
destructors and free-list release run after unlocking. No second failure ledger
or asynchronous retry worker is introduced.

Pool destruction attempts the final drain even without debug assertions. A
permanent final refusal retains that pool's queues, mappings and allocation
guards until process termination. This terminal retention is deliberate, not a
successful cleanup or a leak-free result. Fallible constructor stages remain
ordinary RAII locals until all sub-pools have been built.

The compiled `DYNAMIC_VALUE_MEMORY_COHORT` is aligned with the authenticated
source manifest and advances to the `retained-pool-decommit-v39` suffix. The
previous compiled value was historical v10 while the manifest had reached v38.
Prepared/AOT configuration identity must not certify this source as that older
engine.

## Executed evidence

The tests compile the actual vendored engine and instantiate real pooled
memory, tables, allocation callbacks and native stacks on Linux. Failure
injection is confined to the decommit syscall boundary. They do not substitute
an accounting model for the engine.

| Executed selection | Observed result |
| --- | --- |
| New decommit regression selection | 8 passed |
| Same regressions with debug assertions disabled | 8 passed |
| Complete pooling selection with async/component/GC features | 31 passed; no failures or ignores |
| LSF Store lifecycle selection | 8 passed; no failures or ignores |
| Source integrity and compiled/source cohort controls | 16 passed |
| Production library without async/component/GC features | `cargo check` passed; not a runtime test |
| Threaded clock-fixture cross-check using this engine | Five tests passed in each of 20 parallel runs |

The new controls exercise repeated refusal, prefix-only decommit, pressure
retry, the batch-size-one path, empty queues, clean fresh-Store reuse, native
stack refusal and zeroing, shutdown success and terminal shutdown refusal. The
last case intentionally retains one finite pool until test-process exit.
Observed test counts are not an inventory requirement.

Reproduction commands, using the repository's Rust toolchain and lockfiles:

```sh
CARGO_TARGET_DIR=/path/outside/vendor/target cargo test \
  --manifest-path crates/vendor/wasmtime/Cargo.toml --lib --locked \
  --no-default-features \
  --features cranelift,runtime,std,pooling-allocator,wat,async,component-model,gc,gc-drc,cache,threads,coredump \
  runtime::vm::instance::allocator::pooling
cargo test -p latent-wasmtime --lib backend::store --locked
python -m unittest tools.tests.test_host_codec_wasmtime -v
```

Keep the build target outside the authenticated vendor source directory. Local
runs used the retained source and captured registry dependencies with `--offline`.
The complete local checkout is the captured ownership tree plus this patch;
it is not represented as a new signed or GitHub-qualified head.

All 250 original upstream file identities were rechecked. The cumulative patch
was reapplied to that original source with zero fuzz, and all 273 resulting
source files matched the selected tree byte-for-byte. Immutable upstream
inventory and original-package checksum are unchanged. The selected cumulative
patch SHA-256 is
`2b2738d67f29a3f19a4d7ea5d4399b4818190392dcc29920115be2b21eb5d04e`.

A broader selected vendor-library run produced 173 passes and five page-map
failures. Four of those failures reproduced on the unmodified baseline; the
fifth varied between runs. No full vendor-suite pass is claimed, and none of
those assertions was weakened or disabled. A reduced-feature libtest build
also failed to compile because existing test modules reference disabled
stack/cache/component/GC APIs; it is not counted as execution evidence.

## Remaining boundary

The guards retained here are the guards actually stored in pool entities. The
complete `HostState`/`ActivationRuntime` owner table is **not** yet held until
operating-system decommit acknowledgement. `StoreCustody`'s existing destructor
ordering and panic retention are separate guarantees, not a per-Store physical
receipt for this queue.

Complete original-budget attribution, per-Store acknowledgement, retryable
cell quarantine retaining all original reservations, non-Linux mapping-reset
failure, and current-source signed SpiderMonkey/cross-tenant qualification
remain open. A clean fresh Store in these engine tests does not prove those
broader contracts. No issue acceptance checkbox or runtime profile is promoted.
