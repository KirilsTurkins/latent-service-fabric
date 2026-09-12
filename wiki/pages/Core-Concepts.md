<!-- LSF-WIKI-MANAGED -->
# Core concepts

A service describes callable behavior. A release identifies immutable component bytes. Deployment and trust state decide whether those bytes may be selected and started now.

| Concept | Meaning |
| --- | --- |
| Package digest | Exact OCI package manifest identity, including the portable content graph. |
| Component release digest | Exact executable component identity; it is separate from the package digest. |
| Admission receipt | Historical proof of a checked package and configured policy association. |
| Execution eligibility | A sealed, current capability tied to the exact catalog owner, lifecycle generation and applicable trust authority. |
| Deployment generation | Version of one deployment object. |
| Route generation | Version of the atomically published routing snapshot. |
| State version | Catalog-wide compare-and-swap identity for managed Apply/Delete, including absent-object snapshots. |
| Operation ID | Caller-selected identity bound to the authenticated actor, tenant and exact normalized request. |
| Operation receipt | Retained committed result; finite history can instead report Unknown or Uncertain. |
| Activation | One admitted call, with its own fresh guest state and finite resource ledger. |
| Execution cell | A configured reusable execution slot, not a service-owned process. |
| Cache pin | Resource ownership over bytes or prepared code; it grants no trust or permission by itself. |

The resource model remains fixed runtime resources plus bounded metadata, active work and bounded caches. More dormant releases can consume more metadata and storage without allocating a dedicated guest heap.

Publisher authorization and builder authorization are separate. Signatures bind exact package/component associations. Provenance describes a bounded observed build; an SBOM describes declared or observed inventory. Neither an unchecked envelope nor an inventory association grants execution permission.

A canary snapshot is diagnostic. Promotion requires a sealed window from the configured owner, bound to the exact rollout revision, route generation, cohort and policy. A healthy-looking copied report cannot authorize a transition.

An activation ID supports correlation and retained status; it is not a transaction key for guest side effects. Likewise, an audit acknowledgement is not a deployment receipt, and an Unknown audit outcome does not prove rollback.

Authorities: [package format](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/protocol/package-format.md), [package admission](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/reference/package-admission.md), [release lifecycle](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/reference/release-lifecycle.md), [operator workflows](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-2-operator-workflows.md).
