# latent-signing

Local package signing, strict Ed25519/DSSE evidence and bounded publisher/builder trust verification. Package signatures and build attestations bind different assertions to exact subjects. Web provenance has explicit componentless build profiles rather than pretending every package contains executable code.

Verification returns a checked proof under captured trust/time state. A later catalog acceptance still needs a currentness fence; cryptographic success alone does not authorize a tenant, route, guest or native loader.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/signer.rs](src/signer.rs) | LocalSigner over an explicitly approved host key and exact package subject. |
| [src/keys.rs](src/keys.rs) | Bounded key generation/import ownership. |
| [src/dsse.rs](src/dsse.rs) | Finite DSSE encoding/inspection with explicit purpose. |
| [src/verify.rs](src/verify.rs) | PublisherVerifier, captured proof and current trust recheck. |
| [src/builder_verify.rs](src/builder_verify.rs) | Separate builder trust and build-provenance verification. |
| [src/provenance.rs](src/provenance.rs) | Restricted build assertions and source/input identity. |
| [src/web_provenance.rs](src/web_provenance.rs) | Explicit supplied-file and observed web-build provenance profiles. |
| [src/policy.rs](src/policy.rs) | Publisher policy, revocation and trust-state identity. |

## Execution and ownership

1. Construct an exact package signing subject and bounded evidence using an explicitly selected key/profile.
2. Inspect untrusted evidence before crypto and verify its signature/assertions against the captured current trust snapshot.
3. Observe trusted time monotonically, preserve revocation/generation identity and recheck before returning a proof.
4. The durable authority persists floors across restart and guards final admission; consumers also match subject/evidence identities.

## Integration boundaries

PublisherVerifier has bounded synchronous cryptography and no network lookup or positive verification cache. Its in-process time high-water mark is not a durable restart floor. A builder assertion is different from observing a local compiler, and an SBOM reference is an exact content association rather than a security endorsement.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-artifacts](../latent-artifacts/README.md).

Consumers with normal workspace dependency edges include [latent](../../apps/latent/README.md), [latent-policy](../latent-policy/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-signing.lib.latent-signing
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`requirements_are_canonical_and_bound_into_policy_identity`](src/builder_policy/tests.rs)
- [`unknown_duplicate_null_and_noninteger_policy_fields_fail_closed`](src/builder_policy/tests.rs)
- [`duplicate_keys_rules_weak_keys_and_invalid_sources_are_rejected`](src/builder_policy/tests.rs)
- [`lower_rule_bounds_and_typed_spare_capacity_apply_at_adoption`](src/builder_policy/tests.rs)

Integration targets: [tests/build_provenance.rs](tests/build_provenance.rs), [tests/guest_provenance.rs](tests/guest_provenance.rs), [tests/publisher_trust.rs](tests/publisher_trust.rs), [tests/trust_inputs.rs](tests/trust_inputs.rs).

## Related documentation

- [Package publisher signatures and current trust](../../docs/reference/publisher-trust.md)
- [Build observations and current builder trust](../../docs/reference/build-provenance.md)
- [Authenticated package admission](../../docs/reference/package-admission.md)
- [ADR-0022: Bind publisher proofs to current explicit trust](../../adr/0022-bind-publisher-proofs-to-current-explicit-trust.md)
- [ADR-0023: Bind build attestations to observed inputs and builder trust](../../adr/0023-bind-build-attestations-to-observed-inputs-and-builder-trust.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
