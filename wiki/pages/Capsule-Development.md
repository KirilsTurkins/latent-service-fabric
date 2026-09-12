<!-- LSF-WIKI-MANAGED -->
# Capsule and package development

The maintained Rust echo component demonstrates the current WIT contract, generated bindings, guest imports and portable package path. Use the pinned toolchain and `make echo-capsule`; keep component bytes, manifest and WIT definitions in agreement.

| Stage | Current behavior |
| --- | --- |
| Component validation | Bounded typed WIT/manifest checks and exact imports/exports. |
| Package construction | Deterministic portable capsule or asset-bundle profiles with exact layer digests. |
| Observed build | Bounded selected Git archive, recorded current recipe material and actual maintained build execution. |
| Inventory | Normalized dependency inputs and a restricted CycloneDX 1.6 SBOM. |
| Signing | Separate authorized publisher and builder host APIs over exact encoded claims. |
| Distribution | OCI package and detached evidence; no private keys in build children. |
| Admission | Configured trust, provenance, SBOM and runtime-compatibility checks before publication. |

Observed provenance separates supplied/asserted identity from execution observations. The repository name is operator-asserted. Captured source, recipe files, tool identities and output hashes have explicit scope. The build is lockfile-only and nonhermetic, and the restricted in-toto statement makes no SLSA conformance claim. The generator's unsigned handoff is not admission authority.

The maintained build supervisor bounds combined output and deadlines without per-pipe reader threads or retained logs. Windows uses a hidden owned Job; Linux owns an unreaped process group. This trusted-recipe containment covers ordinary children, not deliberate session escape or cleanup after an uncatchable host termination. It is distinct from the strict isolated native compiler sandbox.

The SBOM records the roles actually observed or declared: guest/build dependencies, proc macros, build scripts, WIT, tools, assets, components and renderers. Source and license availability remain explicit. The dependency inventory is incomplete; no invented graph or license attribution fills gaps. SPDX expressions are checked against the pinned parser/profile.

An embedded SBOM avoids a final package-digest cycle. A detached referrer can associate those exact same bytes with the completed package. The normalized `sbom-inputs.json` is a producer input, not itself an extra package layer.

The maintained observer can export a compatibility fixture with `--legacy-output-dir` from the same build. It uses a distinct fresh output directory and preserves the exact built bytes. This does not turn the unsigned fixture into a trusted package.

Browser assets and renderer/SSR package profiles describe content and associations. General HTTP serving, browser hydration and renderer host integration remain planned under [#44](https://github.com/KirilsTurkins/latent-service-fabric/issues/44). Package support alone is not a hosting runtime.

For evolution, compare real packages through the bounded host API. Named WIT definitions, field/case order and dependencies matter; formatting can be identical structurally while bytes differ. Explicit unknown/unsupported analysis denies replacement. See [Contracts and APIs](Contracts-and-APIs).

Authorities: [creating a capsule](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/component-development/creating-a-capsule.md), [packaging](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/component-development/packaging.md), [SBOM](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/component-development/sbom.md), [build provenance](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/reference/build-provenance.md).
