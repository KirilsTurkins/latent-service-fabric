# Wasmtime 47.0.4 security baseline

## September 29, 2026: Wasmtime 48.0.3 security baseline

The maintained runtime and isolated compiler select Wasmtime **48.0.3**, with
matching Cranelift **0.135.3** internals. The default compiler remains Rust
**1.97.1**; the minimum supported Rust version becomes **1.95.0**, as required
by Wasmtime 48. Both the manifest and minimum-version CI lane change together.

This addresses [RUSTSEC-2026-0315](https://rustsec.org/advisories/RUSTSEC-2026-0315.html)
([GHSA-m63x-6p34-q65x](https://github.com/bytecodealliance/wasmtime/security/advisories/GHSA-m63x-6p34-q65x))
and [RUSTSEC-2026-0316](https://rustsec.org/advisories/RUSTSEC-2026-0316.html)
([GHSA-jqpg-j7w6-42pr](https://github.com/bytecodealliance/wasmtime/security/advisories/GHSA-jqpg-j7w6-42pr)).
The first fixes lost callee fuel across `call_ref` and exception returns. The
second accounts for dynamically lifted record/tuple, box and type-name
allocations. LSF retains its independent pre-lift schema and allocation envelope,
existing fuel and memory limits, and closed host interface surface. Newly exposed
fixed-length lists are explicitly disabled and rejected, not implicitly enabled.

The runtime version participates in the compiler, runtime compatibility and
prepared/native artifact identities. Rebuild the node and isolated AOT compiler
from the same lock. Re-prepare components and rebuild or republish artifacts
bound to the old runtime; do not reuse an old native image as compatible. No
unauthenticated loading fallback or cross-version cache exception is introduced.
The v4 host ABI interface set and WIT bytes are unchanged; its current runtime
metadata is updated. Earlier v2/v3 matrices and dated execution evidence retain
their historical identities rather than being rewritten as new qualification.

Bounded source regressions cover ordinary typed-reference calls, Java exception
returns, dynamic record-list lifting under small and sufficient host-call budgets,
and rejection of fixed-length lists. They use finite local fixtures, not unbounded
memory allocation or network exploitation. Passing dependency scans are current
observations, not a certification of sandbox safety. New validation belongs to
the security PR's workflow runs; the earlier recorded observations below remain
historical.

## Earlier security update

Phase 3 issue [#279](https://github.com/KirilsTurkins/latent-service-fabric/issues/279)
updates the workspace's exact Wasmtime dependency from 47.0.3 to 47.0.4,
including the matching internal Wasmtime, Pulley and Cranelift packages. The
runtime and `latent-aot-compiler` must be rebuilt and deployed together. This
does not change the LSF package version or expand its supported host interfaces.

## Advisory triage

[Upstream 47.0.4](https://github.com/bytecodealliance/wasmtime/releases/tag/v47.0.4)
fixes [RUSTSEC-2026-0268](https://rustsec.org/advisories/RUSTSEC-2026-0268.html)
and [RUSTSEC-2026-0269](https://rustsec.org/advisories/RUSTSEC-2026-0269.html).
The former concerns host allocation through WASIp3 streams; the latter concerns
WASI filesystem paths. Both matched the former resolved dependency version.
No exploit against LSF was established.

The reviewed lockfile contains no `wasmtime-wasi` or `wasmtime-internal-wasi`
package. The current linker installs the context/log/clock host surface, and
the public value planner rejects unsupported resources and streams. Enabling
Component Model async support is not equivalent to installing WASIp3 providers.
These reachability limits do not justify retaining the affected version or
carry forward automatically when Phase 3 adds providers.

The resolved Wasmtime features remain `async`, `component-model`,
`component-model-async`, `cranelift`, `once_cell`, `pooling-allocator`, `runtime`,
`std`, `wasmtime-jit-icache-coherence` and `wit-parser`. Default features and
`parallel-compilation` remain disabled. The patch review found no changed LSF
API usage or need to broaden those features.

## Recorded scan

The scan ran on September 13, 2026 using the official `cargo-audit 0.22.2`
Windows MSVC binary. Its release ZIP was verified against the upstream asset
SHA-256 `0a7316540862c13d954f648917ceacca593747baed6eec180fafa590be2710ab`.
The freshly fetched RustSec database revision was
`b50980aad8b8f14f77e25a97b32dd94bf008b0af` (1,243 advisories).

```text
cargo-audit audit --file Cargo.lock --db <fetched-advisory-db> --no-fetch --json
```

The pre-patch lockfile returned exit 1 with exactly the two advisories above and
no warnings. The patched lockfile returned exit 0 with no vulnerabilities or
warnings. No advisory exception, target filter or disabled yanked-package check
was used. The patched lockfile SHA-256 is
`94d3bd832f203c42829a68e5c9d27724ee8f562aae6246491d02d1607267b9cb`.
This records the database checked at that time; new advisories require another
scan. Issue [#282](https://github.com/KirilsTurkins/latent-service-fabric/issues/282)
owns recurring CI scans and explicit exception handling.

## Native artifact and compiler boundary

The declared runtime version, layout-policy identity, actual engine compatibility
hash, compiler executable digest and authenticated AOT receipt all participate
in compatibility. Identical component bytes do not authorize reuse across engine
versions or configurations. An old native entry is a cache miss or rejected
entry; successful preparation requires newly authenticated output for the
current engine. Replace the configured approved compiler executable digest with
the digest of the newly built compiler. Do not relabel old binaries or receipts.

The patch review checked the upstream copied-load path:
`Component::deserialize` calls `Engine::load_code_bytes`, which creates an owned
`MmapVec` from the authenticated input slice. Engine serialization compatibility
is checked before code publication. LSF continues to reserve the native image,
verify the exact input and current authorization, and deserialize only through
its private authenticated proof. The source guard's reviewed exact pin advances
to 47.0.4; the unsafe allowance and loader function remain unchanged.

The regression suite covers version/layout policy separation, actual runtime
versus compiler engine identity, and reopening the same catalog/native cache
with a different compiler configuration. That restart case must compile once,
load only the new authenticated output, and retain the original configuration's
independent cache entry. Existing tests cover tampered bytes and receipts, wrong
keys, currentness/revocation and resource reclamation. The version-policy test
does not claim to execute a retained 47.0.3 binary.

## Validation and scope

The required CI builds both node and compiler from the locked dependency set,
runs the workspace suite and bounded delivery workflows, and exercises native
cache and isolated compiler containment on Linux x86-64. Compiler tests include
timeout, cancellation, invalid input/output, process failure and owned-resource
retirement. Focused runtime tests also cover value encoding/lifting, preparation,
invocation and current admission checks. The local Windows test suite does not
substitute for the Linux-only process-isolation tests.

The local Rust 1.97.1 run completed 205 library tests: 197 passed, including the
new version/layout check, and eight stopped at catalog fixture setup with
`catalog-path-durability-uncertain`. They reached the unchanged directory-sync
path before Wasmtime compilation; the full Windows run is therefore not a pass.
Linux CI must pass these catalog-dependent tests and the isolated compiler suite
before merge. No durability check or test assertion is weakened for Windows.

No 100,000-execution or full performance campaign is required for this patch.
Current collectors report the linked/workspace engine version. Retained Phase 0
and Phase 1 results, their historical control recipes and strict revision
comparison validators remain tied to their recorded 47.0.3 environment; they
are not relabeled as measurements of 47.0.4. A new revision comparison needs a
reviewed measurement profile and fresh paired evidence.

This patched baseline precedes the Phase 3 ABI, asynchronous I/O and stream
contracts in [#202](https://github.com/KirilsTurkins/latent-service-fabric/issues/202),
[#205](https://github.com/KirilsTurkins/latent-service-fabric/issues/205) and
[#212](https://github.com/KirilsTurkins/latent-service-fabric/issues/212).
It does not certify hostile multitenancy or add a new execution-host backend.
