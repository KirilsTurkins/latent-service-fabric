# Frontend release examples

`site/` is a small supplied JavaScript frontend. `documentation/` has a root
document and a guide page. Both use external styles/scripts and require no
framework compiler. They exercise the
[released frontend workflow](../../docs/operations/static-release-workflow.md).

The dedicated CI workflow creates a bounded reviewed inventory, packages these
actual bytes using the authenticated released CLI, creates fresh disposable test
identities, and verifies both independent signatures. It then transfers exact
digests through a real TLS registry, publishes both sites, changes GET/HEAD
routes, renews evidence, rolls back and restarts the real released node.

The qualification container contains Node/Python and no Rust toolchain. Keys live
only in its private temporary directory and are never retained as CI artifacts.
These minimal supplied files do not qualify Angular/PrimeNG or Docusaurus; those
frameworks require their own browser/CSP integration tests.
