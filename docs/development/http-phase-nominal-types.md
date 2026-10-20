# HTTP phase nominal resource dependency

The explicitly selected `latent:http/phase-timing@0.4.0` interface reuses the
original upload, body and chunk identities from streaming HTTP0.3. WIT resolution
implicitly imports that dependency. A phase-only component needs its resource
and value types; importing its eight old callable methods would additionally
require an operational legacy provider.

Runtime preparation already distinguishes the nominal dependency from an
operational import. Normal contract derivation and package/admission semantic
validation now recognize the same closed case: the exact phase interface must
be present, the original interface must have no functions, and every retained
named type and resource must have its original full structure and identity.
Only the unused legacy `response` record may be absent after normal component
emission; all other canonical types remain mandatory. If present, that record
is validated in full too. A partially callable old interface, other missing/extra/changed type,
lookalike resource, changed phase interface or nominal-only old world still
refuses. All comparisons consume the existing shared structural-work allowance.
The complete original legacy interface keeps its existing validation.

The source correction follows a real phase consumer failure: compilation's
normal contract driver rejected the valid resource-only dependency with
`component-interface-shape-mismatch`. Two focused Rust controls exercise the
closed semantic matrix and normal contract derivation, including malformed
inputs and exhausted comparison limits. The source-bound native producer adds
these controls while retaining its original five tools, eleven controls,
assertions, overflow checks and shared deadlines. All thirteen native controls
passed in [run39430989809](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39430989809/job/118655688632).
The [original retained observation](../testing/evidence/http-phase-nominal-native-2026-10-20.json)
authenticates that distinct five-tool, nineteen-member producer. Its receipts
remain unchanged.

The later TypeScript consumer at `f139baeb76` compiled and emitted a valid
component, but its final graph guard rejected the compiler's omission of only
the unused legacy `response` record. Its original source and decoded final
graphs are retained in the parser fixture, together with source/run/archive
identities. Four Python controls bind both exact source interfaces and the
authenticated import engine/splicer, permit only that omission plus the already
reviewed readiness pruning, and reject changed types, legacy calls or phase
operations. All thirty-seven existing runtime-profile controls still pass.
A separate native control checks the same closed omission, malformed owners,
changed phase and the original comparison budget. Its fresh native run passed in
[run39443901256](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39443901256/job/118700610031):
all25 Rust controls and four emitted-graph controls passed. The complete archive,
five product hashes and exact source inventories are retained in the
[native evidence](../testing/evidence/http-tenant-native-products-2026-10-20.json).
The earlier c2a39082 run failed to compile one new test because it used a
nonexistent budget accessor; the corrected test uses the existing snapshot API
and preserves the same zero-charge assertion. Earlier receipts remain unchanged.

This recognizes descriptive types. It installs no provider, grants no legacy
operation, changes no default host profile and supplies no destination, credential
or stream authority. Fresh signed Java/TypeScript qualification remains separate.
