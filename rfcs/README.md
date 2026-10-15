# Requests for Comments

Use an RFC for unresolved changes to WIT, Protobuf, schemas, core invariants, execution semantics, security boundaries, or compatibility promises. Accepted decisions should be summarized by an ADR.

Use the [template](0000-template.md) to state a concrete decision, alternatives,
failure/resource/security consequences, validation and unresolved questions.
Research records evidence and explores feasibility; an RFC proposes a contract;
an ADR records an adopted decision. None alone establishes implemented support.

## Draft research proposals

The following drafts are based on the documentation/research stack at
[`784cb29b`](https://github.com/KirilsTurkins/latent-service-fabric/tree/784cb29b2bff9c7298f131d3f5e1c95d5f967b08),
reviewed on 2026-10-15. They introduce no executable feature or accepted decision.
Existing ADRs apply until explicitly changed; production research promotion
still requires a scoped ADR and conformance evidence.

| Draft | Decision proposed for review |
| --- | --- |
| [RFC-0006: Durable workflow segments and continuation handoff](0006-durable-workflow-segments-and-continuation-handoff.md) | Finite durable segments, conditional checkpoint/wait commitment, exclusive resume and original-owner retirement; compiler capture is a later frontend. |
| [RFC-0007: Boundary-preserving local-call specialization](0007-boundary-preserving-local-call-specialization.md) | Exact reusable candidates and per-call authority/failure/accounting checks, initially retaining child Stores and cells. |
| [RFC-0008: Native guest admission and activation retirement](0008-native-guest-admission-and-activation-retirement.md) | A separate native guest artifact/lifecycle contract shared by possible SFI and hardware-compartment backends, without selecting a mechanism. |
| [RFC-0009: Optional mapped state and fault ownership](0009-optional-mapped-state-and-fault-ownership.md) | Read-only image grants, exact view/integrity, bounded fault service and safe mapping retirement; writes require a later extension. |

These four contract questions cover five research tracks. Selecting CHERI
hardware, an SFI toolchain, MPK or composition tooling still needs candidate
evidence. Narrow host-library studies
and existing-engine optimizations do not automatically introduce a guest backend.
The [website review guide](../docs/runtime/research-proposals.md) maps these drafts
to their evidence and remaining decisions.

## Accepted proposals

- [RFC-0001: Minimum execution isolation profiles](0001-minimum-execution-isolation-profiles.md), accepted by ADR-0026; enforcement follows its explicitly assigned implementation tickets.
- [RFC-0002: Tenant-scoped publication identity](0002-tenant-scoped-publication-identity.md), accepted by ADR-0027; catalog, runtime and public-selector delivery is tracked by #265–#267.
- [RFC-0003: Versioned OCI transport profiles](0003-versioned-oci-transport-profiles.md), accepted by ADR-0029; the delivered static profile remains supported while Bearer authentication, bounded DNS/redirects and the selected real-registry matrix are tracked by #269–#270.

- [RFC-0004: Route and authorization freshness](0004-route-and-authorization-freshness.md), accepted by ADR-0030; Phase 3 supplies the finite-validity design and conformance handoff, while all distributed implementation remains Phase 5.

- [RFC-0005: Exact Phase 3 host ABI profiles](0005-phase3-host-abi-profiles.md), accepted by ADR-0031; #202 supplies bounded recognition, generated-binding parity and prepared/AOT identity. Provider installation, activation authority and streaming remain separately owned Phase 3 work.
