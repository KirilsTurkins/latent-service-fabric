<!-- LSF-WIKI-MANAGED -->
# Glossary

| Term | Meaning |
| --- | --- |
| Activation | One bounded invocation and its owned accounting/execution state. |
| Admission | Reservation of finite running/queue capacity. |
| AOT | Ahead-of-time derivative compilation; trusted distribution is Phase 2. |
| Capsule | Component bytes plus immutable manifest/contract metadata. |
| Cell | Generic configured capacity, reused after proven cleanup. |
| Contract | Versioned semantic interface, independent of implementation version. |
| Deployment | Desired configuration selecting immutable release bytes. |
| Digest | Content identity of immutable release bytes. |
| Effect intent | Planned durable external-operation record; no Phase 1 provider. |
| Fresh Store | Activation-owned Wasmtime state, never an idle per-service heap. |
| Idempotency key | Metadata; current invocation does not promise deduplication. |
| Lineage | Opaque correlation, not authorization. |
| Prepared cache | Bounded shared components; active owners can outlive eviction. |
| Quarantine | Withheld cell capacity without affirmative cleanup proof. |
| Revision | Release plus deployment configuration pinned by route selection. |
| Route snapshot | Immutable generation for local resolution. |
| RSS | Resident process memory, distinct from cgroup charge/allocation peaks. |
| Useful success | Successful response before the caller's original deadline. |
| WIT | Authoritative WebAssembly interface definitions. |

Authority: [overview](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/overview.md), [API map](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/api-surface.md).
