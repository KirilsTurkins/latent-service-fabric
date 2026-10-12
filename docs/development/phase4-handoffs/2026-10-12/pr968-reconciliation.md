# PR #968: Java transaction capture reconciliation

The #718 issue body and both comments were reviewed. Original snapshot
`939183aa4f62c113420c1c0a1e39d90ef990031f` contains useful unsigned/UTF-8 state
inputs, child-call controls and historical collector continuations. Reconciliation
retains the current compiler, captured-input and transaction owners delivered
through #823/#828/#956, plus the #856/#958 delivery chain and accepted #902.

Two separately selected Java captures now preserve high-bit/full-width unsigned
values, exact UTF-8 bytes, absent values and a real imported child call inside an
acquired command. The child control requires the exact typed permission denial
before returning the existing business rejection. It creates no child budget or
grant. Compiler reports retain distinct source/recipe/component identities and
do not claim signed execution. The existing Rust result-boundary capture and all
prior compiler cases remain. CI builds and retains both new Java captures.

The current diagnostic helper already includes post-stage memory exhaustion
without enlarging its 64 MiB guest ceiling; restoring the older optional 80 MiB
allocation helper would duplicate that surface. Historical frozen policy/TLS
continuations remain bound to their original source and receipts. They are not
reused as approval for changed current inputs.

Useful #959 collector controls are retained: one finite read-only refusal
observation records closed stage/reason fields, preserves the original HTTP
failure and performs no mutation retry. Same-origin ingress uses only the exact
loopback authority and tenant. Startup now declares the version-2 storage/native/
dispatcher owners and an independently protected checkpoint directory. Namespace
receipt checks use the current canonical OriginalCaller actor framing.

The compiler/authoring source suite passed 29 cases; collector/privacy/origin/
provisioning controls passed 58 cases. Required command coverage keeps all 88
baseline blocks and adds one explicit compiler block, for 281 current blocks.
The value fixture compiled and packaged through pinned JDK 25.0.4.1, Gradle
9.1.0, TeaVM and WASI SDK 29; component digest is
`sha256:57a5f071bca76da695c99e533b311b6e6444a551b1487544f29b0bdd5cfc8edb`.
The actual child component compiled with digest
`sha256:4013c9f4f0347b60af9e84ca8607f5b78876bbc50de05b54f1423f05386978bf`;
its final compatibility check correctly reports `unknown-import` for
`latent:service/invoke@0.1.0` under the frozen Phase 4 ABI. This is retained
negative evidence, not an admitted child-call or signed-state pass. The ABI and
build rejection remain enforced. Current signed HTTP/query/recovery execution
remains separate work. #718 and its complete retained-state/lifecycle matrix stay
open; this checkpoint does not close a ticket.
