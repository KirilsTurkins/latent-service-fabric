# Architecture Decision Records

ADRs explain why LSF works as it does and which constraints an implementation
must preserve. Acceptance records an architectural decision; availability comes
from the current implementation and its qualification. Superseding a decision
requires another ADR with an explicit scope.

## Current implementation

The standalone node executes Component Model capsules in fresh Wasmtime Stores,
resolves immutable local routes and uses activation-scoped capability grants.
It provides exact publication admission, bounded OCI transfer, isolated compiler
work, authenticated native reuse, managed delivery and shared HTTP ingress.
The closed Angular renderer and static web targets use that shared ingress.
See the [architecture overview](../docs/architecture/overview.md),
[execution profiles](../docs/runtime/execution-security-profiles.md) and
[current host ABI](../docs/runtime/host-abi-profile.md) for the supported boundary.

Application transactions, durable effect dispatch and clustered control remain
planned. A fixed execution-host backend for process-compromise containment is
also unavailable. A compiler sandbox does not supply that guest boundary.

## Read superseded decisions in context

- ADR-0027 replaces the original one-component/one-publication association with
  exact tenant-scoped publication authority.
- ADR-0025 separates immediate capability calls from future transactional intents.
- ADR-0029 adds an explicitly configured Bearer transport alongside the restricted
  static OCI profile. Its tested topology does not imply support for every registry.
- ADR-0032/0033 extend the original ABI with exact HTTP/blob resource ownership;
  ADR-0035 adds the buffered async application contract.
- ADR-0039/0040/0042 record the shared listener, installed Angular adapter and
  optional scoped backend request beyond the initial renderer qualification.
- ADR-0043 adds a distinct static target. ADR-0044 supersedes its original old-format
  recovery policy and the obsolete catalog/selector compatibility in ADR-0019/0027.
- ADR-0041 governs documentation ownership, versions and publishing. A working
  website build does not complete human guide review or authorize a runtime release.

Dates, original rationale and historical measurements remain useful decision
history. Current guides and reference pages must use the implemented contract;
old implementation snapshots are not setup instructions.

## Decision index

### Runtime and authority

- [ADR-0001: Use Rust for the runtime](0001-use-rust-for-the-runtime.md)
- [ADR-0002: Use the WebAssembly Component Model](0002-use-the-webassembly-component-model.md)
- [ADR-0003: Use WIT as the capsule contract authority](0003-use-wit-as-the-capsule-contract-authority.md)
- [ADR-0004: Use Wasmtime as the first execution engine](0004-use-wasmtime-as-the-first-execution-engine.md)
- [ADR-0005: Forbid per-service idle execution allocation](0005-forbid-per-service-idle-execution-allocation.md)
- [ADR-0006: Use reusable generic execution cells](0006-use-reusable-generic-execution-cells.md)
- [ADR-0007: Distribute capsules as OCI artifacts](0007-distribute-capsules-as-oci-artifacts.md)
- [ADR-0008: Compile AOT artifacts only in a trusted boundary](0008-compile-aot-artifacts-only-in-a-trusted-boundary.md)
- [ADR-0009: Use capability-based host access](0009-use-capability-based-host-access.md)
- [ADR-0010: Separate immutable capsule metadata from deployment policy](0010-separate-immutable-capsule-metadata-from-deployment-policy.md)
- [ADR-0011: Keep the control plane out of the invocation hot path](0011-keep-the-control-plane-out-of-the-invocation-hot-path.md)
- [ADR-0012: Place remote invocation behind a WIT-native transport abstraction](0012-place-remote-invocation-behind-a-wit-native-transport-abstraction.md)
- [ADR-0013: Use explicit state transactions and effect intents](0013-use-explicit-state-transactions-and-effect-intents.md)
- [ADR-0014: Do not promise universal exactly-once external effects](0014-do-not-promise-universal-exactly-once-external-effects.md)
- [ADR-0015: Build a single-node stateless fabric before clustering](0015-build-a-single-node-stateless-fabric-before-clustering.md)
- [ADR-0016: Keep paging, continuation eviction, and fusion optional](0016-keep-paging-continuation-eviction-and-fusion-optional.md)
- [ADR-0017: Use fixed trust-class execution hosts for stronger containment](0017-use-fixed-trust-class-execution-hosts-for-stronger-containment.md)
- [ADR-0018: Treat Latent Service Fabric as a working name](0018-treat-latent-service-fabric-as-a-working-name.md)

### Packages, trust and activation ownership

- [ADR-0019: Separate package identity from component identity](0019-separate-package-identity-from-component-identity.md)
- [ADR-0020: Validate supplied components without executing guests](0020-validate-supplied-components-without-executing-guests.md)
- [ADR-0021: Bound registry authority and transfer ownership](0021-bound-registry-authority-and-transfer-ownership.md)
- [ADR-0022: Bind publisher proofs to current explicit trust](0022-bind-publisher-proofs-to-current-explicit-trust.md)
- [ADR-0023: Bind build attestations to observed inputs and builder trust](0023-bind-build-attestations-to-observed-inputs-and-builder-trust.md)
- [ADR-0024: Bind SBOM inventory through package content](0024-bind-sbom-inventory-through-package-content.md)
- [ADR-0025: Separate immediate capability operations from transactional effect intents](0025-separate-immediate-capability-operations-from-transactional-effect-intents.md)
- [ADR-0026: Require explicit execution isolation profiles](0026-require-explicit-execution-isolation-profiles.md)
- [ADR-0027: Separate publication authority from component identity](0027-separate-publication-authority-from-component-identity.md)
- [ADR-0028: Retain activation ownership across asynchronous waits](0028-retain-activation-ownership-across-asynchronous-waits.md)
- [ADR-0029: Separate registry authority from transport profile](0029-separate-registry-authority-from-transport-profile.md)
- [ADR-0030: Bound disconnected authorization validity](0030-bound-disconnected-authorization-validity.md)

### Capabilities and application hosting

- [ADR-0031: Version host ABI recognition independently of provider authority](0031-version-host-abi-recognition-independently-of-provider-authority.md)
- [ADR-0032: Use bounded owned resources for streaming HTTP](0032-use-bounded-owned-resources-for-streaming-http.md)
- [ADR-0033: Use scoped durable local blobs with owned chunks](0033-use-scoped-durable-local-blobs-with-owned-chunks.md)
- [ADR-0034: Version maintained guest build provenance profiles](0034-version-maintained-guest-build-provenance-profiles.md)
- [ADR-0035: Bound HTTP application values and delivery ownership](0035-bound-http-application-values-and-delivery-ownership.md)
- [ADR-0036: Publish HTTP triggers with exact catalog target pins](0036-publish-http-triggers-with-exact-catalog-target-pins.md)
- [ADR-0037: Qualify a closed Angular Component Model renderer profile](0037-qualify-a-closed-angular-component-renderer-profile.md)
- [ADR-0038: Admit web packages with componentless publication authority](0038-admit-web-packages-with-componentless-publication-authority.md)
- [ADR-0039: Bound the shared HTTP listener and preserve selected admission](0039-bound-the-shared-http-listener-and-preserve-selected-admission.md)
- [ADR-0040: Run the closed Angular adapter in fresh generic Stores](0040-run-the-closed-angular-adapter-in-fresh-generic-stores.md)

### Documentation and current alpha contracts

- [ADR-0041: Publish single-source, version-bound documentation](0041-publish-single-source-version-bound-documentation.md)
- [ADR-0042: Bound Angular render data through the capability broker](0042-bound-angular-render-data-through-the-capability-broker.md)
- [ADR-0043: Select static web publications as first-class HTTP targets](0043-select-static-web-publications-as-first-class-http-targets.md)
- [ADR-0044: Remove obsolete alpha compatibility](0044-remove-obsolete-alpha-compatibility.md)
