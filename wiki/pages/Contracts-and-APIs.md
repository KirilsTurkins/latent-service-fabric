<!-- LSF-WIKI-MANAGED -->
# Contracts and APIs

Typed contracts keep byte validation, structural compatibility, runtime support and execution authority separate.

| Surface | Delivered role |
| --- | --- |
| WIT | Component imports/exports and bounded scalar/composite values with named definitions. |
| Protobuf | Invocation, activation status/cancel, release/deployment/route/node management, rollout and audit RPCs. |
| JSON schemas | Closed manifest, package, policy, evidence and operator configuration profiles. |
| Rust host APIs | Package verification/comparison, signing, catalog authority, caches and bounded control ownership. |
| Six SDK language surfaces | Interface models and executable contract fixtures; no bundled network transports or retry engines. |

Structural package comparison uses real bounded package/WIT input. Reports distinguish Identical, BackwardCompatible, Breaking, Unsupported and Unknown. Public declaration identity, records, variants, enums and dependency versions are compared. Documentation or formatting-only source changes can be Identical despite different package digests.

A breaking allowance is explicit and bound to the exact old/candidate package and component pair. It cannot approve incomplete, unknown or unsupported analysis. Structural permission alone grants neither trust nor current runtime eligibility. The older ID-only CompareContracts RPC remains a placeholder; it is not the package comparison authority.

Runtime requirements can declare the engine/minimum version, target triples and architecture-qualified CPU features. The node captures its actual immutable runtime profile. Explicit requirements without a supported profile fail closed; caller labels do not replace detected capabilities.

The current generic value boundary supports bounded validated scalar/composite values. Do not assume future WIT resources, arbitrary async providers or ambient WASI behavior. Phase 3 will version its host ABI and capability profiles with their own SDK parity tests.

Management returns distinct object, route, state and rollout versions. Typed operation receipts and audit acknowledgements retain their own identities. The operator derives actor/tenant from authenticated context; a caller cannot choose an authoritative actor field.

Authorities: [WIT values](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/protocol/wit-values.md), [release compatibility](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/reference/release-compatibility.md), [management services](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/reference/management-services.md), [SDK guide](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/sdk/README.md).
