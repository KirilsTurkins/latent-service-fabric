# Call-graph fusion research

Call-graph fusion investigates runtime-derived composites for selected stable
local call chains while developers keep services separately authored and
released. **LSF does not implement call-graph fusion.** The manifest's
`fusionEligible` field is not an available execution switch, and Angular SSR
explicitly excludes fusion eligibility.

Unlike [native-SFI](native-sfi-research.md), this work can use the existing
Wasmtime backend: it changes composition and call handling rather than requiring
a different admitted machine-code format.

## Current local calls

The [local-service provider](local-service-invocation.md) already avoids an
inter-service network hop. It uses compiled bindings and the normal activation
manager. Each child retains a fresh Store, derived identity, current target
checks, normal admission, delegated budgets, audit and cleanup. Waiting parents
keep their cells, and children receive capacity or a prompt rejection.

A composite cannot assume that these semantics disappear with an internal
connection. One artifact need not mean one heap, activation, authority or
transaction. Reducing child cell usage changes capacity policy; reusing a callee
instance can change mutable state; propagating a child trap can change a failure
the parent could otherwise handle. WAC type composition supplies no LSF
authorization or lifecycle owner by itself.

## Investigation and evidence

The [research overview](../../research/call-graph-fusion/README.md) distinguishes
joint preparation, guarded component composition and deeper activation merging.
The [primary-source review](../../research/call-graph-fusion/upstream-review.md)
covers the literature, current composition tooling and their transfer limits.
The [evaluation plan](../../research/call-graph-fusion/evaluation-plan.md) defines
identity/currentness, safe fallback, optimizer bounds and semantic tests.

The [benchmark specification](../../benchmarks/fusion/README.md) compares against
the current ordinary path, separates cache states and accounts for build/churn
costs. It remains specified; no fused-path benchmark or speedup is established.
Promotion requires a later architecture decision and conformance evidence under
[ADR-0016](../../adr/0016-keep-paging-continuation-eviction-and-fusion-optional.md).
