<!-- LSF-WIKI-MANAGED -->
# Design governance

LSF uses explicit decision records because resource accounting, compatibility,
and containment claims are architectural commitments rather than incidental
implementation details.

## Decision hierarchy

| Record | Use it for |
|---|---|
| ADR | An accepted decision affecting an invariant, dependency direction, execution model, or compatibility promise. |
| RFC | A proposed design that needs review before contracts change. |
| Issue | Scoped implementation/evidence work and acceptance criteria. |
| Evidence artifact | Raw measurements, aggregate reports, and receipts supporting a bounded claim. |

## Rules that guide changes

- WIT is authoritative for guest-visible component contracts.
- Protobuf is authoritative for control-plane and generic platform RPCs.
- Domain and platform errors remain separate.
- No API may require a persistent process, listener, thread, or pool per service.
- New side effects require explicit retry/idempotency semantics.
- Research stays outside the baseline until evidence and an ADR promote it.
- A ticket’s closed state cannot substitute for required test or gate evidence.

## Phase 0 reporting discipline

The Phase 0 gate is deliberately fail-closed. Documentation must report the
actual receipt state, distinguish local feasibility evidence from production
guarantees, and avoid moving unmet acceptance criteria informally between
issues.

Read [CONTRIBUTING.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/CONTRIBUTING.md),
[ADRs](https://github.com/KirilsTurkins/latent-service-fabric/tree/development/adr),
and [RFCs](https://github.com/KirilsTurkins/latent-service-fabric/tree/development/rfcs).
