# TypeScript fallback through ordinary dependency callbacks

[The owning run](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39689466570) passed one normal TypeScript build and four signed calls at source `56a73d71ef0187d7992e1f6750d27e42312957c1`. The [retained observation](evidence/typescript-explicit-fallback-2026-10-22.json) records the finite #679 result and exact historical build identities.

A captured two-level npm dependency constructs its ordinary default clock and invokes a transitive callback. That callback reaches `Date.now()` without a selected clock profile. The application catches the native Error with message `unsupported:standard-clock-without-approved-profile`, then computes `seed * 5 + 7`. It uses no SDK executor or injected clock replacement.

| Call | Actual outcome |
| --- | --- |
| Catch, seed 7 | Alternate 42, fresh state |
| Catch, seed 11 | Alternate 62, fresh state |
| Uncaught, seed 13 | Terminal guest trap |
| Catch, seed 19 | Alternate 102, fresh state after the trap |

Each raw invocation and retirement observation is retained before the result predicate. All four calls retired five physical owners and showed all 18 available provider counters zero. The node shut down cleanly and was reaped; the observation peer received zero requests. No clock grant, runtime profile, WIT surface or resource limit was changed.

Whole-archive verification checked all 142 CRCs, 190 executed Git materials, 110 recipe rows, 63 captured source rows, the normal generated project, both original dependency sources and their actual bundle contributions, the component/package identities, all four raw results and 44 command streams. The actual build completed 20 compiler/package commands. Development composition preserves all 190 executed materials byte-for-byte; it does not require a second compiler campaign.

The installed compiler identity has 4,431 files. Normal preparation preserves those entries and adds one 18,966-byte core-v2 adapter, giving 4,432 selected files. The retained recipe authenticates that transformation, and the compiler identity records and build observations are bound to the component. Compiler payloads and generated adapter bytes were not uploaded, so the archive does not independently reconstruct those payload bytes. This is unsigned observation evidence, not a hermetic-build attestation.

The native products retain their original three-product `f244` and two-product `f625` compilation provenance. No host native tools or JavaScript engine were rebuilt. The component is 12,469,122 bytes with SHA-256 `ea6e9555213a939100075b09e63d72d9e8e631785456c626940a47a21dea7f38`.

This qualifies explicit application fallback after the reached native refusal. The uncaught call remains a failure. Native table and Store/instance aggregate memory ownership, the remaining cross-language profile/limit/lifecycle report requirements stay open. A separate [reached/eliminated root-edge observation](typescript-compiler-elimination.md) retains eight actual calls and its controller failure. This result does not certify arbitrary dependency compatibility or whole-ticket completion. The separate [C/Go fallback observation](sdk-explicit-fallback.md) retains its own source and native identities.
