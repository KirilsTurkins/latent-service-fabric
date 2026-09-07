# Examples

Examples define WIT contracts and declarative LSF resources. The maintained
echo example also has an executable Rust Component Model guest used by the
Phase 0 runtime and the Phase 1 build foundation.

- [`echo-contract`](echo-contract/README.md): stateless request/response contract and executable Rust guest; build with `make echo-capsule`.
- `counter-contract`: contract/schema example for a future transactional keyed-state service.
- `order-workflow-contract`: contract/schema example for a future durable workflow-facing service.

The counter and workflow examples are not executable Phase 1 services. A
schema-valid document can describe a later phase; Phase 1 semantic admission
still rejects unsupported state models and capabilities.
