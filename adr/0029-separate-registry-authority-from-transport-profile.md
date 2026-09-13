# ADR-0029: Separate registry authority from transport profile

- **Status:** Accepted
- **Date:** 2026-09-13
- **RFC:** [RFC-0003](../rfcs/0003-versioned-oci-transport-profiles.md)
- **Successor to:** [ADR-0021](0021-bound-registry-authority-and-transfer-ownership.md)

## Context

ADR-0021 delivered a deliberately restricted OCI transport with exact registry
and repository authority, bounded transfer/cleanup ownership, static approved
addresses, preissued credentials, no redirects and native OCI 1.1 referrers.
Those choices made the Phase 2 delivery auditable, but standard Registry v2 Bearer
challenge authentication and some real registries require additional bounded
transport behavior.

The permanent security boundary is not "never use DNS/token services/redirects".
It is that untrusted protocol data cannot grant endpoint, credential, repository
or resource authority, and that every started operation remains finitely owned
until physical retirement.

## Decision

Separate permanent OCI registry invariants from versioned transport profiles.

The permanent invariants from ADR-0021 are:

- exact configured registry/repository authority and digest-pinned immutable
  package identity;
- TLS identity and explicit trust roots, except the existing numeric-loopback test
  escape hatch;
- no authority expansion from challenges, DNS replies, redirects, links,
  manifests or other server-controlled data;
- provenance-bound credentials and redacted sensitive diagnostics;
- one original finite transfer deadline across continuations;
- finite socket/work/buffer/cache/upload-cleanup ownership retained until actual
  retirement or explicit bounded transfer;
- no blind replay of uncertain mutations;
- evidence discovery remains separate from signature/provenance/SBOM verification
  and catalog/execution admission;
- shared node/developer-plane resources remain bounded independently of dormant
  service count;
- unsupported or unavailable profile behavior fails explicitly rather than
  silently downgrading or broadening authority.

[RFC-0003](../rfcs/0003-versioned-oci-transport-profiles.md) names two profiles:

- `lsf-oci-static-v1` is the **delivered** profile matching current
  `HttpOciRegistry`: operator-supplied addresses, anonymous/Basic/preissued Bearer,
  no runtime DNS/token exchange/redirects, and native OCI 1.1 referrers.
- `lsf-oci-bearer-v1` is the **selected but not yet supported** Phase 3 profile.
  It may add explicitly approved Bearer token authorities, bounded DNS and
  operation-specific authorized redirects while retaining every permanent
  invariant above.

The static profile keeps the pinned Zot minimal 2.1.18 fixture as its demonstrated
complete push/pull/native-referrer baseline.

Harbor 2.15.2 is selected as the additional real-registry conformance target for
`lsf-oci-bearer-v1` because it uses Registry v2 token authentication. Selection is
not a compatibility claim. #269/#270 must execute authenticated exact push,
digest-pinned pull and native-referrer evidence discovery and record the tested
fixture identities/topology before Harbor or `lsf-oci-bearer-v1` is documented as
supported.

Distribution 3.1.1 remains an explicit complete-profile exclusion under the
current LSF evidence-discovery requirement because the repository's existing
registry reference records that its tested surface does not expose native OCI
1.1 referrers. Package-transfer interoperability alone is not full supply-chain
registry compatibility.

Mutable legacy referrers-tag fallback remains unsupported and requires a separate
consistency decision before selection.

## Implementation ownership

This ADR does not implement new network authority.

- #269 owns bounded `WWW-Authenticate: Bearer` parsing, approved token-service
  acquisition/refresh, scope/audience narrowing, credential epochs, token cache
  bounds and ambiguous-write behavior.
- #270 owns bounded DNS/cache work, connected-peer policy, authorized redirects,
  credential-forwarding rules and completion of the selected real-registry
  conformance matrix.

Existing callers remain on `lsf-oci-static-v1`. Future configuration must make
profile selection explicit and fail before newly authorized network work if the
requested profile is unknown, partially configured, unavailable or unsupported.

## Deadline and ownership boundary

`RegistryLimits::operation_timeout` remains the outer transfer budget. Token
acquisition, resolution, connect, redirects, uploads, content transfer and
referrer discovery consume the same original absolute deadline. Per-connect,
per-request and cleanup timeouts can shorten a stage but cannot reset that
budget.

Resolver jobs/answers/cache entries, token jobs/cache entries, sockets, redirects,
request/response metadata, upload sessions, retained bytes, package leases and
cleanup owners require independent finite ceilings. Cancellation or timeout can
stop new continuation work, but it is not evidence that already-started physical
work ended or that its reservation can be refunded.

## Security consequences

The Bearer profile adds reachable protocol stages, not ambient authority:

- registry authority does not imply trust in an arbitrary token realm;
- a challenge cannot broaden repository/action scope;
- DNS results cannot authorize otherwise forbidden peers;
- redirect URLs cannot authorize destinations or credential forwarding by
  themselves;
- acquired tokens do not establish publisher identity or package admission.

Credential helpers, environment proxies, arbitrary realms, unrestricted DNS,
unrestricted redirects, blind uncertain-write retries and per-service refresh or
resolver workers remain unsupported by these profiles.

## Resource consequences

No runtime resource is added by this decision alone. #269/#270 may add only
node-owned bounded shared work/cache capacity. Dormant deployments own no token
refreshers, DNS workers, registry sockets or timers.

The existing resource invariant remains:

```text
resident resources = fixed node runtime + active operations/activations + bounded shared caches/provider pools
```

## Compatibility and evidence

ADR-0021's delivered implementation and historical Zot evidence remain valid and
are reclassified as evidence for `lsf-oci-static-v1`; they are not evidence for
DNS, Bearer challenge acquisition or redirects.

The Harbor row remains selected-only until #269/#270 pass. Failed or adverse
conformance results must be retained as limitations rather than converted into a
support claim by changing profile wording.

The OCI package format, publisher/build/SBOM verification, catalog admission,
ordinary invocation availability and guest networking authority are unchanged by
this decision.
