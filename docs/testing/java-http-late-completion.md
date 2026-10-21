# Java accepted HTTP completion after logical cancellation

This finite qualification targets the remaining #688 late-completion ownership
boundary. It supplements earlier selected Java HTTP close/drain/cancel and
cross-tenant programmes; it does not require completion of all #741/JDK work.

An unchanged `http-request:6.0` receives a genuinely held response on either an
ordinary `Executors.newSingleThreadExecutor()` task or default
`CompletableFuture.supplyAsync`. After five actual bytes, the caller cancels the
future with `cancel(false)`, verifies `CancellationException`, and observes one
retained runtime Result owner. The sole direct SDK call is a read-only test
observation; it supplies no HTTP, execution or completion behavior to the library.

Only then does an ordinary fixed-body POST produce the controlled peer marker.
The supervisor requires its exact method/body identity and completed response,
plus live physical/provider ownership, before releasing the original HTTP suffix
once. The real callback must consume all 4,109 bytes and return. Its late value
must not overwrite the cancelled future. Result ownership must subsequently be
zero, physical owners must retire, and a fresh call must reset statics in the
same configured cell. Both future variants use the original runtime/provider,
chunk/outstanding, fuel/memory and deadline limits. No native rebuild is involved.

The scope is **after logical task cancellation and before activation
retirement**. There is no claimed callback into a retired Store, stale peer-gate
release, sleep-based completion inference, injected library executor/transport or
raised budget. Earlier root-closing, terminal-trap and cross-tenant observations
keep their original component/runtime source attribution.

Four outcomes, one zero-work grant denial and six contacts are mandatory. Raw
per-case/pending/final shutdown/peer/product observations remain separate from the
bounded summary. Errors preserve partial public process streams and the original
failure. The native products remain the immutable protocol-inclusive `6fd`
producer; current source and all 134 materials must match it before and after.

The [exact-source hosted campaign](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39529845887/job/118992976265)
passed all four signed outcomes, one zero-work grant denial and six HTTP contacts
at `f9a296e9f302de6c489445e2e92b18ad6ac2aef3`. All 175 archive members, exact
revisions, both cancellation-marker/pending-owner/release/suffix-completion
sequences, per-case retirement and raw clean/reaped node/stopped peer were
independently verified. The 4,034,052-byte component has SHA-256
`ae90c6c77f4d1886f1cf1b81e080702814c0df43c0d4fc04e98ae33fd5ca48b3`.
The [fixed evidence](evidence/java-http-late-signed-2026-10-21.json) preserves the
historical native source and explicitly records the three unrelated integration
material changes. All five qualified feature blobs and 199 Java SDK/WIT
preimages remain unchanged. No new native or guest compilation was needed for
that composition. The five source/JDK controls remain separate evidence.

This finite result supplies the selected accepted-task late-completion case;
whole #688 acceptance still requires its cumulative literal audit. Broader #741,
callbacks into retired Stores, arbitrary JVM scheduling, HTTPS and release
qualification are not claimed.
