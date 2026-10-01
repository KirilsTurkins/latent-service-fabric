# Durable effect authority implementation

`latent-effects::authority` supplies the bounded current-authority owner for
Phase 4 deferred effects. Node policy and provider-binding code installs rules;
guest host imports cannot publish rules. The immutable captured envelope retains
tenant, namespace incarnation, publication, command/caller/attempt/commit/effect
identities, exact operation and decoder/destination profile, payload digest,
policy revision, finite ceilings and durable expiry. It contains no credentials,
guest handle, activation deadline, Store or execution cell.

Each attempt intersects captured and current ceilings under the same short
acceptance fence as rule update/revocation. A broader replacement rule cannot
enlarge committed authority. Compatible protected-credential epoch changes are
accepted, while destination, provider, payload/intent format or idempotency
profile changes block old work. The original application state schema does not
select a new decoder for an old intent.

Durable expiry, bounded per-attempt timeout and originating activation lifetime
are separate. A persisted clock floor and an affirmative continuity witness are
required after restart. Regression or unknown continuity blocks dispatch for
reconciliation; reboot never renews an effect's lifetime. This clock rule alone
does not authorize retention sweeping or deletion of protected command history.

Dispatch contexts belong to physical provider workers. They reserve bounded
shared capacity until actual transport cleanup calls `retire`. Dropping an
unretired context quarantines its capacity. Neither revocation nor a lost RPC
waiter turns accepted network work into proof of nonexecution. The dispatcher
must still claim committed records once, fence stale completions, persist their
disposition, and follow each adapter's qualified reconciliation/retry semantics.

This module is an implementation slice of issue #390. Production integration
with namespace authority, the atomic outbox store and standalone provider
workers remains required by #384/#386/#390/#391. Its rule installation API is a
trusted host port, not a substitute for authenticated policy admission. The
tests establish in-process authority and physical-owner behavior; they provide
no engine durability, network delivery, clean-host or power-loss evidence.

Run the focused checks from a prepared contributor checkout:

```sh
cargo test -p latent-effects --lib --locked
cargo clippy -p latent-effects --all-targets --locked -- -D warnings
```

The registered `latent-effects.lib.latent-effects` suite requires all nine
authority cases. Phase 4 uses explicitly unordered effect dispatch; sequence
numbers allocate identity and do not promise provider completion ordering.
