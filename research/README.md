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
