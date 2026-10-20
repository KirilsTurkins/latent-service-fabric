# Ordinary Java HTTP with pending fiber work

This finite qualification combines unchanged `http-request:6.0` calls with the
existing `teavm-activation-fibers-io-v1` compiler profile. It adds no compiler,
runtime, executor, transport or backend implementation. The authored fixture
imports HTTP, clocks and activation explicitly; operators install and grant
them separately. The original 26 published-client results remain independently
source-bound in [the two-client report](java-published-http.md).

One fresh project uses normal declaration, pinned Gradle resolution, exact
captured-graph review and SHA-256 CAS. Its SDK and activation WIT bytes come
unchanged from the captured SDK. After acquiring one pinned compiler cache,
the component build uses the normal read-only/offline compiler-cache path and
the explicit existing fiber-I/O profile. A normal signed package is admitted
and deployed; no application-supplied LSF transport or scheduling hook is used.

The seven primary controls require actual peer gates, not an already-completed
future or a modeled scheduler:

1. An ordinary child Thread waits for HTTP headers while a Timer fires and a
   sibling HTTP call completes. The result checks root/child ThreadLocal values.
2. An independent single-thread executor finishes an HTTP call while another
   executor remains blocked after the first five bytes of a streamed body.
3. The root computes its return value before its accepted child completes. The
   invocation process and physical activation must remain owned until the peer
   releases the child's headers, and the returned counter must still be zero.
4. An uncaught Java root exception drains the accepted child before becoming a
   trap. This exercises the existing exception path; it does not claim that
   arbitrary native traps execute Java finally blocks.
5. One explicit cancellation is acknowledged only after a real pending request
   and charged activation have been observed. An uncertain cancellation is never
   replayed.
6. A narrowed 3,000 ms root deadline expires with a held request, before the
   unchanged HTTP grant's 5,000 ms ceiling. Cold preparation must not substitute
   for the required actual pending-request witness.
7. A narrowed 100,000,000-fuel terminal trap occurs with pending HTTP, bypassing
   guest cleanup. Exact fuel consumption and elapsed time below the original
   HTTP ceiling are required; failure to reach the peer is a failed control.

Four fresh invocations after the terminal controls check reset static/child
state and ordinary HTTP success. A separate initial fresh GET establishes the
component's normal path; it does not alter any configured timer. Missing
activation authority must refuse with zero fuel and zero peer contact while
the same endpoint's HTTP/clock grants are present. Every successful or terminal
control requires complete idle host topology/cells/quotas and zero provider
owners afterward. The peer allows fourteen primary contacts, no mutation or
secondary contact, and must close all sockets/listeners. Node shutdown must
be clean and reaped.

The focused PR workflow authenticates the same four historical `03a3f745`
helpers and ordinary-default/features-empty `e97d44dd` host as the two-client
campaign, before and after execution. It compiles one fresh Java component;
it neither recreates a production native tuple nor claims current native
compilation. Its fixed branch PR trigger avoids requiring a new workflow name
on the default branch. Source/project/peer controls run locally without a
component; the signed hosted result is **pending**.

The first real offline build exposed two invalid pointer-to-integer loop copies
in pinned TeaVM 0.15 output. Bounded generated-C declarations and every use of
the failed variables were retained before temporary-source cleanup. The pinned
coroutine splitter removes internal copied-block phi inputs after remapping
their source IDs. The captured compiler now corrects that predicate in a private
core JAR, preserves every unrelated JAR entry and the immutable checked cache,
and records the actually loaded compiler class source. Real old/corrected IR
controls precede component compilation. No C cast, ignored warning, altered
fixture or optimization change substitutes for a valid loop. Hosted compilation
and the signed lifecycle result remain pending until that campaign passes.

This advances the finite HTTP pending/sibling/drain/cancellation surface of
#688 and #741 only. It does not establish HTTPS, nonzero connect/read phase
timeouts or Webb's default phase-timeout behavior, all scheduler fairness/races,
late callbacks after acknowledged cancellation, cross-tenant isolation, physical
allocation upper bounds or whole-ticket closure. All original profiles, grants,
limits and qualifications remain required in their existing lanes.
