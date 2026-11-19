# Native stack context physical custody

`StackContextHandle` owns the private, strong-only `Arc<StackContext>`. Every
holder uses `Arc::into_inner` when it drops. The last holder receives the value
after the backing allocation is freed; only then may dropping that value refund
its original metadata reservation. There is no extra allocation or second
ledger. No `Weak`, raw-Arc conversion, or direct-Arc owner may escape this
custody. Do not replace this with `Arc::try_unwrap(...).ok()`: competing failed
unwraps can leave ordinary Arc destruction responsible for the last release.

## Run the focused regression

On Linux x86_64 with the repository's pinned Rust toolchain:

```sh
bash tools/run_stack_custody_witness.sh
```

The same script runs in the `runtime` lane of `tools/validate_contracts.sh` and
in the narrowly selected `Native stack physical custody` workflow. The focused
workflow does not require unrelated guest compiler installation and retains
results even when compilation or execution fails. It supplements the existing
runtime contract lane; it does not replace workspace or signed guest tests.

The script builds and runs the native-stack unit tests twice: with
`development-stack-custody-witness`, then with that feature plus
`development-rust-http-combined`. Each pass must discover and successfully
execute the allocator witness. The combined pass also requires every discovered
combined-profile test to pass. Missing or ignored witnesses, zero-test success,
command failures, and execution timeout fail the script. The output directory
(optional first argument) retains each inventory, compiler stderr, execution
log and combined-control requirement list. A missing or incomplete profile is
not successful qualification, even if the other profile passes.

Do not substitute `--all-features` for these passes. The existing Go overlap
observer also installs a test global allocator; enabling its feature excludes
the stack observer. The all-features AOT preparation profile still records the
complete Cargo feature set, including the stack witness feature, even though
that observer is not compiled into that particular test closure.

## What is observed

The witness constructs the actual production context, captures bounded live
allocations on the constructing thread, and locates the allocation containing
that context without assuming an Arc header layout. The allocator pauses before
`System.dealloc` of that exact backing. While paused, the original budget must
still retain its full pre-drop charge. Once released and joined, the metadata
refund must be exact; releasing the runtime must leave no outstanding budget
bytes or reservations.

The cases are direct last drop, last of two cloned holders, controlled unwind,
and eight concurrently released holders. Capture is thread-local so unrelated
libtest allocation activity cannot corrupt it. An atomic one-shot address claim
prevents recycled allocations from generating a second observation. Capture and
worker cleanup use guards; setup failure or assertion unwind releases both the
start gate and the allocator gate and joins every spawned worker.

The source audit in `tools/native_loader_boundary.py` binds the reviewed
production files and the exact test-only observer. Mutation tests retain the
unsafe-code denial for changed, ungated, or copied allocator implementations.

## Scope and qualification limits

This is context-backing custody evidence, not a byte-accurate measurement of the
whole metadata escrow. It does not qualify Mapping boxes, worker escrow, all
native owners, signed guests, or the remaining requirements of #736/#745.
Neither the default production feature set nor any guest qualification workflow
is enabled or relaxed by this test. PR #2161's separate merge hold concerning
the Java scheduled compiler-model qualification remains in effect.
