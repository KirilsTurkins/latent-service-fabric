# Research tracks

Research code must not become a required production dependency. Each track needs an explicit semantic model, portability statement, security analysis, benchmark, and promotion ADR.

These tracks remain exploratory after the [Phase 1 completion](../docs/phase-1-completion.md),
[performance extension](../docs/phase-1-extension-completion.md), and
[Phase 2 completion](../docs/phase-2-completion.md). None is a delivered standalone
capability or a dependency of those gates. The next feature phase is
[capabilities and application hosting](../docs/roadmap.md#phase-3-capabilities-and-application-hosting);
research promotion follows its own evidence and architecture review.

## Outbound streams and typed protocol boundaries

The [outbound streams investigation](outbound-streams/README.md) includes a
local-only SMTP/TLS prototype, source-bound ownership measurements, a six-language
compatibility review, candidate contracts and
[ADR-0059](../adr/0059-defer-general-outbound-streams.md). It proposes deferring
production sockets; it is not a dependency of ordinary libraries or HTTP adapters.

## Bounded invocation-scoped concurrency

The [invocation concurrency investigation](invocation-concurrency/README.md)
compares the six compiler profiles, includes an isolated actual-component Rust
experiment and records scope ownership, fairness, cancellation and timer limits.
The revised [ADR-0060](../adr/0060-bound-invocation-scoped-concurrency.md) targets
standard runtime compatibility beneath unchanged application and transitive
dependency code, without requiring developer-supplied executor/transport adapters.
Logical threads, pools and timers are implementation targets during an activation;
persistent guest work and fabricated execution remain forbidden. Separate runtime
and standard-I/O qualification must precede enablement and reconcile ADR-0059's
outbound recommendation. The original prototype and receipts are not evidence of
these new runtime facilities, nor a blocker for ordinary dependency ingestion.
