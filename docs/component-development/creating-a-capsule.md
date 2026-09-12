# Creating a capsule

A capsule project defines a versioned WIT world, implements its exported interfaces in a supported guest language, declares only the platform imports it requires, compiles to a Component Model binary, and packages immutable metadata.

## Phase 1 assets and workflow

The completed Phase 1 workflow publishes locally trusted component bytes with a
validated capsule manifest and typed contract metadata. A deployment manifest
selects the release and its routes. Follow the executable
[standalone quickstart](../development/standalone-quickstart.md) for the maintained
echo component and the [management reference](../reference/management-services.md)
for publication validation.

The [echo fixture](../../examples/echo-contract/README.md) includes a Rust guest,
pinned build tooling and reproducibility checks. Its generated package is
executable on the standalone node; the checked-in `publish-release.json` is only
a schema-shape example with placeholder digests.

## Phase 2 packaging

The [deterministic packaging workflow](packaging.md) now builds and inspects
supplied components, capsule metadata, typed contracts and pinned WIT sources.
OCI transfer, publisher and independent builder verification, SBOM policy,
release lifecycle and rollout controls are implemented alongside it. The
packager consumes existing build output; it does not compile source, execute
package scripts, sign bytes or invent build provenance. The Phase 2 completion
gate (#158) is still pending.

```text
component.wasm
capsule manifest
WIT package and lock graph
SBOM
detached publisher signature and builder provenance
```

Use the [operator CLI](../reference/operator-cli.md) with explicit input roots:

```bash
latent package build --source package-source.json --input-root build-inputs \
  --sbom-inputs sbom-inputs.json --output-dir package
latent package inspect package --output json
latent package verify package --evidence-index evidence/index.json \
  --evidence-root evidence --policy admission-policy.json --tenant examples \
  --output json
```

The output directory must be new. Its `manifest.json`, `config.json` and declared
`layers/` form an immutable package. Detached evidence has a separate bounded
index and directory. Inspect establishes content and supported contract
structure, not publisher trust or execution authorization. Verify evaluates the
explicit local policy once; it opens no node catalog, issues no execution grant
and does not check the target node's runtime profile or durable policy floors.
The node independently applies its current policy and release lifecycle.

Transfer a package and its evidence through an explicit registry profile with
`package push`/`package pull`; retain returned immutable digests when a transfer
is partial or uncertain. Publish to an enforced node with
`release publish-package PACKAGE --evidence EVIDENCE/index.json --operation-id ID
--expected-generation 0`. That command reads evidence files relative to the
index's parent. Node tokens and registry credentials use separate private files;
the CLI never mounts or edits the node's authoritative catalogs. See
[operator workflows](../phase-2-operator-workflows.md) for exact formats and bounds.

A deployment selects the admitted component digest, grants and resource limits.
Managed Apply/Delete requires both an object generation and the catalog state
version returned by `deployment get ID --operation-snapshot`. A rollout Start
also requires the candidate manifest's `spec.route.weight` to equal the first
declared stage; the CLI does not rewrite it. Compatibility checks and a successful
local verification do not override revocation or authorize a rollback target.

The [bounded operator workflow](../development/standalone-quickstart.md#bounded-phase-2-operator-workflow)
builds two tiny compatible packages and checks actual registry, CLI and node
behavior. Its fresh signatures accompany synthetic test observations. Use the
separate observed-build workflow when evaluating real source and tool evidence.

## Design rules

- No background threads or listeners.
- No assumption that process-local state survives a call.
- No unrestricted filesystem, environment, network, or secret access.
- Every external dependency is an imported WIT contract.
- Domain errors are explicit WIT variants.
- Platform failures remain separate.

Phase 1 provides activation context, clocks, resource budgets and structured
logging. Calls execute within finite activation budgets; persistent guest state
and background work are unavailable. General capabilities, including blob
storage, belong to Phase 3. Stable idempotency for state/effects and durable
workflow suspension belong to later phases; see the [roadmap](../roadmap.md).
