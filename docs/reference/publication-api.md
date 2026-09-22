# Publication selection in management APIs

The publication API implements the public identity separation in
[RFC-0002](../../rfcs/0002-tenant-scoped-publication-identity.md). A component
digest still identifies executable bytes. A package digest identifies immutable
package content, and a publication reference identifies its catalog association.
None of these identifiers is an execution grant.

## Release requests and results

`PublicationRef` contains an exact `publication:sha256:` ID and its tenant.
Public release-management requests require an exact publication whose tenant
matches the authenticated scope before lookup. Missing or invalid references
are rejected. The obsolete component-only `digest` input is removed; field 1
and its name are reserved in the four release query/mutation request messages.

Get, lifecycle inspection, revoke, retire and evidence renewal accept the exact
reference. Release descriptors, lifecycle records and operation receipts report
their captured publication. Descriptors also expose a package digest when the
source is an actual package; a trusted-local upload does not invent one.
Operation lookup and replay retain the original association after coexistence.

The CLI accepts `latent release get --publication PUBLICATION_ID`, and the same
selector on `lifecycle`, `revoke`, `retire` and `renew-evidence`. Tenant comes from
the selected client profile. Positional component digests are rejected before
network dispatch. Mutation operation IDs and generation comparisons remain explicit.
JSON output keeps publication, package and component identities separate and
preserves counters as decimal strings.

Retain the publication ID returned by admission or choose an exact entry from
the authenticated release list. A component checksum cannot identify an
association, even when the current catalog happens to contain only one match.
Foreign and missing publication IDs both return `NotFound` within the authorized
scope; errors do not enumerate candidates.

## Deployment requests and results

On Apply input, `Deployment.publication` is required and
`Deployment.release_digest` must be empty. Optional
`ApplyDeploymentRequest.expected_component_digest` asserts which executable
that publication must contain. Missing publication references and component-only
requests fail before lookup or mutation, even when only one publication exists.
The server resolves the exact reference before mutation; the catalog rechecks
current eligibility at commit.

On output, `Deployment.publication` reports the captured tenant publication,
while `release_digest` reports its component. Output-only `requested_publication`
preserves the caller's original manifest selector. To reapply a response, retain
its publication, clear `release_digest`, omit `requested_publication`, and pass
the component as `expected_component_digest` when that assertion is wanted.

CLI apply and rollout candidate manifests require both `spec.release` and
`spec.publication`. Select the publication returned by admission; the CLI converts
`spec.release` into a checksum assertion and rejects a missing publication before
network dispatch. It also rejects a reply that substitutes another publication
with the same executable component.

Get, bounded lists, managed Apply replies and operation lookup use the captured
association. Managed replay preserves the original manifest, publication,
receipt and generations even after deletion or revocation. Replay does not
install the historical deployment again. An unscoped local publication cannot
be submitted as a tenant publication or selected through a component fallback.

## Recovery and compatibility

Deployment operation table format 2 stores the full captured publication
reference alongside each unchanged format-1 receipt. The enclosing catalog
checksum covers that association. Receipt canonical bytes and `receipt_digest`
retain their previous meaning; they do not alone authenticate the additive
publication reference. Protected catalog ownership remains required.

Startup upgrades a format-1 operation table using a matching retained object
revision or a unique current scoped publication. Ambiguous history is rejected;
archived Phase 2 migration mappings are not read.
The upgrade is durably committed before routes are exposed and preserves
request hashes, receipt bytes, CAS versions and object generations. A format-5
deployment envelope can therefore still need an operation-table upgrade. Older
binaries reject table format 2; preserve a stopped backup before upgrading.

The [publication schema](../../schemas/publication-ref.schema.json), release
lifecycle schema, Protobuf descriptor contract and compatibility fixtures cover
presence and additive field meanings. Generated Rust bindings are built from
the authoritative Protobuf files. All six SDKs expose matching interface models;
this does not announce a new executable SDK client.

| Request | Current behavior |
| --- | --- |
| Missing publication or component-only selector | Rejected before lookup or mutation. |
| Exact publication with optional component assertion | Selects the authenticated tenant publication; an assertion must match. |
| Exact operation replay | Returns captured history without applying it again. |
| Unsupported stored catalog format | Rejected without implicit catalog admission; use fresh alpha state. |

Phase 2 release roots are unsupported. The offline migrator has been removed;
follow the [fresh-state procedure](publication-catalog.md#supported-storage-and-fresh-state)
instead. A nonempty obsolete root cannot become a newly admitted publication
catalog. Current deployment operation-table recovery remains separate from
retired release-root formats.

## Rollout and invocation receipts

StartRollout requires the same exact selector in its candidate Deployment. Its
optional `expected_candidate_component_digest` is a checksum assertion, with
an empty candidate `release_digest`, just as on Apply. CLI candidate manifests
retain `spec.release` and `spec.publication`; the CLI constructs that request.
Get, list, operation lookup and rollback preserve the captured base and candidate
publication IDs, including when both have the same component digest. Revoking
the candidate does not revoke the base. Historical replay returns its original
receipt without installing that candidate again. Status `objects` contains the
currently surviving objects in the authenticated tenant, from zero to two. The
historical base/candidate remain visible after completion, rollback or deletion;
reusing an old object ID in another tenant does not disclose its generation.

Rollout status and receipts expose `publication_id`, `base_publication_id` and
`candidate_publication_id` as applicable. These are source identities, including
a possible internal unscoped source; they do not assert tenant admission. Tenant
scope on the enclosing operation still controls access. Rollout receipt canonical
bytes remain unchanged. Their retained version-2 plan digest binds both captured
IDs; recovery hydrates additive receipt fields from that bounded retained plan.
Audit records also carry the captured pair. Pre-upgrade audit attempts retain
their original bytes and can reconcile without invented historical fields.

InvokeResponse field 10, optional `publication_id`, reports the actual source
captured by route resolution. Its existing `release_digest` field still means
component bytes. Publication selection happens through the deployed revision and
route; an ID in a receipt grants no direct execution permission. Currentness is
checked at activation start. A failure before route resolution has no publication
or revision pin. An old response may omit the publication; a present empty or
malformed ID fails validation. CLI JSON reports `resolvedRevision.publicationId`
without converting 64-bit generations or consumption into floating point.

## Six-language models and operator verification

The [SDK models](../../sdk/README.md) expose `PublicationRef`, `ReleaseSelector`,
`PublicationIdentity` and optional invocation publication IDs. ReleaseSelector
is a transport-neutral choice that an eventual client maps to the method's
legacy digest/publication fields. It does not add a direct Invoke selector.
Phase 3 SDK/profile and executable-client work must reuse these identities and
the authoritative Protobufs instead of defining another release identity.

The bounded [publication workflow](../../tools/run_publication_workflow.py) runs
real CLI and node processes against fresh signed test packages. Its fixture
exporter corrects an embedded SBOM while retaining identical Wasm and capsule
metadata. It publishes both packages independently in two tenants, deploys every
exact publication, invokes it, restarts and inspects/replays original operations,
revokes one candidate, rolls back to its eligible captured base, renews another
tenant's evidence, and restarts again. It also checks legacy ambiguity, foreign
versus missing references, audit identities and clean process reaping.

CI runs this against its existing built binaries and an explicit fresh fixture:

```sh
LSF_OPERATOR_FIXTURE_ROOT="$FIXTURE" python3 tools/ci_rust_artifacts.py \
  --inventory "$INVENTORY" --suite publication-fixture
python3 tools/run_publication_workflow.py --cli target/debug/latent \
  --node target/debug/latentd --fixture-root "$FIXTURE" --source-commit "$GITHUB_SHA"
```

`$FIXTURE` must be a nonexistent child of an owned private temporary directory.
The runner requires Linux and Python 3.13, caps itself at 180 seconds and 160 CLI
processes, removes temporary node data and emits a receipt of at most 64 KiB.
The fresh exporter supplies synthetic signed test observations, not production
build provenance. No registry or 100,000-request load is involved. For an upgrade,
stop the node, back up catalogs and protected trust/configuration files, inspect
the listed publication/package/component associations, migrate manifests to the
exact desired IDs and restart after the enforced admission clock floor (up to
five seconds after stopping the prior owner). Keep original operation IDs for
recovery; do not
retry an uncertain mutation under a new ID merely because a response was lost.
