# Architecture Decision Records

ADRs record decisions that constrain implementations and compatibility. Accepted ADRs may be superseded only by another ADR.

Acceptance records architectural direction, not feature availability. Phase 1,
its performance extension, and Phase 2 are complete. Verified package admission,
OCI transfer, publisher/builder/SBOM policy, isolated compilation, bounded native
reuse and controlled rollout now have delivered implementations. General
capability providers and application hosting enter Phase 3; state/effects,
clustered control and fixed external execution hosts retain their later scope.
The [roadmap](../docs/roadmap.md) and
[Phase 2 completion report](../docs/phase-2-completion.md) identify the delivered
boundary. Dated implementation snapshots within ADRs keep their original context.

[ADR-0019](0019-separate-package-identity-from-component-identity.md) defines the
Phase 2 package identity and format foundation while preserving Phase 1 component
identities. The bounded format codec does not itself establish publisher trust.

[ADR-0020](0020-validate-supplied-components-without-executing-guests.md) implements
deterministic supplied-artifact packaging and bounded structural validation
without compiling or invoking guests.

[ADR-0021](0021-bound-registry-authority-and-transfer-ownership.md) defines scoped
authenticated OCI transfers, retained download budgets and owned upload cleanup.

[ADR-0022](0022-bind-publisher-proofs-to-current-explicit-trust.md) defines bounded
package signatures and publisher proofs bound to explicit current policy and
revocation snapshots, separate from tenant/catalog admission.

[ADR-0023](0023-bind-build-attestations-to-observed-inputs-and-builder-trust.md)
defines observed committed-source builds and separately approved builder proofs,
with exact package/component/source associations and bounded current trust.

[ADR-0024](0024-bind-sbom-inventory-through-package-content.md) defines bounded
declared-input SBOMs embedded before package assembly, exact detached associations
and content policy separate from publisher authentication and admission currentness.
