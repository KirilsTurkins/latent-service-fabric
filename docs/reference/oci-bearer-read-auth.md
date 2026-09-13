# Bounded OCI Bearer read authentication

This document describes the first delivered slice of Phase 3 issue
[#269](https://github.com/KirilsTurkins/latent-service-fabric/issues/269). It extends
the existing OCI transport with one fail-closed Registry v2 Bearer authentication
continuation for safe reads. It does **not** make `lsf-oci-bearer-v1` a complete or
supported transport profile yet; shared token ownership/refresh, authenticated
writes and the real-registry conformance matrix remain outstanding.

The permanent authority rules in [OCI registry adapter](oci-registry.md) continue
to apply. A registry-provided challenge is untrusted protocol data, not authority
to contact a new service or forward credentials.

## Configure one approved token authority

Use `RegistryCredentials::BearerChallenge` only when the operator already knows
and approves the exact token service:

```rust
use latent_oci::{RegistryConfig, RegistryCredentials, RegistryLimits};

let config = RegistryConfig {
    origin: "https://registry.example".into(),
    repository: "tenant/site".into(),
    credentials: RegistryCredentials::BearerChallenge {
        realm: "https://auth.example/token".into(),
        service: "registry.example".into(),
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
query or fragment. A hostname realm requires at least one explicit `SocketAddr`
and accepts at most 16; every address must use the realm's effective port and
must not be unspecified. Token requests use a separate HTTP client and resolver
mapping from registry requests. Both clients disable ambient proxies, redirects,
automatic retries and response decompression and use the configured TLS trust
roots.

`username`, `password` and acquired token bytes are kept in sensitive HTTP header
values and are redacted by configuration diagnostics. The Basic credential is
sent only to the configured token realm. It is never forwarded merely because a
registry advertises another URL.

## Challenge and scope rules

A challenge continuation is considered only after a `401 Unauthorized` response
to a bodyless `GET` or `HEAD`. The adapter requires exactly one
`WWW-Authenticate` field no larger than 4096 bytes. It accepts only a strict
Bearer challenge containing exactly one quoted `realm`, `service` and `scope`.
Unknown, duplicated, malformed or escaped parameters fail closed.

All three values must match local configuration. In particular, the accepted
scope is constructed locally as:

```text
repository:<configured repository>:pull
```

The server cannot expand this to `pull,push`, another repository or another
service. The registry origin and token realm therefore remain two separately
configured authorities.

## Token exchange and deadlines

The token request uses the same absolute `Operation.deadline` created for the
original OCI operation. Connect and per-request timeouts remain inner ceilings;
a challenge does not start a fresh operation budget. There is at most one token
exchange and one authenticated follow-up request. A second `401` is returned as
an authentication failure rather than entering another challenge loop.

Token-service response headers retain the normal OCI response ceiling of 100
headers and 16 KiB aggregate header bytes. The JSON body is limited to 16 KiB.
`token` or `access_token` is accepted; if both are present they must be identical.
The token itself is limited to 8192 printable ASCII bytes. `expires_in = 0` is
rejected, and a returned `scope`, when present, must exactly equal the configured
pull scope.

Because the adapter currently does not retain a token cache, the token body is a
bounded transient allocation owned by the in-flight operation. With the existing
hard maximum of 32 concurrent OCI operations, these token-response buffers are
bounded independently of the number of dormant services. No refresh worker,
per-service timer or background token owner is created by this slice.

## Writes deliberately do not authenticate by replay

`POST`, `PUT`, `PATCH`, `DELETE`, and any body-bearing request are never repeated
automatically after an authentication response. The adapter cannot generally know
whether a remote registry observed an upload or finalization request before the
response was lost or replaced. This slice therefore prefers an explicit
`Unauthenticated` result over manufacturing write certainty.

Authenticated push requires a later #269 delivery that defines the continuation
and uncertainty rules for each Registry v2 write step. Existing preissued Basic
and Bearer credentials keep their previous static-profile behavior.

## Still outstanding for #269

This slice intentionally does not implement:

- shared token caching, acquisition coalescing or bounded refresh ownership;
- expiry/skew policy beyond rejecting a zero lifetime;
- refresh credentials or credential/principal epoch invalidation;
- authenticated upload/finalization continuation;
- cancellation/concurrency tests for shared refresh work, because no shared
  refresh owner exists yet;
- the disposable challenge-auth registry/Harbor conformance run;
- the DNS and authorized-redirect behavior owned by #270.

Those capabilities must retain finite node-owned state and the original operation
deadline. Adding them later must not reinterpret this read-only slice as evidence
that authenticated writes or the full `lsf-oci-bearer-v1` profile are already
supported.
