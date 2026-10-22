# Explicit application fallback after native filesystem refusal

The [retained observation](evidence/sdk-explicit-fallback-2026-10-22.json) qualifies two normal C/Go builds and eight signed calls at source `7818c145d8645f535b048c166eece815d8975e95`. [The owning run](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39686600359) passed. This is a finite #679 fallback slice; it does not make filesystem operations available.

The C fixture calls ordinary `fopen`, requires a null result with `errno == ENOTSUP`, then computes `seed * 5 + 7`. The Go fixture calls ordinary `os.Open`, requires `*os.PathError`, `errors.Is(err, errors.ErrUnsupported)`, and `syscall.ENOSYS`, then performs the same alternate computation. The refusal checks execute before the alternate path. No filesystem grant or SDK/runtime substitution is introduced.

| Per-language call | Required result |
| --- | --- |
| `open:7` | Explicit fallback `42`, fresh static state |
| `open:11` | Explicit fallback `62`, fresh static state |
| `trap:13` | Deliberate trap after the native refusal checks |
| `open:19` | Explicit fallback `102`, fresh static state after the trap |

Every call retains its raw invocation and retirement observation before checking the oracle. All eight observations show the five physical owners retired and all 18 available provider counters zero. Both nodes shut down cleanly and were reaped. The controlled observation peers received zero requests. The original memory, fuel, wall, and capability limits remain in force.

The actual C build has 14 successful commands and the Go build has 16. Both use the normal package/sign/publish/admission path. The native tools retain their original three-product `f244` and two-product `f625` compilation identities. Their historical source is not relabelled as current Development.

The whole 241-member archive, all 117 executed Git inputs, both compiler recipes, captured application snapshots, build observations, component/package identities, and all eight raw outcomes were checked by a cached verifier. A second reviewer read the verifier and independently passed its live-origin mode.

Development composition preserves 115 of the 117 executed input files byte-for-byte. Two shared Rust helper files now contain the merged host-fork support: only Rust-specific functions or the Rust standard recipe changed; the C/Go-used functions remain identical. Regenerating the projects changes only the captured host `Cargo.toml` metadata and its SDK-lock entry. The C Zig and Go componentize-go builds do not execute that Cargo manifest. The original 58/106 source inventories and 53/61 recipe inventories remain bound to their actual historical builds, with exact old/current identities in the observation.

Earlier failures remain failures: an incorrect native-reader key before compilation, an account-egress 503 before compilation, and a successful first C fallback whose reader incorrectly required a success `terminalState`. The corrected success predicate follows the actual CLI schema; the trap predicate still requires the exact `guest_trap` terminal state. The old scratch programmes are unchanged and were not replayed.
