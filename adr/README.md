# Architecture Decision Records

ADRs record decisions that constrain implementations and compatibility. Accepted ADRs may be superseded only by another ADR.

Acceptance records architectural direction, not feature availability. Phase 1
and its performance extension are complete; durable catalog admission,
general capabilities, state/effects, clustered control, and fixed external
execution hosts remain future implementation work. The
[roadmap](../docs/roadmap.md) and [completion report](../docs/phase-1-extension-completion.md)
identify the delivered boundary without changing these decisions.

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
