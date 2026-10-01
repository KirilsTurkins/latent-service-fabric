# Recovery substrate native qualification

The exact source `d8c4efb29949c13747f2c0858033bdc9b6cd6c39` passed
the finite Linux x86-64/ext4 campaign recorded in the
[receipt](recovery399-native-evidence.json). It used the pinned Rust 1.97.1
toolchain, preserved debug assertions and overflow checks, and an immutable
read-only source archive. Fixtures used a separately owned ext4 volume;
overlay and temporary-memory filesystems were not substituted.

All 142 State cases passed. Protected files had 18 passing cases and its one
previously registered ignored ownership case. The actual executable inventories
matched every maintained expected name and ignored obligation. Both packages
passed strict all-target/all-feature Clippy with `--no-deps -D warnings`.
The earlier source's native lint failure and subsequent corrected source,
executable identities and log digests are retained separately in the receipt.

The actual protected recovery cases cover:

- Backup and fresh restore on real selected engines, private output permissions,
  unchanged business namespace bytes, a new recovery epoch and paused admission.
- Refusal while the ordinary physical owner is live, active namespace refusal,
  and missing-root refusal without creating an ordinary database.
- A dropped backup waiter and expired drain while its actual worker is parked:
  retained bytes and the root remain owned; a second owner is refused until
  actual retirement, and the timeout remains quarantined.
- Missing immutable artifacts, revoked operator authorization, wrong input
  digest and existing failed destinations, with the current source still usable.

The portable engine cases additionally exercise current-row acknowledgement
changes without namespace generation, the original deadline, every durable
write fence, interrupted staging, corrupt input, unsupported decoding, linked
inventory refusal and opaque token invalidation after older restore.

The commands are `cargo test --locked -p latent-state -p latent-protected-files
--all-features --lib --no-run`, the same packages' `--list --format terse` and
normal library tests, followed by `cargo clippy --locked` for both packages with
`--all-targets --all-features --no-deps -- -D warnings`. They use
`.cargo/managed-guest.toml`, `CARGO_INCREMENTAL=0`, zero host debug-symbol levels
and `LATENT_STATE_TEST_ROOT` on the qualified private local ext4 volume.
After the bounded initial dependency acquisition, execution was offline.

This campaign certifies the substrate source and finite physical fixture.
Its retained-work inventory is empty. The composed command/result/inbox/effect
workload, actual Java v1/v2 data change, current runtime authorization and a
remote success after a pending backup remain separate integration requirements.
No application snapshot or backup payload is published as test evidence.
# Explicit protected review and resume

The subsequent immutable source `e134d9363046729173b23fba64f482354302e1dd`
passed all 147 maintained State cases on actual Linux x86_64/ext4, including two
new physical administrative review/resume cases. Protected-files passed 18 cases
with its one historical registered ignored ownership case. Both owners passed
strict all-target/all-feature Clippy. Actual libtest discovery exactly matched
all 147/19 maintained case names. The [resume receipt](recovery399-resume-native-evidence.json)
records source/archive/tool, logs and preserved executable hashes separately
from the earlier snapshot source qualification.

The fixture restores a real protected engine, observes its new recovery epoch,
refuses namespace resume before global review, keeps the namespace paused after
global review, then uses the installed explicit resume port. After actual engine
retirement/reopening it refuses the original pre-restore live token and replays
the original bounded operation receipt under current authorization. A second
case changes authorization after installed review and verifies refusal at the
real irreversible writer fence with unchanged namespace/token.

The prior source `e9a0b792` passed all 147 State cases but failed strict native
lint for three unnecessary owned arguments in a new test helper; that failure
is retained and the narrow borrow-only fix has no suppressed check. The initial
source-staging quoting refusals and empty-cache selection error are also kept
under the local qualification directory. These are not engine-test passes.
No real retained effect/inbox workload, Java capsule, migration, management
command or complete #398/#399 acceptance claim is included in this receipt.
