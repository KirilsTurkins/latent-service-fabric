# ADR-0024: Bind SBOM inventory through package content

- Status: accepted
- Date: 2026-09-12
- Issue: #145

## Context

An SBOM that embeds its final package manifest digest cannot also be a layer of
that package: each digest would depend on the other. A registry referrer alone
also does not authenticate an inventory. Another publisher can attach unrelated
claims to a public subject without controlling its existing package bytes.

The packaging API already distinguishes exact received package bytes from
untrusted metadata, and the observed build recipe captures selected source,
compiler outputs, WIT inputs and tool identities. This supports a useful input
inventory without claiming to reconstruct the complete linked program or perform
license compatibility and vulnerability analysis.

## Decision

Use one bounded, closed CycloneDX JSON 1.6 profile generated before package
assembly. Its root records logical package identity, never final `PackageDigest`.
Embed its exact bytes at `package/sbom.cdx.json` with media type
`application/vnd.cyclonedx+json`. Exclude that file and the generated packaging
receipt from output inventory coverage to prevent self-reference. Record the
limited coverage explicitly.

The package manifest binds the embedded SBOM through its content descriptor.
Package inspection validates independently checkable component, WIT and output
asset identities against the bundle, rejects malformed occupancy of the reserved
path, and retains a private bounded summary. Inspection preserves received SBOM
bytes. Metadata that packaging canonicalizes must not be labeled as an unchanged
output solely because its original source was observed.

Use the identical embedded bytes as the existing detached SBOM referrer payload.
Its outer subject supplies the now-known exact package media type, digest and
size. Check both the subject and embedded payload association. Association checks
establish no publisher or builder authority; admission combines them with current
authenticated package proofs under #146.

Reuse emitted Cargo compiler-artifact records to distinguish observed guest and
host build units. Export a normalized bounded inventory from selected manifests,
the captured lockfile, WIT lock, tool observations and package outputs. Keep one
CycloneDX encoder in Rust. Do not expose raw compiler messages, private cache
paths or credentials in the normalized inventory. Keep observed/declared source
attribution and unavailable license information explicit.

Validate supported license expressions with a pinned SPDX parser and identifier
list, preceded by byte, token and nesting limits. The initial profile accepts
expressions only; malformed input cannot fall back to a custom named license.
Do not infer license compatibility or fetch license text or advisory data.

Content policy specifies presence and attribution requirements for fixed roles.
Its canonical digest binds all choices. Admission owns policy replacement and
currentness; this module introduces no independent authority generation or trust
store.

## Consequences

Publisher signatures over the exact assembled package also bind its embedded
SBOM. Changing the inventory changes package identity and invalidates a proof for
the old package. Matching detached evidence supports discovery and association;
it cannot upgrade a declaration into an authenticated or complete dependency
inventory by itself.

The profile and offline upstream schema tests constrain interoperability while
bounded semantic checks enforce byte identities, unique properties and paths,
attribution consistency and resource budgets. Unsupported CycloneDX features
remain explicit errors. A future broader profile requires a deliberate version
change rather than accepting new fields silently.

See the [SBOM profile](../docs/component-development/sbom.md),
[package format](../docs/protocol/package-format.md) and
[observed build provenance](../docs/reference/build-provenance.md).
