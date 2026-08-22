# Development Workflow

> **Document role:** Contributor orientation. `CONTRIBUTING.md`, `VALIDATION.md`, toolchain files, issue requirements, and repository policies are authoritative.

## 1. Start from an issue or accepted design

Before coding, identify:

- the concrete acceptance requirements;
- affected contract surfaces;
- relevant ADRs or RFCs;
- compatibility impact;
- security and resource-accounting impact;
- required conformance tests or benchmark evidence.

Do not infer a runtime behavior that contradicts an accepted interface or invariant.

## 2. Classify the change

| Change | Expected process |
|---|---|
| Core invariant, dependency direction, execution model, or compatibility promise | ADR |
| Proposal needing review before contract changes | RFC |
| WIT, Protobuf, JSON Schema, Rust trait, or SDK change | Interface review |
| Code behind an accepted seam | Implementation review |
| Paging, fusion, native isolation, or other unpromoted experiment | Keep under `research/` until promoted by ADR |

## 3. Use a focused branch

Use a descriptive prefix such as `feat/`, `fix/`, `docs/`, `refactor/`, `test/`, or `research/`. Keep unrelated architectural or formatting changes out of the branch.

## 4. Preserve contract authority

- WIT is authoritative for guest-visible component contracts.
- Protobuf is authoritative for control-plane and generic management RPCs.
- JSON Schema is authoritative for declarative resources.
- Rust traits define internal seams.
- SDK surfaces must preserve rather than redefine semantics.

Generated artifacts belong only where generation is reproducible and repository policy permits them.

## 5. Validate locally

Install the exact pinned toolchain and run:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make validate
```

The root `Cargo.lock` is authoritative. Validation must not rewrite handwritten contracts.

The explicit MSRV check is:

```bash
rustup toolchain install 1.94.1 --profile minimal
cargo +1.94.1 check --workspace --all-targets --all-features --locked
```

## 6. Test the architectural claim

Compilation is necessary but insufficient. Add or update the relevant conformance, compatibility, security, integration, chaos, leak, or benchmark specification.

A scheduler change, for example, should address bounded queues and fairness. A cell change should address reset and leakage. A state change should address conflicts, commit inspection, idempotency, and ambiguity.

## 7. Prepare the pull request

A pull request should explain:

- affected contract surfaces;
- compatibility impact;
- security impact;
- resource-accounting impact;
- relevant ADR or RFC;
- tests and benchmark evidence;
- generated artifacts and how they are reproduced;
- known limitations.

Review the diff for accidental generated files, unbounded allocations, ambient guest access, hidden retry assumptions, and service-specific persistent resources.

## 8. Keep the Wiki non-normative

Update canonical repository documentation first. Then update the Wiki summary or navigation if the merged change affects reader guidance.

Do not place a unique security requirement, compatibility promise, or protocol rule only in the Wiki.

## Canonical sources

- [CONTRIBUTING.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/CONTRIBUTING.md)
- [Toolchain baseline](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/development/toolchain.md)
- [VALIDATION.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/VALIDATION.md)
- [Architecture decisions](https://github.com/KirilsTurkins/latent-service-fabric/tree/release/adr)
- [RFCs](https://github.com/KirilsTurkins/latent-service-fabric/tree/release/rfcs)
