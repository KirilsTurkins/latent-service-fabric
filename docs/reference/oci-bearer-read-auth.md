# Bounded OCI Bearer authentication

Phase 3 issue [#269](https://github.com/KirilsTurkins/latent-service-fabric/issues/269)
extends the original read-only PR #297 with scoped token caching, coalesced
on-demand refresh, credential rotation and authenticated writes. The complete
`lsf-oci-bearer-v1` transport adds the separately configured
[DNS and redirect policy](oci-network-profile.md); authentication alone does not
authorize either implicitly.

The permanent authority rules in [OCI registry adapter](oci-registry.md) continue
to apply. A registry-provided challenge is untrusted protocol data, not authority
to contact a new service or forward credentials.

## Configure one approved token authority

Use `RegistryCredentials::BearerChallenge` only when the operator already knows
and approves the exact token service:

```rust
use latent_core::TenantId;
use latent_oci::{BearerIdentity, RegistryActions, RegistryConfig, RegistryCredentials, RegistryLimits};

let config = RegistryConfig {
    origin: "https://registry.example".into(),
    repository: "tenant/site".into(),
    credentials: RegistryCredentials::BearerChallenge {
        realm: "https://auth.example/token".into(),
        service: "registry.example".into(),
        identity: BearerIdentity {
            tenant: TenantId("tenant".into()),
            principal: "registry-reader".into(),
            credential_epoch: 1,
        },
        actions: RegistryActions::Pull,
        username: "robot-reader".into(),
        password: load_secret(),
        addresses: vec!["192.0.2.40:443".parse().unwrap()],
    },
    addresses: vec!["192.0.2.20:443".parse().unwrap()],
    additional_root_certificates: Vec::new(),
    allow_insecure_loopback: false,
    limits: RegistryLimits::default(),
};
```

The token `realm` must be an exact HTTPS URL with a host and without userinfo,
query or fragment. With the ordinary constructors, a hostname realm requires
at least one explicit `SocketAddr`
and accepts at most 16; every address must use the realm's effective port and
must not be unspecified. Token requests use a separate HTTP client and resolver
mapping from registry requests. Both clients disable ambient proxies, redirects,
automatic retries and response decompression and use the configured TLS trust
roots.

`username`, `password` and acquired token bytes are kept in sensitive HTTP header
values and are redacted by configuration diagnostics. The Basic credential is
sent only to the configured token realm. It is never forwarded merely because a
registry advertises another URL.

The identity and action set are trusted operator configuration, never values
learned from a challenge or guest. Identity fields must be nonempty bounded
printable ASCII; epochs are positive `u64`. The alpha `BearerChallenge` Rust
constructor now requires explicit `identity` and `actions`. Static credential
variants retain their previous meaning. Share one `HttpOciRegistry` owner or its
clones; do not construct a provider/client per dormant deployment or per request.

## Challenge and scope rules

A challenge continuation is considered only after a `401 Unauthorized` response
to a bodyless `GET` or `HEAD`. The adapter requires exactly one
`WWW-Authenticate` field no larger than 4096 bytes. It accepts only a strict
Bearer challenge containing exactly one quoted `realm` and `service`, and an
optional quoted `scope` (the Registry v2 ping may omit it).
Unknown, duplicated, malformed or escaped parameters fail closed.

Realm and service must match local configuration. Any challenge scope must name
the configured repository and only locally permitted actions. Quoted comma
lists are parsed as values, not split into additional challenge parameters.
The requested token scope is constructed locally as:

```text
repository:<configured repository>:pull
repository:<configured repository>:pull,push
```

`RegistryActions::PullPush` explicitly enables the second form. A pull-only
owner rejects writes before network work; a challenge cannot expand it. Another
repository, service, realm or action is rejected. Registry and token realm remain
two separately configured authorities, even when both use the same hostname.

## Token exchange and deadlines

The token request uses the same absolute `Operation.deadline` created for the
original OCI operation. Connect and per-request timeouts remain inner ceilings;
a challenge does not start a fresh operation budget. Each continuation joins at
most one bounded acquisition and makes one authenticated follow-up. A second `401` is returned as
an authentication failure rather than entering another challenge loop.

Token-service response headers retain the normal OCI response ceiling of 100
headers and 16 KiB aggregate header bytes. The JSON body is limited to 16 KiB.
`token` or `access_token` is accepted; empty strings are absent aliases, as
emitted by Harbor 2.15.2. At least one nonempty token is required, and two
nonempty aliases must be identical. Explicit nulls remain malformed.
The token itself is limited to 8192 printable ASCII bytes. Optional fields may be
absent, but present-null, malformed and duplicate fields are rejected. A returned
`scope`, when present, must exactly equal the locally requested action set.

`expires_in` defaults to 60 seconds only when absent. Accepted lifetimes are
6–3600 seconds, with five seconds removed for skew. Bounded RFC3339 `issued_at`
values cannot be expired or more than five seconds ahead of the receiving clock.
The monotonic expiry cannot exceed the original acquisition-start lifetime;
issued time can shorten it, never extend it. Long token exchanges consume that
same lifetime and operation deadline.

There is one cached token per owner, bound structurally to the configured profile,
registry, realm, service, repository/actions, tenant, principal and credential
epoch. Clones share this state; independent clients never share tokens. One
async acquisition owner coalesces equivalent calls under the existing operation
limit (hard maximum 32); excess admission is rejected, not queued indefinitely.
Acquisition failures have a one-second on-demand negative-cache window to avoid
a serialized failure stampede. Deadline/cancellation does not poison other
callers' remaining budgets. No refresh worker or per-service timer is created.

Expired tokens are retired on demand. Refresh reauthenticates with the approved
Basic credential; offline refresh tokens are neither requested nor stored.
Unexpected `refresh_token` material is rejected rather than becoming a second
unscoped credential source. Token JSON and parsed secret strings are zeroized
when retired; HTTP headers remain sensitive and diagnostics omit credential data.

## Authenticated writes are never replayed

`POST`, `PUT`, `PATCH`, `DELETE`, and any body-bearing request are never repeated
automatically after an authentication response. The adapter cannot generally know
whether a remote registry observed an upload or finalization request before the
response was lost or replaced. A `PullPush` owner therefore obtains a token from
the explicitly approved realm **before sending the first write**, without first
probing with an unauthenticated mutation. A cached valid token can be reused.

`POST` initiation, upload/finalization and manifest publication each preserve the
existing upload ownership and uncertainty rules. A write's `401`, lost response,
timeout or disconnect is returned, not retried. Callers must inspect the original
digest/session outcome before considering another mutation. A write's `401`
invalidates that cached token for a later independently submitted operation;
it does not acquire another token or resubmit the failed write. Static Basic and
preissued Bearer behavior is unchanged.

## Rotation and physical ownership

`HttpOciRegistry::rotate_bearer_credentials(identity, username, password)` requires
the same tenant and principal and a strictly newer positive epoch. It immediately
invalidates later cached use and negative-cache entries. An old acquisition may
finish physically, but cannot install or send its token after rotation. New
callers wait on the same finite acquisition owner, not a second refresh worker.
Changing tenant, principal, realm or action authority requires a separate client.

`RegistryUsage.bearer` exposes the epoch, cached tokens, active and waiting
acquisitions, retained token bytes, their hard ceiling and a conservative 64 KiB
reservation per active acquisition. Token headers are at most 8199 bytes including
the scheme; retained headers are capped at `(max_in_flight + 2) * 8199`. Retired
tokens pinned by responses remain charged through response retirement; eviction
and rotation cannot manufacture capacity. Socket pools retain their existing
separate fixed ceilings.

Cancelling an acquisition leader drops its actual HTTP future and releases its
ownership only as that future retires; a remaining follower can acquire under
its own original deadline. Shutdown closes operation admission and waits for
actual transfers/upload cleanup before clearing credentials and token cache.
A shutdown deadline failure leaves live ownership visible instead of claiming
reclamation. Rotation does not undo a mutation already submitted to a registry.

## Validation and remaining transport boundary

```text
cargo test -p latent-oci --all-targets --locked
cargo clippy -p latent-oci --all-targets --locked --no-deps -- -D warnings
python -m unittest tools.tests.test_harbor_registry_runner tools.tests.test_oci_registry_runner
python tools/run_oci_registry_tests.py
python tools/run_harbor_registry_tests.py --output target/harbor-receipt.json
```

The ordinary Rust suite includes TLS fault peers for malicious authority,
malformed/oversized/expired tokens, read/write permission, coalescing, retained
buffers, rotation, lost writes, cancellation, deadlines and failed shutdown.
Controlled peers are not substituted for real-registry conformance.

The separate Harbor runner uses the digest-verified 2.15.2 installer template and
[pinned images](../../tools/harbor_registry/images.json), eight finite containers,
an isolated backend network, a loopback-only TLS frontend, fresh certificates and
a disposable private project's pull/push-only robot credential. It waits for
dependency health without restart loops. Cleanup verifies ownership labels and
removes immutable container/network IDs and owned volumes; fixture files stay
under the repository's `target/phase3-harbor` directory. This is not a production
Harbor installer or a server-hardening claim.

The real test pushes tiny packages and detached evidence, pulls by digest,
discovers native referrers, checks pull-only write denial and clean client
shutdown. The receipt records image/installer identities, source revision,
tracked-tree state and cleanup. A working-tree receipt is diagnostic, not an
immutable release claim. The separate [network conformance path](oci-network-profile.md)
adds explicit DNS and controlled-peer redirect validation without claiming
untested hosted-storage topology support. No mutable referrers-tag fallback is
introduced.
