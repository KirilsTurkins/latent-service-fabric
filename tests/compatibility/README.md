# Contract compatibility tests

Phase 1 checks the authoritative WIT/Protobuf/schema/SDK surfaces through the
[contract hardening gate](../../docs/protocol/phase-1-contract-hardening.md),
including descriptor drift and cross-SDK representations. Phase 2 additionally
checks [exact old/candidate package compatibility](../../docs/reference/release-compatibility.md),
actual runtime requirements and authenticated native-cache keys. Its conservative
comparison covers supported synchronous WIT; general binding services and the
future async/resource surfaces are not delivered by that comparison.
The following is the broader compatibility fixture specification.

Compatibility fixtures must cover additive functions, additive record fields where permitted, variant changes, removed functions, changed sync/async behavior, resource changes, dependency-version changes, and parallel major-version bindings.
