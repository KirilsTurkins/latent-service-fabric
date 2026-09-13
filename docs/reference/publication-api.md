# Publication selection in management APIs

The publication API implements the public identity separation in
[RFC-0002](../../rfcs/0002-tenant-scoped-publication-identity.md). A component
digest still identifies executable bytes. A package digest identifies immutable
package content, and a publication reference identifies its catalog association.
None of these identifiers is an execution grant.

## Release requests and results

`PublicationRef` contains an exact `publication:sha256:` ID and its tenant.
Public requests require that tenant to match the authenticated scope before
lookup. Use either the existing nonempty component `digest` or `publication`.
With an explicit publication, leave `digest` absent or empty. Two selectors,
an empty/invalid reference, or a mismatched reference tenant are invalid; the
server never falls back to the component field.

Get, lifecycle inspection, revoke, retire and evidence renewal accept the exact
reference. Release descriptors, lifecycle records and operation receipts report
their captured publication. Descriptors also expose a package digest when the
source is an actual package; a trusted-local upload does not invent one.
Operation lookup and replay retain the original association after coexistence.

The CLI accepts `latent release get --publication PUBLICATION_ID`, and the same
selector on `lifecycle`, `revoke`, `retire` and `renew-evidence`. Tenant comes from
the selected client profile. The existing positional component digest remains
available. Mutation operation IDs and generation comparisons remain explicit.
JSON output keeps publication, package and component identities separate and
preserves counters as decimal strings.

Fresh component-only requests require exactly one association in the authorized
scope, including revoked/retired associations when counting ambiguity. Multiple
associations return `state-conflict`, reason `publication-selector-ambiguous`,
with `retryable: false`. Foreign and missing IDs both return `NotFound` within the
authorized scope; errors do not enumerate candidates.

## Deployment requests and results

On Apply input, `Deployment.publication` selects a publication and
`Deployment.release_digest` must be empty. Optional
`ApplyDeploymentRequest.expected_component_digest` asserts which executable
that publication must contain. It is a checksum assertion, not a second
selector. Without `publication`, the existing component field is the selector
and the new assertion must be absent. The server resolves the reference before
mutation; the catalog still rechecks current eligibility at commit.

On output, `Deployment.publication` reports the captured tenant publication,
while `release_digest` reports its component. Output-only
`requested_publication` preserves the caller's original explicit manifest
selector. It remains absent for a legacy manifest, even after the server captures
a publication. This keeps canonical manifests and their historical hashes stable.
Convert a response to an input deliberately: choose one selector and omit
`requested_publication`. Old generated clients ignore these additive fields.

Deployment JSON continues to use `spec.release` plus optional `spec.publication`
as described in the [runtime contract](publication-runtime.md). The CLI converts
the former into a component assertion when the latter is present. Its output
reports the captured publication separately from the original manifest, and it
rejects a reply that substitutes another publication with the same component.

Get, bounded lists, managed Apply replies and operation lookup use the captured
association. A legacy reapplication of an existing deployment retains its pin;
a new ambiguous component-only deployment is rejected. Managed replay preserves
the original manifest, publication, receipt and generations even after deletion
or revocation. Replay does not install the historical deployment again.

The internal trusted-local, unscoped compatibility path remains distinct from
tenant admission. Such results retain their component identity and omit the
public tenant reference; their exact unscoped pin remains inside the catalog and
operation history. An unscoped ID cannot be submitted as a tenant publication.

## Recovery and compatibility

Deployment operation table format 2 stores the full captured publication
reference alongside each unchanged format-1 receipt. The enclosing catalog
checksum covers that association. Receipt canonical bytes and `receipt_digest`
retain their previous meaning; they do not alone authenticate the additive
publication reference. Protected catalog ownership remains required.

Startup upgrades a format-1 operation table using a matching retained object
revision or the artifact catalog's retained legacy association. Unique recovery
is allowed where no historical mapping exists; ambiguous history is rejected.
The upgrade is durably committed before routes are exposed and preserves
request hashes, receipt bytes, CAS versions and object generations. A format-5
deployment envelope can therefore still need an operation-table upgrade. Older
binaries reject table format 2; preserve a stopped backup before upgrading.

The [publication schema](../../schemas/publication-ref.schema.json), release
lifecycle schema, Protobuf descriptor contract and compatibility fixtures cover
presence and additive field meanings. Generated Rust bindings are built from
the authoritative Protobuf files. Public rollout and six-language SDK integration
remain part of the same Phase 3 ticket #267; these release/deployment additions
alone do not close that ticket or announce a new executable SDK client.
