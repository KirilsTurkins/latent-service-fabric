# Current Java runtime and policy source verification

These original Linux executions verify the merged preparation, AOT and trust
owners. They retain exact committed source trees, complete Git and benchmark
inputs, read-only source mounts, true debug assertions and overflow checks, and
each registered suite's original 900-second limit. Retired private caches were
forked read-only into new owned volumes; their earlier results supplied no pass.

| Original source | Complete suite | Actual result | Build and execution |
| --- | --- | --- | --- |
| `e6209fcd4e36627a25b5a4fde16a31b053080027` | Wasmtime library | 345 passed, 2 original benchmark collectors ignored, 0 filtered | 75.83 seconds |
| `e6209fcd4e36627a25b5a4fde16a31b053080027` | Native AOT cache | 5 passed, 0 ignored, 0 filtered | 26.99 seconds |
| `f8a60eaaa083cd9c71590c367fb643c73cc15fd3` | Policy library | 110 passed, 7 original fixture/registry cases ignored, 0 filtered; all 117 names listed | 38.51 seconds |

The [runtime review](runtime-review.json) rechecks every registered case name,
original log digest, both executed ELF digests, actual container exit and control
settings. The complete AOT suite includes the real buffered-web profile change
after physical restart; its [raw log](native-aot-cache.log) and
[receipt](native-aot-cache-receipt.json) remain original bytes.

The first complete current policy execution failed with 109 passes and one
failure. Its [original log](failed-e620-policy.log) and
[receipt](failed-e620-policy-receipt.json) stay failed. The parser already knew
the activation-runtime operations and clock scope but omitted that exact
contract from its explicit opt-in allowlist. The one-line production correction
at `f8a60eaa` preserves the default linker, strict operation/resource grammar and
wrong-version refusal. The [fresh policy seal](policy-review.json),
[complete listing](policy-library-list.log) and [raw execution](policy-library.log)
record the corrected complete run. All twelve clock-renewal cases, shared-reader
poison and retirement cases, nonblocking commit/currentness fence and shared web
verification reservation executed successfully.

The [policy source bridge](current-policy-owner-bridge.json) records all 68
reviewed source hashes on the six published Java branches. All library source
and manifest bytes match; 63 of the 68 reviewed files are identical on every
branch. Five example-authoring files vary
on #748/#762. The [Wasmtime bridge](current-wasmtime-owner-bridge.json) retains the
separate security-fixture cleanup variation and #802's additional Phase 4 source.
It does not claim whole-crate byte equality for those variants. Exact source
observations remain separate from a full dependency or execution qualification.

[The file inventory](original-files.json) hashes the copied original records,
logs and runtime collector source. Earlier C4, packaged R5 and actual AOT receipts
retain their original sources and outcomes. Full current CI, actual signed Java
#718 campaigns and final delivery remain separate required evidence.
