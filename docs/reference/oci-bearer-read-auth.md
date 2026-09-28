# Bounded OCI Bearer authentication

`lsf-oci-bearer-v1` provides scoped token caching, coalesced on-demand refresh,
credential rotation and authenticated writes. The complete
`lsf-oci-bearer-v1` transport adds the separately configured
[DNS and redirect policy](oci-network-profile.md); authentication alone does not
authorize either implicitly.

The permanent authority rules in [OCI registry adapter](oci-registry.md) continue
to apply. A registry-provided challenge is untrusted protocol data, not authority
to contact a new service or forward credentials.

## Configure the CLI

Use `latent package push` and `latent package pull` with a version 2
[registry profile](../../schemas/cli-registry-profile.schema.json). Start from
[the example profile](../../examples/guides/registry-challenge.json),
copy it to a private directory, and replace its example authorities and address
allowlists with values approved by your registry operator. The example addresses
are documentation addresses, not a working registry.

1. Set `origin` and `repository` to the exact registry and repository. Set
   `bearerChallenge.realm` to the approved HTTPS token URL and `service` to the
   exact challenge service. The CLI never discovers authority from a challenge.
2. Set the trusted `identity` tenant, principal and positive `credentialEpoch`.
   Select `pull` for download-only jobs or `pull-push` for publishers. These fields
   partition local credential ownership; they do not grant server permissions.
3. Have your CI secret provider write `credentials.json` beside the profile using
   the [Basic credential shape](../../schemas/cli-registry-credentials.schema.json).
   The username/password are sent only to the approved token realm. Use a private
   runner directory and restrict the file to the job identity (0700 directory and
   0600 file on Linux/WSL; an equivalent owner-only ACL on Windows). Pass only the
   file path to LSF. Never put secret values in arguments, logs, Terraform state or
   retained test receipts. A preissued Bearer credential file cannot be combined
   with `bearerChallenge`.
4. Choose explicit socket addresses in top-level `addresses` and
   `bearerChallenge.addresses`, or configure `network` and leave both arrays empty.
   Each network destination names an exact HTTPS origin, CIDR allowlist,
   `specialAddresses` and either static IPs or one explicit numeric DNS server.
   Every private, loopback, link-local or other special address needs exact
   approval as well as CIDR membership. Configure a DNS TTL ceiling of 1–300
   seconds. No system DNS, ambient HTTP proxy or credential helper is used.
5. Keep `maximumRedirects: 0` unless the selected registry requires storage
   redirects. Approve each required storage origin and bounded `contentPrefixes`
   explicitly; the maximum is three redirects. Only bodyless blob GET/HEAD may
   follow them, and redirected requests carry no registry or token credential.
   Writes, token exchanges and unrelated paths cannot use this permission.
6. Keep `rootCertificates: []` for the built-in public roots, or add approved DER
   CA file paths relative to the profile. There are at most eight roots of 64 KiB
   each. The version 2 profile always requires HTTPS and verified certificates.

Then use the same commands as the [OCI transfer workflow](../phase-2-operator-workflows.md#oci-transfer):

```sh
latent package push package --registry-profile registry.json --reference candidate --evidence-index evidence/index.json --evidence-root evidence
latent package pull --registry-profile registry.json --reference sha256:REPLACE_WITH_PUSH_DIGEST --output-dir received-package --evidence-output received-evidence
```

Use the exact returned digest for the second command. Inspect and verify the
received package and evidence before publication; transport authentication alone
does not grant publisher trust. One `--rpc-timeout-ms` budget covers profile
loading, DNS, token exchange, redirects and all package/referrer transfers.
Cleanup has a separate finite grace. An expired token can refresh on demand
within that budget; an expired CI identity cannot be renewed by LSF. Provision a
fresh protected credential and increment its epoch for a new command. A failed or
uncertain write is never automatically replayed: inspect the recorded confirmed
digests and uncertain outcome before submitting a new operation.

The profile and credential documents are each capped at 16 KiB. Unknown,
duplicate and present-null fields are rejected, including nested network fields.
There are at most eight destinations, sixteen address ranges/IPs per destination
and eight content prefixes. Exact URL, port, address and prefix semantics are
also checked by the transport before any connection. Version 1 remains the
explicit static profile; advanced fields cannot silently change its authority.

### Azure qualification boundary

Azure's [identity authentication](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-authentication)
and [managed identity](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-authentication-managed-identity)
options are provisioned outside LSF. An ACA identity used by the platform to pull
a runtime image does not supply credentials to this package client. Give the CI
package publisher its own approved repository permissions and private credential
delivery. Capture provider output directly into a protected file in the job;
disable command tracing and avoid displaying token responses.

The CLI implementation does not establish ACR compatibility. Actual ACR
qualification must record immutable package/evidence push and digest pull,
subject verification, short-lived identity expiry/renewal, denied scope and
addresses, DNS rotation, applicable redirects and unavailable endpoints. Mark
features unused by that specific topology as unused. Do not copy a local Harbor
or TLS-test-peer result into an Azure receipt. The registry support matrix stays
unchanged until that real run passes.

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
printable ASCII; epochs are positive `u64`. The `BearerChallenge` Rust
constructor requires explicit `identity` and `actions`. Share one `HttpOciRegistry` owner or its
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
python tools/run_harbor_registry_tests.py --output target/harbor-receipt.json
```

Run the owned integration fixtures on Linux x86_64 with Docker. For the static
Zot profile, follow the [prepared registry check](oci-registry.md#run-the-real-registry-check);
that runner requires an explicit Cargo test inventory.

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

## Run the CLI on the real local registry

The CLI qualification uses the same owned Harbor instance and a fresh project
robot with pull/push scope. On a Linux test host with the repository's Node.js,
Python and Rust tools installed, run:

```sh
cargo build --locked --package latent --bin latent
python tools/run_harbor_registry_tests.py --network --cli target/debug/latent --output target/harbor-cli.json
```

The runner builds two signed static packages with the CLI and ordinary Node.js
tools, pushes packages and evidence to Harbor, pulls immutable digests, and
verifies the exact subjects with explicit publisher/builder policy. It uses no
Rust application build and no Azure resource. A source-built CLI receipt does
not claim authentication as a published release.

Credentials live only in private fixture files, never command arguments or the
public receipt. The project robot expires after one day and the owned registry
is destroyed when the bounded run ends. A real deployment must provision and
rotate its own least-privilege package-client credential separately from any
container-image pull identity. Do not place it in Terraform state or copy test
identities into a deployment.

Each CLI process owns a fresh token cache. Expiry/refresh within an operation,
DNS rotation and credential-free redirects retain their separate real TLS/DNS
conformance tests; the Harbor drill does not claim to induce all of them. This
specific topology uses local registry storage and disables redirects. It does
check rejected DNS address authority, wrong TLS trust, invalid credentials,
foreign-project scope, pull-only writes and a refused endpoint. Failed writes
are never replayed by the drill; follow the immutable-digest recovery contract.
