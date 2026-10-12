# Accepted policy and publication rejection

An accepted deferred-effect grant retains the rejection token of its original
approved installation. Accepted policy withdrawal, binding changes, and exact
publication lifecycle changes permanently close affected tokens. Reapproving a
rule creates a fresh token; it cannot reopen an earlier accepted context or
provider grant. The original physical context, provider request and native
reservation remain owned until actual cleanup. Rejection supplies no proof of
nonexecution and authorizes no retry.

The node must attach `EffectAuthorityOwner::rejection_observer()` to its actual
`PolicyStore` and `LifecycleAuthorityHandle` before either exposes decisions or
mutations. Both `install_rejection_observer` methods accept exactly one adapter;
late or duplicate registration fails. `rejection_observer_matches` checks the
exact shared adapter identity, so equal limits or a second effect owner cannot
satisfy startup composition. Existing stateless owners retain their supported
unobserved behavior; Phase 4 startup must explicitly require both attachments.

The observer is a sealed weak adapter implemented entirely in
`latent-core::authority_rejection`. It invokes no Effects, provider, policy,
artifact, audit or native callback. Its registry holds at most the configured
effect-rule count plus four lookup tokens. Entries contain bounded tenant and
publication identifiers and weak atomic flags. No credentials, documents,
physical keepers, per-record workers, timers or unbounded history are retained.
Rejected or expired weak entries are reclaimed before another installation.
Registry poisoning and owner retirement fail closed. Retirement or uncertain
owner persistence also closes future installation in that same registry; a new
node owner must be explicitly bound before it can approve new work.

Policy acceptance rejects only the changed tenant. Publication acceptance uses
the exact validated publication and tenant scope; an unscoped local publication
matches only its exact publication ID. Final CAS, response preflight and metadata
validation precede rejection. Historical receipt replay, rejected transitions,
and unchanged publication rows do not accept another authority change. Rejection
finishes before the first persistence call. Unknown or failed persistence never
restores tokens. Actual policy/lifecycle fences keep their existing ordering;
the new lower-layer metadata lock never calls back into them and is released
before disk I/O.

Rule publication still requires the trusted host's current policy/publication
installation fence. A rejected installation refuses an identical or older
policy revision. Reinstallation requires a newer actually approved policy
revision; bare configuration, IDs and digests supply no approval. A compatible
ceiling widening without an accepted authority change preserves an eligible
grant's original ceiling, expiry and deadline. Disabled, narrowed or replaced
installations permanently reject their earlier tokens. Sticky namespace
incarnation closure continues to use its existing exact namespace fence.

Fresh `ReconcileOnly` lookup has its own finite token under actual current
management permission. It may inspect an old disabled execution installation,
but its purpose cannot become send authority. A later affected policy or
publication acceptance rejects that original lookup token as well. Retirement
reclaims its registry entry without refunding a still retained provider or
native owner.

Eighteen added schedules cover the neutral registry, real policy and lifecycle
ledgers, persistence cuts and restart, retained provider grants, exact native
capacity, and current-policy/current-publication resealing for distinct fresh
work. The Wire schedules perform actual accepted owner mutations while an
original physical context and native reservation remain held; they are not
network or storage-envelope qualification. Existing provider HTTP/TLS schedules
must consume these hooks to demonstrate a held prewrite denial. Production
startup attachment and that provider integration remain required.

This milestone registers the source schedules and passes formatting, source,
documentation, generator and CI inventory checks. New native tests and strict
Clippy have not run while compiler work is held for disk capacity. It supplies
no new native, packaged-node, full CI or issue-closure evidence.
