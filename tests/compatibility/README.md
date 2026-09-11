# Contract compatibility tests

Phase 1 checks the authoritative WIT/Protobuf/schema/SDK surfaces through the
[contract hardening gate](../../docs/protocol/phase-1-contract-hardening.md),
including descriptor drift and cross-SDK representations. General contract
comparison and binding services remain outside the standalone RPC subset.
The following is the broader compatibility fixture specification.

Compatibility fixtures must cover additive functions, additive record fields where permitted, variant changes, removed functions, changed sync/async behavior, resource changes, dependency-version changes, and parallel major-version bindings.
