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

Five focused controls pass, including actual JDK cancellation/late-value
references and fixture `javac` signature checking. Signed execution is pending.
This source programme alone checks no whole acceptance box and closes no issue.
