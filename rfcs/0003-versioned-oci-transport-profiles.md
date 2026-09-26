# RFC-0003: Versioned OCI transport profiles

- **Status:** Accepted
- **Authors:** Latent Service Fabric maintainers
- **Created:** 2026-09-13
- **Target milestone:** Phase 3
- **Accepted by:** [ADR-0029](../adr/0029-separate-registry-authority-from-transport-profile.md)

## Summary

LSF will version OCI registry transport interoperability independently from the
permanent authority and ownership rules established by ADR-0021.

The already delivered registry behavior is named `lsf-oci-static-v1`. It remains
supported alongside the second opt-in profile,
`lsf-oci-bearer-v1`, for standard Bearer challenge authentication, bounded DNS
and explicitly authorized redirects. #269 owns token acquisition/refresh and
#270 owns DNS, redirect handling and the real-registry conformance matrix. Their
implementation and [exact evidence boundaries](../docs/reference/oci-network-profile.md)
are now documented separately; selection alone is not compatibility evidence.

Profile expansion never lets an untrusted registry response grant new network or
credential authority. Every token realm, DNS destination, redirect destination,
repository, action scope and credential source is intersected with explicit
operator policy before network work begins or credentials are forwarded.

## Motivation

ADR-0021 intentionally shipped a narrow OCI 1.1 client: one explicit origin and
repository, operator-supplied socket addresses for hostnames, anonymous/Basic or
preissued Bearer credentials, no runtime DNS, no redirects, no automatic token
service exchange, and native referrers only. That profile is useful and tested,
but several production registries require the standard challenge/token flow and
may use separate authorization or object-storage endpoints.

Those interoperability choices should not become permanent architectural
invariants. The invariants are instead the authority, identity, bounded ownership,
uncertain-write and admission boundaries that made the Phase 2 client safe.

The protocol references for this RFC are:

- OCI Distribution Specification 1.1.1:
  <https://github.com/opencontainers/distribution-spec/blob/v1.1.1/spec.md>
- Docker Registry v2 Bearer authentication flow:
  <https://docs.docker.com/reference/api/registry/auth/>
- Harbor v2.15.2 release, published 2026-07-02:
  <https://github.com/goharbor/harbor/releases/tag/v2.15.2>
- Harbor token-service documentation, which describes Registry v2 token
  authentication:
  <https://goharbor.io/docs/2.14.0/install-config/customize-token-service/>

The Harbor documentation version is evidence for the protocol shape, not an LSF
compatibility claim for Harbor 2.14. The selected Phase 3 conformance target is
Harbor 2.15.2 and must be exercised directly by #269/#270 before LSF reports that
profile as supported.

## Detailed contract

### Permanent registry invariants

These rules apply to every LSF OCI transport profile:

1. **Explicit registry and repository authority.** A transfer begins with a
   configured registry authority and one permitted repository. Tags are mutable
   selectors; durable package identity uses the exact resolved manifest digest.
2. **TLS identity remains authoritative.** Except for the existing explicit
   numeric-loopback test escape hatch, registry and token endpoints use HTTPS
   with hostname validation and configured trust roots. A resolved IP address does
   not replace the TLS server name.
3. **Server data cannot grant authority.** `WWW-Authenticate`, `Location`, `Link`,
   DNS replies and OCI manifests are untrusted protocol inputs. Following them
   requires a match against preconfigured authority.
4. **Credentials are provenance-bound.** Basic passwords, preissued Bearer tokens,
   refresh credentials and acquired access tokens have an explicit owner and
   allowed audience/repository/actions. They are never sourced from ambient
   credential helpers or environment proxy settings.
5. **One finite operation deadline.** Authentication, name resolution, connect,
   redirects, manifest/blob transfer, upload session work and referrer discovery
   consume the original absolute transfer deadline. A continuation does not reset
   the clock.
6. **Physical ownership controls refunds.** Socket permits, resolver work, token
   work, upload sessions, response buffers, raw-byte leases, cache work and
   cleanup reservations remain charged until actual retirement or an explicit
   bounded ownership transfer. Dropping a requesting future is not a refund.
7. **Uncertain mutations are not replayed blindly.** A lost/ambiguous response
   after an upload or manifest publication requires state/digest reconciliation.
   Automatic challenge or redirect handling may not silently replay an uncertain
   mutation as though no remote side effect occurred.
8. **Discovery is not trust.** Referrer descriptors identify candidate evidence;
   signature/provenance/SBOM verification, current trust policy and catalog
   admission remain separate owners.
9. **Registry work is shared node/developer-plane work.** No dormant deployment
   owns a resolver, token refresher, socket pool, timer, registry worker or cache.
   Any shared worker/cache cardinality is node-configured and finite.
10. **Unsupported behavior fails explicitly.** No profile falls back to a more
    permissive transport mode because a registry returned an unexpected challenge,
    URL, DNS answer or discovery result.

### `lsf-oci-static-v1` - delivered initial profile

This name describes the current `HttpOciRegistry` behavior without changing its
existing source API or compatibility:

- exact configured HTTPS origin and repository;
- hostname origins require up to 16 operator-approved `SocketAddr` values; no
  runtime DNS;
- credentials are anonymous, explicit Basic or preissued Bearer;
- no automatic token-service exchange or refresh;
- no redirects; upload `Location` and pagination `Link` continuations stay within
  the configured origin/repository and permitted operation path;
- native OCI 1.1 referrers are required for the complete supply-chain discovery
  profile;
- no legacy referrers-tag fallback;
- existing bounded transfer, upload cleanup, raw-byte and cache ownership rules
  remain unchanged.

The existing pinned Zot minimal 2.1.18 fixture is the conformance baseline for
this profile. It is the only named real-registry profile whose complete LSF
push/pull/native-referrer path is currently demonstrated by repository tests.

### `lsf-oci-bearer-v1` - selected Phase 3 profile

This profile requires the explicit #269/#270 implementation and validation. It
extends, rather than weakens, the permanent invariants. The network constructor
never silently upgrades an existing static caller.

Configuration must provide finite policy for:

- approved registry DNS names and/or literal addresses;
- approved HTTPS token authorities, independently from registry authority;
- credential provenance for token acquisition, including whether Basic or a
  refresh credential may be sent to a particular token authority;
- exact service/audience values when required by the selected registry;
- permitted repository plus pull/push action scopes;
- bounded DNS answer count/cache entries/TTL policy;
- permitted redirect authorities and operation classes (content read, upload
  continuation, token exchange), including explicit cross-origin credential
  forwarding rules;
- existing trust roots and transport/resource limits.

A Bearer challenge is accepted only if all of the following are true:

1. the challenge syntax and retained bytes are within finite limits;
2. the realm resolves to an explicitly approved HTTPS token authority;
3. the requested service/audience matches configured policy;
4. requested repository/action scope is no broader than the in-flight operation
   and configured repository authority;
5. the selected credential is approved for that token authority and tenant/node
   credential epoch;
6. token acquisition still fits the original transfer deadline and bounded
   pending-work/cache limits.

A token response is retained under a finite cache keyed by token authority,
registry audience/service, repository/actions, principal/credential identity and
credential epoch. Expiry/skew handling and equivalent acquisition coalescing are
bounded. Rotation invalidates future use without pretending already-running
network work disappeared.

DNS resolution is similarly bounded. Every connection validates the resulting
address against profile policy and still validates TLS against the configured
hostname. DNS rebinding, private/link-local/metadata-address bypass and unbounded
answer retention must fail closed.

Redirects are operation-specific. GET/HEAD content redirects, upload session
continuations and token service requests are not interchangeable authority.
Cross-origin registry credentials are never forwarded to object storage unless
that exact forwarding is explicitly authorized; the default is no forwarding.
Scheme downgrade, userinfo, unapproved authorities, repository escape and loops
are rejected under finite hop/URL/header limits.

### End-to-end deadline and bounded ownership

`RegistryLimits::operation_timeout` is the current outer operation budget and is
carried as one absolute deadline through the selected profile. Existing
`connect_timeout` and `request_timeout` remain inner ceilings; they may shorten a
stage but never extend the operation deadline. Abandoned known sessions transfer
to the existing reserved cleanup owner with its independent, finite
`cleanup_timeout`. This is cleanup-only DELETE ownership, not a renewed upload
budget or a replay of an uncertain mutation; capacity stays charged until it ends.

The Phase 3 implementation must place finite ceilings on at least:

- live registry operations and sockets;
- pending resolver jobs, answers and cache entries;
- pending token acquisitions/refreshes and retained token entries/bytes;
- redirect hops and retained redirect metadata;
- retained request/response header bytes;
- upload-session state and cleanup work;
- referrer pages/descriptors/bytes;
- raw transfer/cache bytes and retained package leases;
- shared blocking/network worker or task ownership used by the implementation.

A stage that times out or is cancelled retains its charged ownership until the
underlying work physically ends, a socket is closed, an upload cleanup owner
settles, or another explicitly bounded owner takes responsibility. A watchdog is
not evidence that cleanup occurred.

### Registry support matrix

The matrix distinguishes **delivered evidence** from **selected conformance
work**. A selected row is not a support claim until its required tests pass.

| Registry/version | LSF profile | Auth topology | Push/pull | Native referrers | Evidence status |
| --- | --- | --- | --- | --- | --- |
| Zot minimal 2.1.18, pinned image digest `sha256:f1ffb7a5bbddc0feea83646e29c587ecf39b3193733b447749d4c9ead111a395` | `lsf-oci-static-v1` | one ephemeral TLS loopback origin, explicit Basic credential | demonstrated | demonstrated | delivered repository fixture |
| Harbor 2.15.2 | `lsf-oci-bearer-v1` | private project, approved same-origin token realm, explicit DNS/TLS, local storage | demonstrated | demonstrated | owned fixture; redirect policy separately verified with controlled TLS peers |
| Distribution 3.1.1 | none for complete LSF evidence discovery | varies | package transfer can interoperate | current LSF docs record native referrers unavailable | explicit complete-profile exclusion |

The Harbor fixture is reproducible only when #270 records the exact Harbor 2.15.2
release/container identities it executed, creates disposable TLS and a disposable
private project/least-privilege credential, records the observed approved registry
and token authorities, uses bounded local container resources, and destroys only
resources owned by that run. Hosted credentials are not required for the baseline.

The conformance path must prove exact package push, digest-pinned pull and native
referrer evidence discovery. If Harbor 2.15.2 does not satisfy native referrers
under the tested topology, LSF must report that result and either keep Harbor as a
partial transport target or select another registry through a reviewed RFC/ADR
update. It must not silently enable mutable legacy fallback.

### Unsupported behavior

The following remain unsupported unless a later profile explicitly selects them:

- ambient credential helpers, cloud instance credentials or environment proxies;
- arbitrary challenge realms or credential forwarding learned from server data;
- unrestricted DNS, DNS results that bypass destination policy, or TLS hostname
  substitution with an IP address;
- arbitrary redirects, scheme downgrade, redirect credential forwarding by
  default, or unbounded hops;
- automatic retry of uncertain upload/finalization mutations;
- mutable legacy referrers-tag fallback;
- registry-specific artifact discovery that bypasses OCI association checks;
- treating registry authentication/discovery as publisher trust or catalog
  admission;
- per-service token refreshers, resolver pools, socket pools or registry workers.

A future mutable referrers-tag fallback requires a separate consistency decision
covering concurrent writers, lost updates and exact evidence association before
it can become a supported profile.

## Compatibility and migration

Existing `RegistryConfig` values and callers keep the behavior named
`lsf-oci-static-v1`; this RFC does not change their wire/API semantics. Operators
do not opt into DNS, token exchange or redirects merely by updating LSF.

#269/#270 may add an explicit profile selector or new configuration structure.
That selector must default existing callers to the static profile or require an
explicit migration with an equivalent fail-closed result. Unknown, partially
configured or unavailable profiles return a bounded configuration/profile error
before performing newly authorized network work.

Historical Zot evidence remains evidence for the static profile only. It cannot
be relabeled as proof for Bearer challenge, DNS or redirect behavior.

## Resource-allocation impact

No new runtime resources are introduced by this design document. The selected
profile permits future node-owned bounded resolver/token/connection metadata and
work queues. Their configured maxima are independent of deployment/service count.

The resident-resource invariant remains:

```text
fixed node runtime + active operations/activations + bounded shared caches/provider pools
```

Dormant services do not own registry workers, token refresh timers, DNS caches or
sockets.

## Security and trust-boundary impact

The second profile increases protocol reachability, so it narrows authority at
each new hop rather than delegating authority to the registry:

- registry authority does not imply token-authority trust;
- token authority does not imply repository/action expansion;
- DNS data does not imply destination permission;
- redirect data does not imply destination or credential-forwarding permission;
- token possession does not imply publisher/build/SBOM trust;
- successful registry transfer does not imply catalog/execution admission.

Secrets and Bearer tokens must remain redacted from diagnostics. Sensitive URL
query data from token/upload flows must not be emitted verbatim.

## Failure semantics

Profile selection/configuration failures occur before profile-specific network
work. Authentication denial, scope mismatch, unapproved realm/destination,
resolver failure, redirect denial, deadline expiry, oversized responses and
cleanup failure remain explicit typed platform/registry failures rather than
fallback triggers.

An operation deadline or caller cancellation stops admission of new continuation
work but does not claim that an already-started socket, upload cleanup or token
request physically ended. Its owner remains charged until retirement.

## Alternatives

### Make DNS/token/redirect support universal

Rejected. It would make the narrow Phase 2 authority contract disappear and make
compatibility/security behavior depend on server responses rather than selected
operator policy.

### Keep the static profile forever

Rejected. Standard Bearer challenge authentication is a common Registry v2
interoperability requirement, and keeping it permanently out of scope would turn
a Phase 2 delivery simplification into an accidental product invariant.

### Enable legacy referrers fallback immediately

Rejected. The OCI 1.1 fallback uses mutable tags and concurrent-update behavior
that needs an explicit consistency contract. Phase 3 can expand transport
interoperability without weakening evidence association.

## Validation plan

#269 must exercise malicious and valid Bearer challenges, audience/scope narrowing,
credential rotation, expiry, acquisition coalescing, cancellation and ambiguous
write boundaries, then demonstrate authenticated transfer against the selected
Harbor fixture.

#270 must exercise bounded DNS, rebinding/private-address policy, TLS hostname
validation, redirect classes/credential forwarding, loops and cancellation. Its
real-registry matrix must run exact push, digest pull and native referrers against
Zot static-v1 and the selected Harbor 2.15.2 topology, recording exact fixture
identities and limitations.

The current static-profile unit/integration tests remain regression coverage. The
new profile cannot replace or weaken them.

## Open questions

None block this decision. The exact Rust configuration types, cache sizes and
error-detail names belong to #269/#270 implementation review as long as they obey
these fixed authority, deadline and ownership rules.
