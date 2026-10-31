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
does not satisfy it. Enabling this workflow alone confers no compiler or
repaired-runtime pass.

## Observed results on 31 October 2026

[Compiler run 41231319361](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41231319361)
ran at `eb8bfc41999827b6ab10bcdc1b6a50da48787586`. Its artifact
`13054160505` is 52,708,533 bytes with ZIP SHA-256
`c1c36cde5737ae3b76b2c60287c76005ab6127bc1566614bbe9514d98f8a5cb2`;
all 110 member CRCs were checked. The ten TLS, eleven wait-driver and eight
synchronization controls passed. The repaired sysroot and unchanged application
compiled, then the original catalogue refused the changed body with
`rust-original-full-body-or-signature`. This is a failed compiler programme,
not a component or signed-runtime qualification. No guest executed. The
subsequent 76 source-mechanism controls were not reached.

The separate runtime consumer
[PR #1371](https://github.com/KirilsTurkins/latent-service-fabric/pull/1371)
has since retained the successful signed
[run 41231421695](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41231421695)
at `eb5bfd4786f46131394f814e77eef4412d26e5dc`. Its artifact
`13053847936` is 674,622 bytes with ZIP SHA-256
`a09fe2fba877f149c156bce8abf30f54e0e2774baaab98fe3731f04101eaeaff`;
all 154 member CRCs were checked. The five invocation records contain the
expected cold/hot/post-error pool results, declared error and recovery greeting.
Their retirement records show zero active/queued activation reservations and
zero reserved fuel/memory after every call; node and peer shutdown completed.
This evidence executes the 511,729-byte component
`c3135d063fae81a2dc651d4f102b2bcdd53eacf197406104aad4e3b405dfe97c`
with a separately identified native node, not this branch's frozen fault guest.

These are distinct source, build and execution events. The companion result
does not retroactively pass this compiler run, establish current diagnostic-head
CI, or replace the original failed component and nonempty fault-frame gate.
Review the companion's exact catalogue and native-producer chain when integrating
the repaired runtime; do not manufacture another historical origin. Neither
record closes the full #743 or checkpoint qualification.
