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

Guest staging captures this ceiling and exact profile immediately. Final command
preparation calls `EffectAuthorityOwner::refresh_for_commit` with the staged
envelope. It preserves the payload and all command/effect provenance, intersects
the captured ceiling with the current compatible rule, and records that narrower
intersection. The lifetime origin becomes the final preparation time; its age
and timeout are capped by the original remaining lifetime, so this step cannot
extend staged expiry. Compatible policy revision and protected-credential
rotation do not change the destination or decoder.

The final `commit_fence` then checks the complete finite intent set. Any further
ceiling narrowing rejects this prepared commit instead of persisting broader
authority. The caller retains the original command claim for physical retirement
and a durable technical-abort disposition; it must not re-run the guest to hide
this conflict. The metadata-only fence remains held through namespace and
cancellation acceptance and is released before engine I/O. Neither refresh nor
this final fence allocates a dispatch permit.

Final adapter delegation also seals the exact payload digest, byte count and
durable lifetime. `PayloadRecord::verify_grant` checks the retained payload
against that delegation before transport admission, including media and sorted
metadata. `into_value` transfers the verified request buffer into the transport
owner without allocating a second body. The focused ownership schedule rejects
changed effect identity, media, metadata and bytes and verifies the transferred
buffer keeps its allocation. Windows library validation passes all 44 portable
cases and strict all-target Clippy; the eight Linux runtime schedules retain
their separate platform requirement.

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

The registered `latent-effects.lib.latent-effects` suite requires all seventeen
authority cases alongside the bounded payload and storage cases. Phase 4 uses
explicitly unordered effect dispatch; sequence
numbers allocate identity and do not promise provider completion ordering.

The staging refresh and strict final fence were validated with all 43 effect
library cases and strict all-target Clippy on Windows on 2026-10-01. The three
new schedules cover immutable provenance and expiry under narrowing/widening,
incompatible profiles and clock/expiry failures, and a policy change between
refresh and final acceptance. The local Linux rerun was blocked before execution
by a Docker Desktop engine HTTP 500; it supplies no new Linux evidence.

## Rechecking a retained transport grant

`DispatchGrant::check_current(EffectTime)` checks the exact original sealed
effect owner after any awaited connection or qualification work and before
protocol writes. It reads bounded current metadata under the same short rule
fence. Revocation, changed adapter/profile, a narrower ceiling, credential
epoch/reference replacement, expired original age/deadline, or clock rollback
fails closed. Compatible policy widening cannot change the captured ceiling,
expiry or original attempt deadline. The provider request separately checks its
original installed provider epoch and protected credential material.

A bounded shared liveness flag belongs to the original affine
`DispatchContext`. Actual retirement or unexpected context drop closes only
that attempt's grants; another live attempt cannot revive them. This check
allocates no physical permit, queue, retry or worker and never refreshes a
lease. It must run outside the already held `accept_with` fence. The maintained
NATS adapter invokes it before setup and immediately before publication.

All 57 portable Windows effect library cases passed on Rust 1.97.1, including
three new current-grant schedules, with zero ignored or filtered cases; strict
all-target/all-feature effect Clippy passed. The exact Linux inventory is now
73 cases. New native transport execution remains separately qualified by the
owned provider fixture; these metadata tests do not establish broker or HTTP
endpoint qualification.

## Accepted namespace closure and retained provider grants

Namespace management uses `prepare_namespace_close` inside its actual final
Policy -> Namespace -> Effects acceptance fence. The affine metadata fence
checks finite sticky-closure capacity before invoking the original native
request gate. Rejected native acceptance changes no rule. Successful acceptance
disables every rule for the exact tenant, namespace and incarnation before
engine I/O. It preserves all original physical provider owners and deadlines.

The same rules owner backs `DispatchGrant::check_current`, so a provider waiting
for connection/TLS cannot use a retained grant to write after accepted closure.
Rule publication cannot re-enable that closed incarnation, including under a
newer publication. A recreated namespace has a distinct incarnation. An
uncertain durable close remains conservatively closed; no management response,
timeout or policy replacement supplies physical retirement or an abort proof.
The closure registry is bounded by the existing configured maximum rule count.

The actual state-management adapter attaches this fence to quiesce, retire,
destroy and recreate, using the installed dispatcher's same rules/store owner.
It also binds the original global request keeper before native submission, so
callback errors and protected-root checks cannot release it early. This bridge
is separate from publication policy mutation, whose trusted installation owner
must publish the corresponding current effect rule revocation.

On the pinned Linux Rust 1.97.1 image, all 95 effect library cases and all 19
state-management cases passed; the latter selected the actual native management
adapter rather than unrelated Wire cases. Strict all-target/all-feature effect
Clippy passed. The new Wire schedule creates a real namespace, retains an
accepted provider grant, commits authenticated quiescence, and proves its
original grant is denied while the physical permit remains charged. These
checks establish the metadata/engine bridge; the provider's held-TLS schedule
separately establishes transport behavior.
