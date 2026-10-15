# Research tracks

Research code must not become a required production dependency. Each track needs an explicit semantic model, portability statement, security analysis, benchmark, and promotion ADR.

Research promotion follows its own evidence and architecture review, separately
from the [implemented runtime and planned phases](../docs/roadmap.md). A
prototype, source inspection or historical measurement does not establish a
delivered standalone capability.

## Native software fault isolation

The [native-SFI investigation](native-sfi/README.md) reviews restricted native
code as an optional execution backend, distinct from existing Wasmtime AOT.
It records [pinned upstream findings](native-sfi/upstream-review.md) and an
[adversarial evaluation plan](native-sfi/evaluation-plan.md), including native
artifact admission, capabilities, interruption, fault recovery and physical
cleanup. There is no LSF native-SFI prototype or qualified backend. Candidate
artifacts remain outside the node until the research and promotion gates pass.

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
