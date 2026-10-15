# latent-native-vm-fixture

Explicit test-only package/evidence generator for the native VM qualification
runner. It takes the echo example from an authenticated extracted toolkit,
builds a checked package with an embedded SBOM, generates fresh ephemeral
publisher/builder keys and exports public verification policy plus detached
evidence. It does not run a VM, start a node or compile the supplied component.

This is one of the repository's two isolated Rust package projects outside the
root workspace. Its own [Cargo.toml](Cargo.toml) declares an independent workspace
and [Cargo.lock](Cargo.lock); root workspace builds do not select it implicitly.

## Responsibilities and architecture

The implementation is [src/main.rs](src/main.rs). Its main stages are:

| Function | Responsibility |
| --- | --- |
| `read` / `write_json` | Bounded regular input files and create-new JSON outputs |
| `package` | Exact echo component identity, capsule/contracts/WIT layers, WIT lock and SBOM associations |
| `policy` | Fresh, finite test publisher/builder policy and revocation snapshots |
| `synthetic_observation` | Clearly synthetic test build assertion with an invalid example repository and fixed marker material |
| `export` | Ephemeral keys, signatures, public verification, checked directory export and fixture metadata |
| `main` | Exact `--test-only BUNDLED_ROOT NEW_OUTPUT` grammar and fixed safe diagnostics |

## Execution and ownership

1. The [native VM runner](../run_native_vm.py) authenticates the fixture helper
   and release archive, extracts checked release contents and chooses a fresh
   private output location.
2. The helper verifies the bundled echo component digest, builds deterministic
   package layers and embeds the bounded inventory through `latent-packaging`.
3. Fresh key owners sign the exact package subject. Test policy admits only the
   explicit test identities and tenant; the helper performs public verification
   before exporting the fixture.
4. Package bytes, detached evidence, `policy.json` and `fixture.json` are written
   into a new directory. Existing output is refused; failure can leave a partial
   test directory for the runner to retire.
5. The runner validates the metadata and copies only its bounded approved file
   set into the selected VM. Private signing keys are never exported.

## Trust and scope

`fixture.json` explicitly records `syntheticTestTrust: true`,
`privateKeysExported: false`, `runtimeDefaultTrust: false` and
`actualBuildProvenanceClaim: false`. The signed observation exercises evidence
plumbing; it is not a claim that this helper observed the echo compiler or a
reproducible release build.

Do not install the generated test policy as production default trust. Runtime
admission remains the actual node's job. The helper uses the normal artifact,
packaging, signing and verification libraries while keeping synthetic test
identities visibly separate from release/operator authority.

The file reader's regular-file/size checks are test input bounds, not the node's
protected descriptor-rooted credential reader. Its caller owns the authenticated
extracted tree and private staging directory. The helper itself supplies no
process watchdog, VM isolation or production credential policy.

## Dependencies and verification

Direct path dependencies are [latent-artifacts](../../crates/latent-artifacts/README.md),
[latent-core](../../crates/latent-core/README.md),
[latent-packaging](../../crates/latent-packaging/README.md),
[latent-policy](../../crates/latent-policy/README.md) and
[latent-signing](../../crates/latent-signing/README.md). Its independent lock owns
the selected dependency resolution; use the native qualification/release recipe
to build the helper rather than assuming the root test recipe built it.

There are no Rust test functions in this package and no root registered package
suite. The consuming runner checks fresh public test trust, exact fixture fields,
bounded file copying and real VM/node outcomes. Those steps require an explicitly
selected [native release gate](../../docs/development/native-release-gate.md);
documenting or building the helper does not execute that campaign.

## Related documentation

- [Native release gate](../../docs/development/native-release-gate.md)
- [Security baseline](../../docs/development/security-baseline.md)
- [Build provenance](../../docs/reference/build-provenance.md)
- [Package admission](../../docs/reference/package-admission.md)
- [Workspace and isolated package index](../../crates/README.md)
