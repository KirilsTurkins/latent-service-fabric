# Examples

Examples define WIT contracts and declarative LSF resources. The maintained
echo example also has an executable Rust Component Model guest used by the
retained Phase 0 runtime and the completed Phase 1/2 standalone workflows. The
[quickstart](../docs/development/standalone-quickstart.md) builds, publishes,
deploys and invokes it through the operator CLI and authenticated node.

- [`echo-contract`](echo-contract/README.md): stateless request/response contract and executable Rust guest; build with `make echo-capsule`.
- `counter-contract`: contract/schema example for a future transactional keyed-state service.
- `order-workflow-contract`: contract/schema example for a future durable workflow-facing service.
- [`package-inputs`](package-inputs/README.md): supplied browser/SSR packaging inputs, without a serving or rendering runtime.
- [`package-format`](package-format/README.md): exact-byte OCI/evidence format fixtures, without publisher trust or executable-content claims.

The counter and workflow examples are not executable services in the completed
Phase 2 runtime. A schema-valid document can describe a later phase; semantic admission
still rejects unsupported state models and capabilities.
