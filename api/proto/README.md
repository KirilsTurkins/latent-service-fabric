# Protobuf APIs

These files are the authoritative transport-neutral service definitions for the control plane, node registration, route distribution, trigger management, policy explanation, generic invocation, cancellation, and activation inspection.

No generated server or client code is committed yet. WIT remains authoritative for typed component-to-component calls; the generic invocation API carries encoded payloads for tooling and gateways.

The Phase 1 pre-stabilization compatibility record and checked-in field
contract are in [`docs/protocol/phase-1-contract-hardening.md`](../../docs/protocol/phase-1-contract-hardening.md)
and `phase1-field-contract.json`.
