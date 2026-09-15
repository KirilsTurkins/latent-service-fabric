# Architecture Decision Records

ADRs record decisions that constrain implementations and compatibility. Accepted ADRs may be superseded only by another ADR.

Acceptance records architectural direction, not feature availability. Phase 1,
its performance extension, and Phase 2 are complete. Verified package admission,
OCI transfer, publisher/builder/SBOM policy, isolated compilation, bounded native
reuse and controlled rollout now have delivered implementations. General
capability providers and application hosting enter Phase 3. Transactional
state/effects and clustered control retain their later scope. Stronger external
execution hosts remain unsupported until their explicit isolation profile is
implemented and validated. The [roadmap](../docs/roadmap.md) and
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
Its permanent authority/ownership boundary is retained while ADR-0029 versions
the transport interoperability choices.

[ADR-0022](0022-bind-publisher-proofs-to-current-explicit-trust.md) defines bounded
package signatures and publisher proofs bound to explicit current policy and
revocation snapshots, separate from tenant/catalog admission.

[ADR-0023](0023-bind-build-attestations-to-observed-inputs-and-builder-trust.md)
defines observed committed-source builds and separately approved builder proofs,
with exact package/component/source associations and bounded current trust.

[ADR-0024](0024-bind-sbom-inventory-through-package-content.md) defines bounded
declared-input SBOMs embedded before package assembly, exact detached associations
and content policy separate from publisher authentication and admission currentness.

[ADR-0025](0025-separate-immediate-capability-operations-from-transactional-effect-intents.md)
separates Phase 3 immediate capability operations and explicit uncertain outcomes
from Phase 4 transactional state/effect intents. It narrows ADR-0013's blanket
external-effect statement while preserving ADR-0014's no-universal-exactly-once
boundary.

[ADR-0026](0026-require-explicit-execution-isolation-profiles.md) defines exact
security-profile selection, trusted-computing-base boundaries and fail-closed
requirements for in-process guests, isolated compilation, authenticated native
reuse and future provider/renderer/fixed-host execution.

[ADR-0027](0027-separate-publication-authority-from-component-identity.md)
supersedes only ADR-0019's one-component/one-publication rule. It separates
tenant-scoped immutable publication and lifecycle authority from component/code
deduplication, preserving legacy component fields and requiring explicit
selectors, bounded migration and independent currentness. Implementation remains
assigned to #265â€“#267 in [RFC-0002](../rfcs/0002-tenant-scoped-publication-identity.md).

[ADR-0028](0028-retain-activation-ownership-across-asynchronous-waits.md) follows
ADR-0006 by defining ownership while active guests await providers or descendant
calls. Yielding the shared runtime thread does not refund a live cell, Store,
buffer or reservation; nested calls must make progress within fixed declared
capacity or reject promptly. Implementation and conformance remain assigned to
#205, #208, #209 and #238.

[ADR-0029](0029-separate-registry-authority-from-transport-profile.md) separates
ADR-0021's permanent registry authority/ownership rules from versioned transport
choices. `lsf-oci-static-v1` names the delivered restricted profile;
`lsf-oci-bearer-v1` remains selected but unsupported until #269/#270 deliver and
validate token authentication, bounded DNS/redirects and the Harbor conformance
matrix from [RFC-0003](../rfcs/0003-versioned-oci-transport-profiles.md).

[ADR-0030](0030-bound-disconnected-authorization-validity.md) clarifies
ADR-0011's temporary disconnected operation. Exact publication authorization has
finite lease/disconnection bounds independent of route retention, with explicit
clock, replay, restart and guarded-start semantics. Phase 3 delivers the design;
[the Phase 5 handoff](../docs/architecture/cluster-freshness-handoff.md) requires
executable distributed conformance before support is claimed.

[ADR-0031](0031-version-host-abi-recognition-independently-of-provider-authority.md)
defines the exact Phase 3 host ABI recognition profile, selected asynchronous
forms, immediate-operation error semantics and prepared/native identity. Real
generated-binding checks enforce shape agreement; provider installation and
activation authority remain separate, as specified in
[RFC-0005](../rfcs/0005-phase3-host-abi-profiles.md).

[ADR-0032](0032-use-bounded-owned-resources-for-streaming-http.md) extends the host
profile to V3 with exact owned HTTP upload/body/chunk resources, finite transfer
and resident-byte accounting, and explicit EOF/cancellation semantics. The
[streaming profile](../docs/runtime/streaming-http.md) preserves V1/V2 contracts
and the separate authorization and dormant-resource boundaries.

[ADR-0033](0033-use-scoped-durable-local-blobs-with-owned-chunks.md) extends the
profile to V4 with immutable local blobs, original tenant/session authority,
owned chunks and a durable publication boundary. The [local storage
contract](../docs/runtime/local-blobs.md) defines finite inventory, explicit
retention, no-follow filesystem access and cancellation/recovery ownership.

[ADR-0034](0034-version-maintained-guest-build-provenance-profiles.md) adds
separately approved Rust and C guest build recipes for the maintained SDK
examples. It preserves ADR-0023's independent builder trust and finite process
ownership while keeping the original echo recipe unchanged.

[ADR-0035](0035-bound-http-application-values-and-delivery-ownership.md) defines
the buffered inbound application contract, canonical HTTP mapping, host-context
authority and retained response-delivery ownership. It separates an async
application export from provider availability and from the shared HTTP listener.

[ADR-0036](0036-publish-http-triggers-with-exact-catalog-target-pins.md) binds
HTTP route metadata and exact publication/deployment targets in one catalog
transaction, with explicit CAS, bounded receipts and retained request ownership.

[ADR-0037](0037-qualify-a-closed-angular-component-renderer-profile.md) selects
a closed Angular Component Model renderer candidate using executable SSR,
hydration and resource-bound evidence. It keeps production adapter/build work
and unsupported stronger isolation profiles explicit.

[ADR-0038](0038-admit-web-packages-with-componentless-publication-authority.md)
admits exact browser/SSR packages with componentless scoped publication authority,
current-use leases and the existing catalog's shared resource bounds.

[ADR-0039](0039-bound-the-shared-http-listener-and-preserve-selected-admission.md)
defines the shared HTTP/TLS listener, explicit authentication and proxy profiles,
finite connection residency, exact selected admission and retained cleanup/write
ownership. Its narrow Connection-header rule supersedes that part of ADR-0035;
the bounded application mapping remains unchanged.

[ADR-0040](0040-run-the-closed-angular-adapter-in-fresh-generic-stores.md)
installs the closed Angular adapter in fresh generic Stores with explicit profile
identity, finite callback/binary budgets and the existing HTTP cleanup ownership.
T1 remains gated on observed Angular build and web deployment authority.
