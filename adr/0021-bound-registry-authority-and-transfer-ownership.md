# ADR-0021: Bound registry authority and transfer ownership

- Status: Accepted
- Date: 2026-09-12
- Related: [ADR-0019](0019-separate-package-identity-from-component-identity.md), [ADR-0020](0020-validate-supplied-components-without-executing-guests.md), [#142](https://github.com/KirilsTurkins/latent-service-fabric/issues/142)

## Context

Immutable OCI package formats and deterministic local packaging now exist.
Network distribution must preserve those byte associations under mutable tags,
untrusted responses, cancellation and limited resources. An unrestricted generic
HTTP client would add redirect, credential, resolver and retention authority not
represented by the existing package interfaces.

## Decision

Implement a shared `HttpOciRegistry` for one explicit HTTPS origin and repository.
Every reference and followed URL stays in that scope. Require approved static
socket addresses for hostnames, keeping runtime DNS work outside transfer
ownership. Use pinned rustls/ring and Mozilla roots plus bounded explicitly
approved DER roots, with certificate and hostname validation enabled. Permit
HTTP only for an explicit numeric-loopback test configuration.

Support anonymous access, scoped Basic credentials and preissued Bearer tokens.
Do not automatically request tokens, consult credential helpers, use environment
proxies, follow redirects, retry requests or decompress bodies. Credential
diagnostics are redacted and network errors use fixed messages. Unsupported
registry behavior fails explicitly within this restricted profile.

Fetch a tag manifest once and pin its exact digest before following associated
content. Validate declared sizes, media types and actual hashes while bounding
streaming materialization. A high-level complete pull retains raw-byte and
package-slot leases until its owning result is dropped. The existing low-level
owned-return APIs transfer retention responsibility to callers; their lifetime
cannot be counted by an adapter that no longer owns the data.

Push checked blobs first and the original manifest last. Preserve opaque upload
query state without granting authority to another origin or repository. One
bounded shared worker owns upload initiation and abandoned-session cleanup.
Cancellation cannot release an active session's permit before its owned cleanup
finishes. Unknown sessions whose URL never arrived require registry-side expiry.
Shutdown and cleanup deadlines report incomplete work honestly.

Require native OCI 1.1 referrers. Bound response bytes, pages, descriptors and
followed URLs; apply artifact-type filtering locally. A descriptor list is
discovery, not authenticated evidence or trust admission. The mutable referrers
tag fallback is deliberately unsupported: its concurrent update protocol would
require another explicit consistency contract. This restricted implementation
does not claim full OCI client fallback conformance.

## Consequences

Registry outages do not become an invocation dependency for already eligible
local catalog content. Registry transfer alone cannot publish or authorize a
release, and it cannot extend guest networking capabilities. Publisher trust,
evidence verification, durable cache/admission and rollout remain separate
Phase 2 tickets.

Some registries require separate token exchanges, object-store redirects or
legacy referrer fallback. They must use preissued credentials and this supported
profile, or wait for a separately designed authority/consistency extension.
Finite HTTP parser scratch, metadata, raw buffers and caller-owned copies remain
distinct; configured raw-byte leases are not a total process memory guarantee.

Validate the profile through a pinned disposable Zot minimal 2.1.18 registry using
real TLS/Basic authentication and tiny format fixtures, plus scripted adversarial
HTTP tests. CI caps container resources and removes only the container whose
immutable ID and ownership label match its recovery record. No persistent
registry volume or load-benchmark evidence is needed. The
[registry reference](../docs/reference/oci-registry.md) documents configuration,
limits, ownership and supported interoperability.
