# Shared client profile validation evidence

Bounded local run on 2026-09-19, Windows x64, isolated `target/phase3-227`
worktree. No credentials, production payloads or provider configuration were
used. This records model/fixture evidence for #227, not transport delivery.

| Check | Observed result |
| --- | --- |
| `python sdk/profile/validate.py` | 8 authoritative RPCs, 6 facades, 68 shared vectors and 16 unsigned boundaries validated; generated files current. |
| `python -m unittest discover -s sdk/profile -p "test_*.py"` | 12 tests passed using Python 3.13.5. |
| `cargo test -p latent-sdk --locked --tests` | 11 tests passed, including public `latent_sdk::management` vector/lifetime tests and unchanged legacy identity/publication tests, Rust 1.97.1. |
| `cargo clippy -p latent-sdk --locked --all-targets -- -D warnings` | Passed. Generated vector assertions allow only the intentional long-function lint. |
| `rustfmt --edition 2021 --check` on the three new Rust sources | Passed; generated Rust and Go also reproduce through pinned formatter output. |
| `go test -timeout 30s ./...` in `sdk/go` | Both packages passed with Go 1.23.2; shared vectors and bounded context/recovery tests executed. |
| `npm --prefix sdk/typescript-client run test:semantic` | TypeScript 5.8.3 compilation and vectors/lifetime/legacy tests passed on Node 24.19.0. |
| `javac --release 21` plus `dev.latent.sdk.InvocationIdentityTest` | All sources compiled and vectors/lifetime/legacy tests passed on JDK 25.0.3. |
| Release build and execution of `Latent.Sdk.SemanticTests` | Zero warnings/errors; vectors/lifetime/legacy tests passed on .NET SDK 8.0.425. |
| Zig 0.16.0 `cc -std=c11 -Wall -Wextra -Werror -pedantic` plus executable | Windows-native C vectors, callback ownership and legacy tests passed. |

Every native suite checks the same 68 cases and canonical decimal inputs.
Important regression boundaries include exact `18446744073709551615`, values
above JavaScript's safe number range, trailing LF/CRLF/NUL rejection, optional
zero versus missing generation, unknown signed enum values, retained publication
and original operation receipts, independent audit uncertainty, and local
cancellation that cannot establish server cleanup. Rust uses a bounded poll;
Go/Java/.NET use finite wait guards; C checks callback/handle ownership without
unbounded asynchronous work.

The final audit correction adds independent optional u64
`audit_attempt_sequence` to response metadata and failures. Shared vectors verify
absent/zero/max presence, retain a known acknowledgement separately, and preserve
unknown `future-state` plus a maximum attempt without fabricating any numeric
acknowledgement. All six native suites rerun these same corrected cases.

## Reproduction and limits

Use the [profile commands](README.md#executable-semantic-fixtures) with repository
toolchain pins. Local build/cache output stayed below this worktree's ignored
`target`; TypeScript dependencies/build output stayed within this worktree.
Rust commands used a dedicated `--target-dir target/profile-cargo`. The .NET
run used an ignored bootstrap directory pinned to installed 8.0.425 and an
isolated `--artifacts-path`, not the pre-existing SDK target directory.

The local Node/JDK/.NET runtimes differ from the pinned Linux CI values
22.16.0/21.0.11+10/8.0.423. C ran on Windows, not the shell runner's Linux target.
Consequently this is not a claim that the exact Linux `tools/validate_sdks.sh`
gate ran locally. The existing native CI entry points include all new suites;
parent review must check the final PR head rather than an earlier milestone.
The dedicated Python generation check remains a separate command for the CI
owner to schedule with pinned `rustfmt` and `gofmt`; no workflow changes are
included here.

Model construction and lifetime doubles do not validate protobuf codecs, a live
node, authentication, provider calls, closed policy document validation or
production mutation replay. Those proofs remain with executable transport
tickets #228/#230/#260/#261/#262/#263 and the server suites. No retry, remote
cleanup, invented grant ceiling or client-side authorization is inferred from
these tests. `ListCapabilities` has no authoritative effective-ceiling field;
referenced policy/binding documents retain stored limits without turning them
into execution authority.
