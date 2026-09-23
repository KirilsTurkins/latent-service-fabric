# Standalone C capsule qualification

This is developer execution evidence for #545, separate from the beginner
[C authoring guide](../component-development/c-authoring.md). It does not
authorize a runtime release or replace the human newcomer review in #345.

## Observed execution

[Run 35878685638](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35878685638)
passed on September 23, 2026 for source head
`fefebb7a5433d1d9510b4b229299a81e008b62ff`. Its qualification source receipt is
`sha256:7bab7aa68dbb73b3f93c454f19c9e16544c2abd2156425f0e47ba61c88deda77`;
the complete node receipt is
`sha256:6af52b4b63ef4bdf5daac536d4b925f82b7fee0db5bceaf4966be8d4d578bfc6`.
The workflow artifact retains captured source identities, every compiler stage,
admitted capability tests, node control results and the executed tutorial.

Five independent projects built outside the runtime checkout: greeting,
word-count, shipping, HTTP status and recovery. The actual C source, selected
WIT, maintained SDK headers, generated bindings and tool identities were
captured before compilation and checked afterward. Builds took 0.872-0.923
seconds in this single experiment. These are not production benchmarks.

Signing occurred after compilation in a separate process. The node rejected
unsigned publication, enforced source-bound builder approval, published the
signed packages and deployed their returned identities. It made 111 control
calls and observed 27 completed activations plus a disconnected client.
Unicode input, declared errors, denied HTTP, traps, fuel/memory exhaustion,
deadline, cancellation and disconnection were followed by successful calls.
The recovery capsule returned a fresh static-state value of 1. The HTTP peer
observed eight authorized requests, no unexpected requests and closure of all
three held requests. There were no automatic retries of effects.

Node startup took 74,497,203 ns. Observed guest peak linear memory was
131,072-327,680 bytes. Held-call samples each reported one active invocation
with 16 MiB of reserved guest memory; whole-node RSS was 84,377,600 and
84,430,848 bytes. RSS is not guest allocator retention and these finite Linux
`/proc` observations are not atomic. The shared code cache was bounded to two
entries and one preparation, ending with 62,792 compiled-image bytes, five
misses and three evictions. Idle checks required zero occupied/quarantined
cells, zero activation quotas and zero activation-scoped owners. At 5, 9 and
17 dormant deployments, no per-service process, listener, event loop or
growing thread population appeared. Deletion and clean node/provider shutdown
completed.

## Coverage and reproduction

The same workflow ran actual C and Rust components against admitted host
providers for buffered and streaming HTTP, blobs, secrets, events, local
service invocation, random values and metrics. C scope regressions cover
allocation bounds, duplicate adoption, detach/release, reverse-order cleanup
and zeroization. The async helpers retain frames until subtask retirement;
stream/blob owners use explicit affine handle and buffer cleanup. C cannot
statically prevent copying a handle: application ownership mistakes remain
errors, not additional authority or refunds. A trap tears down the activation;
it does not roll back external effects.

All six printed Bash steps in the beginner guide ran unchanged, including
valid/invalid input and cleanup. That guide's source digest was
`sha256:75e136d3283053a9c7bc9572368a866982fb391e01694bb5fcef031ecfcba3ea`.
The tutorial website selects complete C and Rust implementations from their
actual source files, not abbreviated pseudocode.

With the pinned Linux tools installed, reproduce in a fresh output directory:

```sh
python3 tools/qualify_c_capsules.py --output /tmp/my-fresh-c-qualification
```

Success requires every stage. Earlier attempts remain failed evidence: one
exposed the no-string binding header mismatch; two separate real-node attempts
received an uncertain `unavailable` deployment result during population setup.
No uncertain mutation was retried or reclassified as success. Later attempts
used fresh nodes; read-only operation/audit diagnostics were added to retain
more context if that control failure recurs. The successful experiment does
not establish that the earlier intermittent control condition is fixed.

The later [retained failure at `797e068c`](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35886661009)
identified `admission-clock-lease-uncovered`, rather than a compiler or guest
ownership failure. Managed deployment preparation and commit now renew the
existing finite durable clock lease at their authenticated control boundaries,
before entering currentness fences. They still recheck policy and time, perform
each mutation once, and fail closed on renewal/persistence errors. Historical
operation replay performs no renewal. A deterministic control-store regression
checks failure-before-effect and unchanged replay; Linux CI and the full
real-node experiment must validate this change. The old failure's audit-page
completeness flag was incorrect because its cursor is nested under `data.page`;
the collector and its tests now use the actual wire shape.

The [next failure at `d8a6451c`](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35889722458)
passed the ownership and failure-before-mutation regressions, but preparation
still expired its lease. Complete audit pagination shows preparation growing
from roughly one to two seconds as dormant rows were added, with no prepared
receipt for the rejected operation. The shared renewal helper had retained the
sampler's two-second margin even at a mutation boundary. Control renewal now
persists a full configured five-second window; periodic sampling still uses its
existing margin. A fake-clock regression proves the distinction and exact
expiry. This is not a longer lease or a retry, and still requires qualification.

This is a finite, experimental single-node profile, not 100k-scale sizing,
cluster placement, throughput or transactional-state qualification. Build
observations are operator assertions, not authenticated source, hermetic
builds or complete transitive SBOMs. Broad PR CI and qualification at the final
head must pass before merge; historical measurements do not approve later
source. All six language tickets, #345 and the release gates remain separate.
