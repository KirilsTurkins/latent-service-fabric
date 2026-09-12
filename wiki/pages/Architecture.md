<!-- LSF-WIKI-MANAGED -->
# Architecture

The delivered runtime is one Linux node with local durable catalogs, immutable route snapshots and configured execution pools. The separate operator CLI uses authenticated loopback RPC. Package registries distribute bytes; they do not become runtime admission authorities.

![Phase 2 owners and later phase boundaries](assets/system-decomposition.gif)

| Owner | Delivered responsibility |
| --- | --- |
| Package and registry libraries | Deterministic portable packages, bounded OCI transfer and optional raw blob reuse. |
| Catalog and supply-chain authority | Verified publication, exact package/component associations, current policy and lifecycle capabilities. |
| Deployment store | Atomic desired state, route generations and bounded operation/rollout history. |
| Rollout coordinator | One bounded control queue for explicit operator commands; no automatic health-driven controller. |
| Audit owner | Bounded durable attempts/outcomes, recovery and leased query pages. |
| Execution backend | Fixed cells, bounded preparation, fresh activation state and final eligibility checks. |
| Optional isolated compiler/native cache | Approved child compilation and authenticated local native reuse with separate resource owners. |

An activation selects and pins one revision and route generation. Admission reserves its execution budget; preparation completes before the cell lease. A fresh Wasmtime Store supplies supported host imports. Deadline, cancellation and completion keep their owners until cleanup actually retires work. Revocation cannot be bypassed by a prepared cache hit or an old queued token.

Control-plane I/O stays outside Invoke. Canary capture uses bounded in-memory accounting and an affine terminal owner; it never writes audit files or changes an activation's execution budget. Critical control audit and complete response preflight precede mutation. A lost caller may leave a committed operation whose terminal audit outcome is Unknown; exact durable lookup resolves what is retained.

Resources have distinct limits: catalog metadata, queue slots, request/response bytes, audit retention, raw cache storage, compiler jobs and native images. Fixed workers do not imply constant catalog RSS. Cancellation does not refund bytes or job slots while another owner still holds them.

| Selected bound | Profile and scope |
| --- | --- |
| Admission policy | 256 KiB maximum encoded policy; nested role limits also apply. |
| Signature / provenance envelope | 4 KiB / 48 KiB hard ceilings, with separately bounded decoded claims. |
| Audit | 16 KiB per encoded record; default retained records use a 64 MiB byte ceiling. |
| Rollout | 64 KiB per command and per response page; each page reserves four times its requested bytes for overlapping representations. |
| Raw cache | Default 256 MiB resident/reserved disk and 64 MiB per object; staging, reads and metadata have separate allowances. |

Configured lower limits and remaining capacity can reject work before a listed count or byte ceiling is reached. These counters describe ownership domains, not total process RSS.

The default trusted-local mode remains explicit compatibility behavior. Enforced catalogs bind one configured authority, and persisted mode markers reject a downgrade. Optional rollout, audit and AOT owners have real startup/shutdown lifetimes; no dormant service receives its own worker.

General HTTP ingress, provider capabilities, cross-node control, transactional guest state and durable workflows belong to later phases. Phase 3's [41-ticket plan](https://github.com/KirilsTurkins/latent-service-fabric/issues/201) is planned work.

Authorities: [architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/ARCHITECTURE.md), [standalone node](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/reference/standalone-node.md), [audit](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-2-audit.md), [trusted AOT](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/runtime/trusted-aot.md).
