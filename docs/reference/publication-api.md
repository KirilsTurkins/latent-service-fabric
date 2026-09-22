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

| Client/server combination | Supported behavior |
| --- | --- |
| Legacy client, legacy server | Existing component fields retain their original meaning. |
| Legacy client, upgraded server | Unique component selection works; a fresh ambiguous selection fails without listing candidates. |
| Legacy operation replay, upgraded server | The retained tenant/operation association returns original history; it does not resolve the component again. |
| Explicit selector, upgraded server | Exact tenant publication is selected; an optional component assertion must match. |
| Explicit selector, old server | Empty legacy selector fails validation when the old server ignores the new field; no silent fallback. |
| Old binary, upgraded catalog | Unsupported publication/deployment table versions fail closed. Restore only a consistent stopped backup for downgrade. |

Phase 2 release roots are unsupported. The offline migrator has been removed;
follow the [fresh-state procedure](publication-catalog.md#supported-storage-and-fresh-state)
instead. A nonempty obsolete root cannot become a newly admitted publication
catalog. Current deployment operation-table recovery remains separate from
retired release-root formats.

## Rollout and invocation receipts

StartRollout uses the same explicit selector in its candidate Deployment. Its
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

The [SDK models](../../sdk/README.md) expose `PublicationRef`,
`PublicationIdentity` and optional invocation publication IDs. The obsolete
component-or-publication `ReleaseSelector` has been removed from all six
facades and generated common profiles. Requests use the method's exact
publication reference. This does not add a direct Invoke selector.
Executable clients reuse the authoritative Protobuf identities.

The bounded [publication workflow](../../tools/run_publication_workflow.py) runs
real CLI and node processes against fresh signed test packages. Its fixture
exporter corrects an embedded SBOM while retaining identical Wasm and capsule
metadata. It publishes both packages independently in two tenants, deploys every
exact publication, invokes it, restarts and inspects/replays original operations,
revokes one candidate, rolls back to its eligible captured base, renews another
tenant's evidence, and restarts again. It also checks component-only request rejection, foreign
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
