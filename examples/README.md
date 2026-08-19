# Examples

Examples define versioned WIT contracts and declarative LSF resources. The echo
example additionally provides the Phase 0 executable Rust component fixture.

- `echo-contract`: stateless request/response contract plus the generated-binding Rust guest under `guest-rust/`.
- `counter-contract`: transactional keyed-state contract only.
- `order-workflow-contract`: durable workflow-facing service contract only.
