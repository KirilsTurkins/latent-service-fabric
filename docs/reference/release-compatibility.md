# Release and runtime compatibility

Phase 2 checks both whether a capsule can run on this node and whether a candidate
preserves the supported contract of an older package. These are separate decisions.
[Package admission](package-admission.md) still requires current publisher,
builder, SBOM and tenant policy. A compatibility report carries no signing,
tenant, deployment or execution authority.

## Declare host requirements

The capsule [manifest schema](../../schemas/capsule-manifest.schema.json) adds
optional requirements to its closed `compatibility` object. This example is the
complete value of that member, not a standalone capsule manifest:

```json
{
  "minimumFabricVersion": "0.1.0",
  "runtime": {"engine": "wasmtime", "minimumVersion": "47.0.3"},
  "targetTriples": ["x86_64-unknown-linux-gnu"],
  "cpuFeatures": ["x86_64.sse2"]
}
```

The runtime selector supports Wasmtime. The target list restricts the acceptable
host triples; every listed CPU requirement must be present. These fields declare
requirements; they never enable compiler features or select a different backend.
This example deliberately restricts the capsule to the named Linux target; omit
or change that requirement for another deployment target. Targets have at least
two hyphens and use ASCII letters, digits, `_`, `.` and `-`.
CPU tokens are architecture-qualified, such as `x86_64.avx2` or `aarch64.lse`.
The current vocabulary is closed to the 22 tokens listed in the schema and
`latent_manifest::CPU_FEATURES`; unknown features are rejected.
The profile permits at most eight target triples and 32 CPU requirements, with
128-byte strings. Duplicate entries, explicit nulls and unknown fields are
rejected; runtime minimum versions must be valid SemVer.
Omitting them preserves the existing portable capsule shape and canonical bytes.
Empty target/CPU arrays impose no restriction and normalize to omission.
Existing execution rules still apply, including stateless Wasm Component execution,
supported threading, bounded resources and declared host capabilities.

The node constructs one bounded immutable profile from its actual fabric/runtime
versions, target and detected CPU features. Its configurable `cpu_feature_set`
cache label is not evidence of processor support. Host requirements are checked
before enforced admission or recovery grants eligibility, before deployment
publication, and before runtime preparation. A missing profile cannot approve
explicit host requirements. Dormant releases retain no CPU probe, worker or
runtime instance.

Host embeddings use `check_runtime_compatibility(manifest, profile)` with an
optional borrowed `RuntimeCompatibilityProfile`. Its constructor validates
supplied host facts; it does not detect hardware itself. The Wasmtime adapter
provides the actual detected facts through
`WasmtimeConfig::detected_runtime_profile()`, and a factory exposes its captured
profile with `runtime_profile()`. The profile digest binds engine,
fabric/runtime versions, target, CPU features and memory/fuel ceilings.

An incompatible host can preserve verified historical catalog data without
granting current eligibility. A historical receipt or cached preparation result
does not override the current node's requirements. See the
[admission and recovery boundary](package-admission.md#historical-admission-and-current-execution).

## Keep identities separate

| Identity | Meaning |
| --- | --- |
| Capsule implementation version | Human-facing version of the implementation, bound to package version. |
| WIT package/contract version | Exact versioned interface identity used for contract selection. |
| Component `ReleaseDigest` | SHA-256 of component bytes. |
| `PackageDigest` | SHA-256 of exact package-manifest bytes, binding configuration and layers. |
| Fabric contract version | Supported platform contract; currently `0.1.0`, independent of the Cargo prerelease version. |
| Runtime version | Wasmtime engine version, independent of the capsule or WIT version. |
| Deployment revision/generation | Execution-policy identity and mutation/publication stamps. |

A higher implementation version says nothing about compatibility. A new WIT
version changes its dispatch identifier even when its types look the same;
comparison never remaps an old caller to that new identifier automatically.
WIT formatting or documentation changes can produce different package bytes
while the analyzed contract remains `Identical`. That classification does not
assert identical guest behavior or implementation bytes.

## Compare the supported contract

The comparison direction is **old package to candidate**: can the candidate
preserve calls described by the old package? The supported subset covers
synchronous freestanding functions, scalar values, lists, options, tuples,
records, variants, enums, aliases and nested results. Existing functions must
retain parameter names/order and complete parameter/result structure. Record
fields, variant/enum cases and their order remain exact. Adding a case or record
field is conservatively breaking; the checker does not synthesize adapters.

Candidate additions can be backward compatible when the old versioned contracts,
functions, types and dependencies remain satisfied. Removed functions or changed
nested definitions are breaking. The package's pinned WIT dependency graph is
resolved before comparison, which checks the exact direct interface dependencies
of the public surface. A changed declared host-import set is unknown because this
checker cannot approve a new host binding. Human-readable signature text is not a
substitute for either check.

| Result | Meaning for a later rollout decision |
| --- | --- |
| `Identical` | The analyzed supported contract is identical; package/component identity is reported separately. |
| `BackwardCompatible` | The candidate preserves the old supported contract under the declared comparison rules. |
| `Breaking` | The candidate does not preserve that contract; an explicit decision must bind this exact old/candidate pair. |
| `Unsupported` | The requested shape is outside the supported analysis subset. |
| `Unknown` | The available inputs or analysis limits cannot establish a result. |

Unknown, unsupported or exhausted analysis never authorizes promotion, including
when a caller permits breaking changes. An allowance for a known breaking pair
does not bypass runtime requirements, package integrity or current supply-chain
authority. Automatic rollout coordination and canary policy remain
[#153](https://github.com/KirilsTurkins/latent-service-fabric/issues/153) and
[#154](https://github.com/KirilsTurkins/latent-service-fabric/issues/154).

## Descriptor and package boundaries

Legacy typed contract descriptors describe scalar/list/option/result/tuple
structure, but records and variants retain only names. Descriptor comparison
therefore returns unknown for missing named definitions rather than treating
equal names or digest strings as proof of structural identity. Resources and
asynchronous surfaces are outside the current supported execution subset.

Package comparison takes two privately constructed, checked package bundles. It
resolves their exact retained WIT sources using the existing bounded source
validation and compares complete supported types. Parsing and comparison state
exist only for that explicit control operation. No additional parser graph is
retained on each bundle, catalog release or dormant deployment.

The Rust host API is the comparison surface for this slice. The existing
`ContractService.CompareContracts` placeholder accepts only contract IDs and
does not become package or rollout authority. The [operator CLI](../phase-2-operator-workflows.md)
exposes node admission and rollout operations that enforce compatibility; it
does not add a standalone package-comparison command.

## Use the host comparison API

The caller obtains each bundle through the existing build/inspect API. A default
comparison permits only the supported nonbreaking direction:

```rust
use latent_core::PlatformError;
use latent_packaging::{compare_packages, PackageBundle, PackageComparisonLimits};

fn preserves_previous_contract(
    previous: &PackageBundle,
    candidate: &PackageBundle,
) -> Result<bool, PlatformError> {
    let report = compare_packages(previous, candidate, PackageComparisonLimits::default())?;
    Ok(report.allows_replacement(None))
}
```

Inspect `report.previous()`, `report.candidate()` and `report.structural()` to
record exact identities, the classification and bounded diagnostics. A
`BreakingChangeAllowance::for_pair(previous, candidate)` represents an explicit
decision about that exact pair; pass its reference to `allows_replacement` only
after making that decision. A different pair, unsupported shape or incomplete
analysis remains denied. The returned boolean describes compatibility only.

`latent_contracts::compare_descriptors` provides the separate limited descriptor
analysis. Its `StructuralReport` distinguishes `analysis_complete` from
`diagnostics_truncated`: a bounded diagnostic list is not a complete inventory
of every difference. `BoundedCompatibilityChecker` adapts that checker to the
older trait, mapping unsupported or invalid analysis to its legacy unknown
result. Neither API trusts equal declared digest or display-signature strings.

## Bound the control operation

Comparison limits are explicit positive ceilings; callers can lower them.
Descriptor and package analysis share these default hard maxima:

| Resource | Ceiling |
| --- | ---: |
| Examined nodes / edges | 131,072 / 262,144 |
| Type depth | 64 |
| Cumulative compared string bytes | 8 MiB |
| Name bytes | 512 |
| Accounted retained analysis bytes | 8 MiB |
| Diagnostic issues | 32 |
| Diagnostic path bytes | 1,024 |
| Diagnostic report bytes | 64 KiB |

The package path additionally applies the existing
[semantic parser limits](../component-development/packaging.md#ownership-and-bounds)
and a two-input WIT allowance of 8 MiB and 512 source packages. It validates
aggregate inputs before constructing both resolved graphs. Exhausting work or input allowances cannot produce a
successful compatibility decision. The retained-byte counter charges descriptor
inputs, comparison indexes and selected package lock/dependency buffers. Parser
arenas are bounded separately by the semantic limits; the counter is neither a
complete allocation measurement nor an operating-system RSS ceiling.

## Validate a change

Small deterministic tests cover unchanged contracts, callable additions/removals,
nested record/variant/result changes, versioned identities and dependency changes,
plus unsupported forms and deliberately lowered analysis limits. Host checks use
controlled profiles for missing-engine, minimum-version, target and CPU cases;
real node preparation and deployment retain their own enforcement tests.

```sh
cargo test -p latent-contracts -p latent-packaging -p latent-manifest --locked
python -m unittest tools.tests.test_release_compatibility_schema
```

The Python checks validate the actual JSON example above and reject closed-field,
null, duplicate and collection-limit violations. Rust checks establish semantic
version ordering, actual host support and the comparison result. These checks do
not run a large load benchmark or start a guest for contract analysis.
