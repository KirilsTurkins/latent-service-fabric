# Phase 2 audit foundation

Phase 2 delivery operations need attributable security and administration records without creating unbounded metric dimensions, service-owned background workers or secret-bearing logs. `latent-audit` now exposes an initial bounded in-memory journal and a fixed event vocabulary for early feature integration.

This is a foundation for #152, not the final durable audit service.

## Event identity

`Phase2AuditIdentity` keeps the following identities separate where they exist:

- authenticated tenant;
- caller operation ID;
- immutable package manifest digest;
- component release digest;
- policy ID;
- rollout ID;
- deployment revision;
- route generation.

The event vocabulary is a fixed enum covering verification decisions, release revocation/retirement, cache hit/miss/corruption, rollout transitions, promotion and rollback. `wire_name()` exposes bounded low-cardinality names; arbitrary package, service, digest or error text is not a metric dimension.

`reason_code` is intended for stable bounded dispositions. Raw registry responses, signature bytes, signing keys, credentials and arbitrary external error bodies must not be copied into it.

## Bounded journal behavior

`BoundedPhase2AuditJournal` is node-owned shared state with explicit limits for retained events, query page size, metadata entries and string length. It starts no worker, timer, listener or service-specific task.

The initial overflow policy is **reject new events rather than silently evict retained audit history**. `append` returns `ResourceExhausted` and increments `rejected_overflow_events`. Feature owners integrating security-critical mutations must decide how that explicit audit failure affects their operation; this foundation does not silently declare an unaudited mutation successful.

Queries require an exact tenant and never return another tenant's entries. Pagination uses an opaque monotonically increasing journal cursor. The cursor identifies a position only; it grants no authorization by itself.

The journal is currently process-memory only. Restart durability, persistent retention and management/API export remain required follow-up work in #152.

## Metadata and redaction boundary

Actor and event attributes are bounded maps. Keys containing common secret-bearing terms such as `authorization`, `credential`, `password`, `private-key`, `secret`, `signing-key` or `token` are rejected rather than retained. Feature integrations must still perform source-aware redaction before constructing events; key filtering is a final guard, not a general secret detector.

An actor carrying a tenant identity must match the event tenant. System actors may leave their actor tenant unset, but the event itself always remains tenant-scoped.

## Current evidence and follow-up

Focused tests cover tenant isolation and pagination, fail-closed capacity behavior, sensitive metadata rejection, actor/tenant mismatch and uniqueness of the fixed wire vocabulary.

Still outstanding in #152:

- durable shared retention and restart behavior;
- authenticated management/protobuf query surfaces;
- exporter/backpressure and sink-failure policy;
- cancellation/shutdown behavior for any later asynchronous exporter;
- integrations from signature/provenance/SBOM, lifecycle/cache and rollout owners;
- canary-attributable outcome integration and final Phase 2 gate evidence.

The current synchronous journal does not change activation accounting or guest execution state and does not establish a production audit-retention guarantee.
