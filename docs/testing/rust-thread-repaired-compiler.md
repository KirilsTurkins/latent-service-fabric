# Rebuild the root-retirement repair without replacing fault evidence

The [root-retirement investigation](rust-thread-root-retirement.md) separates
native mechanism controls from actual signed ThreadPool execution. Its retained
diagnostic component predates the SDK repair and deliberately remains immutable.
Rebuilding only the host cannot establish whether the guest-side repair works.

## Fresh compiler observation

The existing `rust-owned-thread-inputs.yml` workflow now also accepts pushes on
`diag/rust-thread-frames-20261023` that change its workflow, either owning compiler
programme, or `sdk/rust-standard-runtime/**`. Those pushes select the existing
`--application-diagnostic` path. The original compiler branch still uses its
previous non-application default, and manual dispatch still requires the explicit
`application-diagnostic` option, whose default remains false.

The same selector controls Node, wasm-tools, Zig, compiler isolation/bindgen
preparation and the application compiler invocation. A partially enabled run
must not compile without its required prerequisites. Read-only permissions,
pinned actions, exact-head source checks, existing native/source controls,
20-minute job timeout, original artifact bounds, read-only cache and always-run
three-day artifact retention remain unchanged. This is compiler work, not a
signed invocation or an update to the installed compiler.

## Review the output before promotion

Retain the exact run, head, artifact and component/core identities, including
failed runs. A changed object graph may correctly refuse at the immutable
catalogue; that is new candidate compiler evidence, not successful qualification.
Do not change old receipts, substitute a freshly compiled component into an old
diagnostic result, or bypass the existing source/normal-component checks.

A candidate still needs an explicitly reviewed catalogue update and source-
matched native products before the unchanged signed five-call campaign can
establish ThreadPool progress and physical retirement. The separate diagnostic's
original nonempty fault-frame requirement remains mandatory; a suspension record
does not satisfy it. No new compiler or repaired-runtime pass is claimed here.
