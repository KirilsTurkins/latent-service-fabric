# Protobuf APIs

These files are the authoritative transport-neutral service definitions for the control plane, node registration, route distribution, trigger management, policy explanation, generic invocation, cancellation, and activation inspection.

Rust message types plus Tonic client and server surfaces are generated at build time by `crates/latent-rpc`. The generated Rust remains under Cargo `OUT_DIR`; it is never checked in beside the authoritative `.proto` files. `latent-api.protos` is the sorted, exhaustive input manifest used by both the build script and repository validator, so adding a `.proto` without adding it to generation fails validation.

WIT remains authoritative for typed component-to-component calls. The generic invocation API carries encoded payloads for tooling and gateways; generated RPC types do not implement service semantics.

`latent-wire` now implements the bounded Phase 1 invocation and management
adapters. See the [management service reference](../../docs/reference/management-services.md)
for typed release uploads, tenant authorization, atomic deployment generations,
pagination, node-operator inventory access, and explicit unsupported methods.
The additive Phase 2 `PublishReleaseRequest.package` alternative performs
[authenticated package admission](../../docs/reference/package-admission.md);
enforced nodes reject the retained trusted-local `artifact` alternative.
The additive [release lifecycle APIs](../../docs/reference/release-lifecycle.md)
add tenant-scoped status, revoke/retire, evidence renewal and bounded operation
receipts. Publication's optional operation precondition preserves existing
callers; actor identity still comes from the listener's trusted principal.
The [standalone Linux node](../../docs/reference/standalone-node.md) serves this
subset through a bounded loopback listener with configured credentials.

The Phase 1 pre-stabilization compatibility record and checked-in descriptor contract are in [`docs/protocol/phase-1-contract-hardening.md`](../../docs/protocol/phase-1-contract-hardening.md) and `phase1-descriptor-contract.json`, which is validated from a Buf-built `FileDescriptorSet` by `tools/validate_phase1_descriptor.py`.
