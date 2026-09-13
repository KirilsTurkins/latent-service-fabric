# ADR-0031: Version host ABI recognition independently of provider authority

- **Status:** Accepted
- **Date:** 2026-09-13
- **RFC:** [RFC-0005](../rfcs/0005-phase3-host-abi-profiles.md)

## Context

Phase 3 requires exact agreement between inspected WIT, compiled host imports,
generated bindings and cached native compatibility. It must also distinguish
recognizing a contract from installing and authorizing its implementation.

## Decision

Use the bounded data-only `lsf-host-abi-phase3-v2` profile for generic host ABI
recognition. Packaging, component comparison and runtime preparation share its
exact versioned names, authoritative sources and selected function forms.
Preserve existing context/log/clock bytes and the legacy aggregate world. Select
new HTTP/events 0.2.0 contracts for explicit immediate-operation uncertainty and
broker acknowledgement, with ownership semantics fixed by RFC-0005.

Inspect recognized provider imports independently of configuration. Fail
preparation when the required actual provider is absent. Neither a profile
entry, generated trait, signature, prepared artifact nor isolation label grants
permission to perform an external operation. Current activation authority,
provider generations and required isolation belong to their runtime owners.

Admit only selected freestanding async imports and bounded value forms. Keep
resources, futures, streams and async guest exports unavailable until their
owning tickets extend the ABI and finite ownership model explicitly.

Bind the profile ID and exact source digest into generic preparation and AOT
compatibility. Keep mutable grants and credential rotations outside native-code
authority; current eligibility and exact descriptor checks remain mandatory.
Resolve only selected WIT dependency versions when generating bindings and
verify generated-linker compatibility with real components in normal CI.

## Consequences

- Packages can be inspected before a provider is configured, while execution
  remains closed at the missing-provider boundary.
- Old generic prepared/native compatibility identities require regeneration.
- The currently installed guest surface remains the four built-ins; provider
  delivery, the sealed broker, streaming and stronger deployment enforcement
  remain assigned to their Phase 3 tickets.
- No dormant service receives an execution resource, listener, task or pool from
  recognition. ABI support never implies hostile-multitenant qualification.
