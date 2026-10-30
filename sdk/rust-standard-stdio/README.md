# latent-standard-stdio

Compiler-owned synchronous bridge from the selected Rust standard-library stdio
PAL to the existing typed LSF LOG import. It supports the explicit bounded logging
profile beneath ordinary `std::io`, `print!` and `eprint!`. It is not an external
client, general WASI stdio implementation or application callback.

The implementation is wasm32-only. A native build contains no logging bridge and
does not qualify guest execution. The owned sysroot and bridge must use the same
pinned Rust compiler and be bound together by the source recipe.

## Architecture

[src/lib.rs](src/lib.rs) exports the fixed intra-core Rust-ABI symbol
`__lsf_std_log_write_v1(level, message)`. Its body calls the actual generated
`latent-component-bindings` LOG interface without pointer, allocator or canonical
variant-layout assumptions. Only the symbol's export attribute allows unsafe
code; the handwritten body does not.

| Input or result | Meaning |
| --- | --- |
| Level 2 / 4 | Info for stdout / error for stderr; other values refuse. |
| Message | Borrowed UTF-8 text, at most 256 bytes per call, with no application-selected identity fields. |
| 0 | The typed LOG operation accepted the record. |
| 1 / 2 / 3 | Invalid input/field / budget exhausted / provider unavailable. |
| 4 | Reentrant bridge call refused. |
| 5 | Provider returned a negative acceptance result. |

A scoped atomic busy guard resets on destruction. Each call performs one typed
synchronous operation without retry, worker, queue or finalizer. Success means
sink acceptance, not remote delivery. Vector joining and its separate bounds
belong to the outer stdio PAL.

## Authority and lifetime

The [guest SDK's `standard-logging` feature](../rust-guest/README.md) includes the
bridge for the selected recipe. A Cargo feature does not install LOG, grant
permission or make an arbitrary sysroot ABI compatible. Application WIT, host
ABI recognition, installed provider and current policy must still agree.

The bridge supplies no ambient filesystem or terminal. Applications still choose
what they disclose in log text. The [Rust runtime source profile](../rust-standard-runtime/README.md)
describes the owned sysroot and distinct closed-stdio profile; this is not a
fallback that turns unsupported writes into successful discarded output.

## Verification and references

Use the [standard-facility matrix](../../docs/component-development/standard-facilities.md),
[Rust authoring guide](../../docs/component-development/rust-authoring.md) and
[runtime capability records](../../docs/component-development/runtime-capabilities.md)
for actual compiler/component evidence and remaining gates. Compile-only host
coverage is not execution of this wasm32 symbol. The
[local test workflow](../../docs/development/local-tests.md) owns suite/fixture
selection; [Cargo.toml](Cargo.toml) owns the target dependency.

See the [workspace index](../../crates/README.md) for other compiler, runtime and
client packages.
