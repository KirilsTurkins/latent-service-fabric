# Qualified HTTP effect conformance

The closed [put-once contract](../reference/qualified-http-effects.md) passed
all 54 registered `latent-http.lib.latent-http` cases on Linux x86-64 at clean
source `cc797f977d67ae939cba7997d0dc9eabfd56909e`, using Rust 1.97.1.
The maintained suite discovery confirmed the exact 54 names and zero ignored
cases. Strict HTTP-owner Clippy passed for all targets and features with
`--no-deps -- -D warnings`.

The [source and artifact receipt](evidence/http-effect-put-once-v1-cc797f97.json)
records exact endpoint version 1, lost-response proxy version 1, source hashes,
successful Cargo artifact inventory, native executable and execution/lint log
hashes. The native build used the existing bounded HTTP transport and the cached
Rust toolchain; the protected-owner cases used an ext4 Cargo-volume root with
safe ancestry. Overlay and unsafe-ancestry refusals from earlier fixture setup
attempts remain in the local qualification directory along with failed draft
runs and tooling attempts. They do not count as passes.

The executed commands were:

```bash
export LATENT_STATE_TEST_ROOT=/protected/effect393-protected-test-roots
cargo --config .cargo/managed-guest.toml test --offline --locked -p latent-http --lib --all-features --no-run --message-format=json
cargo --config .cargo/managed-guest.toml test --offline --locked -p latent-http --lib --all-features -- --test-threads=2
cargo --config .cargo/managed-guest.toml clippy --offline --locked -p latent-http --all-targets --all-features --no-deps -- -D warnings
```

The endpoint atomically persisted its counter and receipt in the selected
embedded database, then reopened the database and compared the retained records
and counter. An equal-key replay made two PUT attempts but only one mutation.
The lost-response case made one PUT and one GET, recovered the original opaque
acknowledgement and retained one mutation. Changed-body reuse returned conflict
without a second mutation. Removing an expired lookup record did not allow a
late request with the original cutoff to mutate again.

The existing dispatcher tests persisted its normal lower-store atomic fixture
rows before the send marker, inspected the durable send attempt, recovered an
acknowledgement through the real TLS proxy, and reopened its protected database
after a crash before send. The fixture exercises the current protected
credential reference, rotation, revocation, original horizon, finite budgets,
and physical ownership during dropped callers in send/read. No live guest
capability is fabricated.

This record qualifies the adapter and its synthetic, approved local TLS peer.
The common upper guest commit path and production entry gate #240 require their
own integration evidence. Arbitrary HTTP endpoints and commercial provider
contracts are outside this record; ambiguous or expired remote history still
requires explicit operator reconciliation.
