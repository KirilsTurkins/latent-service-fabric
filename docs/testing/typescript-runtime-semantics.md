# Ordinary TypeScript scheduling

The separate `typescript-runtime-semantics.yml` programme compiles and signs one
ordinary component through the normal compiler using the authenticated historical
engine, splicer and native products from `typescript_fetch_replay_inputs.py`.
No host or runtime engine is rebuilt, and no application scheduler is injected.

The original Fetch profile stays at 16 tasks, two executors, 16 queued-work
records, eight waits/timers/results and 64 native owners. Ordinary language APIs
exercise a genuinely pending thenable with ignored second settlement, nested
microtasks and synchronous run-to-completion, pending rejection identity,
`finally` value/reason ordering, three nonoverlapping interval callbacks followed
by clear, timer arguments and nested timer/microtask ordering, and idempotent
clear before firing. Every positive case requires its exact returned trace.

Separate negative attempts throw from a timer callback and leave an unhandled
rejection. Both must fail with a known guest trap, followed by fresh success.
A generic trap alone does not prove callback origin or the precise rejection
cause; the receipt keeps `callbackOriginProven: false`. A synchronous infinite
loop must consume exactly its narrower 50-million-fuel caller allowance and
return resource exhaustion. Positive bootstrap and fresh calls use that same
narrower budget. The original node and other caller ceilings are unchanged.

Every invocation requires a reaped caller, zero outbound/child/effect usage,
physical retirement and idle provider owners. The node must stop cleanly and a
real peer must observe zero contacts. Source, packaged component, compiler
recipes, historical products and raw failure rows remain retained and bound.
Source/type checks or host Node reference outcomes are not signed execution.

The [signed observation](evidence/typescript-runtime-semantics-signed-2026-10-20.json)
passed all 15 calls in [run 39394512962](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39394512962/job/118533782955)
on frozen source `1a56c53aa2dd738c1afd7e4f95577462c19a2061`. All raw result
oracles, source/component/build identities, 15 physical-retirement and zero-owner
observations, the clean node stop and zero real peer contacts were independently
checked. The synchronous loop consumed exactly 50,000,000 fuel; same-budget
bootstrap and fresh calls succeeded. The engine and native products remain the
explicit authenticated historical profile, not a development rebuild.

This finite programme does not qualify all callback causes, recurrence
storms/catch-up, arbitrary races, cross-tenant reuse, native stack/heap costs,
selected socket modules or the complete #745/#736 matrices.
