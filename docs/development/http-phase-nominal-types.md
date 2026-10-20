# HTTP phase nominal resource dependency

The explicitly selected `latent:http/phase-timing@0.4.0` interface reuses the
original upload, body and chunk identities from streaming HTTP0.3. WIT resolution
implicitly imports that dependency. A phase-only component needs its resource
and value types; importing its eight old callable methods would additionally
require an operational legacy provider.

Runtime preparation already distinguishes the nominal dependency from an
operational import. Normal contract derivation and package/admission semantic
validation now recognize the same closed case: the exact phase interface must
be present, the original interface must have no functions, and every canonical
named type and resource must be present with its original full structure and
identity. A partially callable old interface, missing/extra/changed type,
lookalike resource, changed phase interface or nominal-only old world still
refuses. All comparisons consume the existing shared structural-work allowance.
The complete original legacy interface keeps its existing validation.

The source correction follows a real phase consumer failure: compilation's
normal contract driver rejected the valid resource-only dependency with
`component-interface-shape-mismatch`. Two focused Rust controls exercise the
closed semantic matrix and normal contract derivation, including malformed
inputs and exhausted comparison limits. The source-bound native producer adds
these controls while retaining its original five tools, eleven controls,
assertions, overflow checks and shared deadlines. Actual results are pending.

This recognizes descriptive types. It installs no provider, grants no legacy
operation, changes no default host profile and supplies no destination, credential
or stream authority. Fresh signed Java/TypeScript qualification remains separate.
