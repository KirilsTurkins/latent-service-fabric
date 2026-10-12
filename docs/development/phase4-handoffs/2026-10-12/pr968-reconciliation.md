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
Actual new component compilation and current signed HTTP/query/recovery execution
remain separate work. #718 and its complete retained-state/lifecycle matrix stay
open; this checkpoint does not close a ticket.
