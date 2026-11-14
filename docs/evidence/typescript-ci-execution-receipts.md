# TypeScript stack: strict execution receipts and captured clock output

## Reproduced parent CI failures

General CI run `43246096504` used head
`aafe9fe575a373aa8333285fc4ca5d5bb6b0805f` and synthetic merge
`7d1d16ff52ce91d04e46aa7a1715aee4f776c4a8`.

Two early jobs failed on the import order in
`latent-component-threading/src/admission/derived_names.rs`. Commit
`aa491f5753e3982a38a7bd60c5084725ab4e8a37` already corrects the Rust 2024
formatting; this patch does not duplicate it.

The workspace test job's retained execution receipt reported sixteen errors
across eight suites even though the underlying cases passed. Two reporting
problems were distinguishable in artifact `13957048912`:

1. Libtest's pretty formatter appends ` - should panic` to the execution name
   of a `#[should_panic]` case, while discovery lists its unannotated identity.
   The receipt parser treated the display annotation as a new, unknown case.
2. The clock fixture wrote directly through `stderr().lock()`, bypassing
   libtest capture. Concurrent clock diagnostics split one test's outcome line
   in the `go_write_progress_runtime` suite. That damaged transcript does not
   establish a valid execution receipt and must remain rejected.

## Changes

`_libtest_outcomes` resolves only libtest's exact terminal ` - should panic`
annotation and only to an already discovered identity. Arbitrary suffixes are
not stripped. Ambiguous displayed/original identities, unknown cases, failures,
missing outcomes, duplicates and incorrect ignored state remain errors. The
same resolution applies to the standard long-running-case progress message.

The five clock-witness writes now use `eprintln!`, which participates in libtest
capture. The witness text and lifecycle assertions are unchanged. Qualification
runs using `--nocapture` still receive the original witness lines; `--show-output`
also retains them. Ordinary parallel tests no longer interleave those bytes
with libtest's outcome stream. No malformed-line exception is added to the
receipt parser.

## Executed validation

| Selection | Observed result |
| --- | --- |
| Discovery/receipt and Go clock Python controls | 29 passed |
| Component-threading default source proofs | 90 passed |
| Component-threading all-feature source proofs | 91 passed |
| Component-threading combined-preview source proofs | 95 passed |
| Actual clock tests with two test threads | Five cases passed in every one of 20 runs |
| Actual clock witness modes | Original zero/ticker/wall witnesses present under both `--nocapture` and `--show-output` |

The new parser regression controls also require failure for invented names,
foreign suffixes, missing/duplicate outcomes, a failed should-panic case,
incorrect ignores, ambiguous identities and the historical interleaving shape.

Replaying the historical artifact with the new parser removes the fifteen
annotation-related errors. The one genuinely damaged historical suite remains
rejected. That artifact is not rewritten, repaired into a pass, or substituted
for fresh execution.

The native clock executions use the captured ownership source tree plus the
concurrent vendored decommit patch and this exact fixture. They execute real
Rust/libtest output, but are not an exact full-parent checkout or signed guest
qualification. The changed parent-file preimages are independently checked
against the published parent. The source-proof crate bytes match the published
parent plus its already-published formatting fix. Counts describe observations,
not new inventory gates.

```sh
python -m unittest tools.tests.test_ci_suite_discovery tools.tests.test_go_zero_clock -v
cargo test -p latent-component-threading --lib --locked
cargo test -p latent-component-threading --lib --all-features --locked
cargo test -p latent-component-threading --lib --features rust-http-combined-preview-diagnostic --locked
cargo test -p latent-wasmtime --test go_write_progress_runtime fixture::zero_clock::tests --locked -- --test-threads=2
```

No guest result, resource budget, registered inventory, ignored-test policy,
dependency pin, golden component image or qualification success predicate is
weakened. A fresh complete CI run remains necessary after publication.
