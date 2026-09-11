# Architecture Decision Records

ADRs record decisions that constrain implementations and compatibility. Accepted ADRs may be superseded only by another ADR.

Acceptance records architectural direction, not feature availability. Phase 1
and its performance extension are complete; OCI supply-chain integration,
general capabilities, state/effects, clustered control, and fixed external
execution hosts remain future implementation work. The
[roadmap](../docs/roadmap.md) and [completion report](../docs/phase-1-extension-completion.md)
identify the delivered boundary without changing these decisions.

[ADR-0019](0019-separate-package-identity-from-component-identity.md) defines the
Phase 2 package identity and format foundation while preserving Phase 1 component
identities. The bounded format codec does not itself establish publisher trust.
