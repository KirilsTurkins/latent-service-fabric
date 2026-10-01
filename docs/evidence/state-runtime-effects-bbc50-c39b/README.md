# StateRuntime retained effect authorization evidence

This records focused Linux qualification of the production retained authorization
owners. It does not establish signed Java command/query execution, HTTP application
delivery, restart recovery, or complete #718 qualification.

| Observation | Immutable source | Result |
| --- | --- | --- |
| Actual protected engine commit refuses a revoked original staging decision while the independent state decision remains valid, before entering the effect fence | `bbc50e81264b642de6b17ad67cbcf0a54e1782db` | 1 passed, 0 failed, 0 ignored |
| Actual deferred dispatcher retains `PolicyBlocked` when native dispatch authority is absent, does not admit the provider, and physically retires | `bbc50e81264b642de6b17ad67cbcf0a54e1782db` | 1 passed, 0 failed, 0 ignored |
| Actual signed publication and `PolicyStore` require the explicit native service dispatch purpose, original deadline and current policy; changed purpose, foreign caller and revocation refuse | `c39b7b3bc97b7a91756ce7d841a870a49aa3b6e8` | 1 passed, 0 failed, 0 ignored |
| Linux `latentd` library, all features, locked dependency graph | `c39b7b3bc97b7a91756ce7d841a870a49aa3b6e8` | `cargo check` passed; strict `cargo clippy --no-deps -- -D warnings` passed |

The first two case bodies and their production owners are unchanged in `c39b7b3b`.
That two-file fix adds the missing Linux test import and clones the same native
HTTP provider before coercion to the guest invoker interface. The table retains
the original executed source for each observation rather than presenting three
cases as one newly executed suite.

The source archives were produced from the published Git commits. Compilation used
the runnable tools image
`sha256:808682d39104dc67ea35b407841aa8ecd4d5662bb8fa8df09e78cecdf4cacde7`,
Rust 1.97.1, `.cargo/managed-guest.toml`, `--locked`, two build jobs, disabled
incremental compilation, and zero dev/test debug information. Each native container
was limited to four CPUs, 8 GiB and 512 processes. The protected fixture volume was
the original Linux ext4 owner. Sources were mounted read-only; the shared warm
cache had no other active owner during these runs.

The original failed attempts remain included:

- `r1` passed the engine and dispatcher cases. Its remaining policy/App commands
  stopped before compilation because their pinned dependencies were absent from
  the cache under `--offline`.
- `r2` downloaded the unchanged locked dependencies. It found the missing test
  import and the Linux provider `Arc` coercion compile error. It remains failed.
- `r3` used the separately published two-file fix, passed the policy case and App
  check/lint, and did not rerun the earlier two passing cases.

The raw reports, commands, exit codes, tool versions and original archive digests
are copied byte-for-byte under the attempt directories. [inventory.json](./inventory.json)
records their sizes and SHA-256 values. It also records the three executed test
binary hashes; those original binaries and source archives are preserved in the
owning worktree's `target/qualification718/native-effects-r*` directories. App
compilation and lint are source validation, with no App executable or guest
execution claim.
