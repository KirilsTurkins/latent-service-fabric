<!-- LSF-WIKI-MANAGED -->
# Core concepts

| Concept | Meaning |
| --- | --- |
| Service | Stable logical identity, independent of a process/port. |
| Release | Immutable component bytes with validated manifest/typed metadata and content digest. |
| Deployment/revision | Release plus configuration, policy and resource ceilings. |
| Route snapshot | Immutable local mapping selecting a revision, pinned per activation. |
| Activation | One invocation with function, input, authenticated identity, budget and deadline. |
| Cell | Generic bounded capacity; fresh guest Store/host state per activation. |
| Shared cache | Bounded node-owned code/metadata; active owners can retain evicted entries. |

```text
resident state = fixed node runtime + bounded catalog metadata
               + active activations + bounded shared caches
```

Metadata is bounded by configuration but grows with service count up to its limits. Dormant services receive no dedicated execution worker or guest heap. Phase 1 is stateless; state commit, effect intents and durable workflow suspension are later semantics.

A caller activation ID allows status/cancel before the response arrives. It is not authority or an idempotency key. A lost response or absent retained status never establishes that no execution occurred.

Authority: [architecture overview](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/overview.md), [lifecycle](Activation-Lifecycle).
