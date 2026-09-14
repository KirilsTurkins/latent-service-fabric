# Security baseline

Phase 3 issue [#282](https://github.com/KirilsTurkins/latent-service-fabric/issues/282) is being delivered in bounded slices. The first implemented slice is the Rust dependency advisory baseline in [`.github/workflows/security-rustsec.yml`](../../.github/workflows/security-rustsec.yml). It does not complete the broader secret-scanning, static-analysis, repository-setting, SDK-ecosystem, exception-management, or integrated runtime-security work in #282.

## RustSec advisory scan

The workflow uses [`cargo-audit`](https://github.com/rustsec/rustsec/tree/main/cargo-audit) `0.22.2`, the upstream RustSec release reviewed on 2026-09-13. The scanner is installed from crates.io with the published package lock (`cargo install --locked`) under the repository's reviewed Rust 1.97.1 toolchain action. External workflow actions retain the immutable identities documented in [workflow-action-pins.md](workflow-action-pins.md).

The scan is deliberately independent of the ordinary docs/full CI profile:

- pull requests into `development` run it only when `Cargo.lock`, a `Cargo.toml`, the Rust toolchain, an audit configuration, platform WIT, installed Wasmtime host imports/surface validation, component binding generation, or this baseline's workflow/test/documentation surfaces change;
- pushes to `development` and `release` use the same dependency-sensitive selection;
- the weekly schedule and manual dispatch explicitly scan **both** maintained branches, even when their lockfiles have not changed.

GitHub emits `schedule` and `workflow_dispatch` events only for workflows present on the repository's default branch. LSF's default branch is currently `release`, while feature delivery integrates through `development`. Therefore the scheduled/manual matrix is defined and reviewable in this slice, but it does not become an active periodic repository control merely by merging this PR into `development`; normal promotion must also place the workflow on `release`. This slice does not bypass the repository's integration policy to activate it early.

Unrelated Markdown-only changes do not start a Rust dependency scan; this baseline runbook is an explicit exception so its described commands stay covered. The broader #282 work still needs lightweight secret/static coverage appropriate for documentation changes; this advisory slice does not claim that coverage.

### Untrusted pull-request boundary

A pull-request checkout is treated as untrusted scan input, not as scanner configuration. Scanner installation changes to runner-owned temporary storage first and uses a separate temporary `CARGO_HOME`, so a PR cannot supply repository-local Cargo configuration or aliases to the install step. The audit invokes the exact installed `cargo-audit` binary directly from runner-owned storage rather than invoking `cargo audit` through the checked-out Cargo configuration.

Direct invocation still requires the `audit` subcommand: `cargo-audit audit --db ... --no-fetch --file ...`. The top-level `cargo-audit --version` reports `cargo-audit 0.22.2`; the subcommand version has a different display name. Both maintained-branch and change scans use the same verified invocation.

The scan also passes `--file` with the absolute committed `Cargo.lock` path and executes from runner temporary storage. In `cargo-audit`, an explicitly supplied lockfile path is loaded directly rather than taking the missing-lockfile fallback that can ask Cargo to generate a lockfile. The workflow rejects a symlinked lockfile and caps its size at 8 MiB before parsing it. It does not execute workspace builds, build scripts, tests, examples, or package metadata from the pull request.

## Advisory database freshness and evidence

Every job creates a fresh shallow clone of the [`RustSec/advisory-db`](https://github.com/RustSec/advisory-db) `main` branch in runner-owned temporary storage. It then resolves the remote `main` identity independently and requires the cloned commit to equal that remote identity before scanning. The audit itself runs with `--no-fetch` against that verified checkout.

This defines *fresh* as "the exact `main` identity advertised by the required upstream at scan time", not "the database contains a commit newer than an arbitrary wall-clock age". A quiet advisory database is therefore not mislabeled stale. Clone, remote-identity, installation, or audit failures fail the job instead of being treated as an empty advisory result.

The job summary records:

- exact `cargo-audit` version;
- exact advisory-database commit;
- SHA-256 of the scanned `Cargo.lock`;
- source revision, and the maintained branch name for scheduled/manual scans.

These are workflow observations, not a security certification or a statement that an advisory is reachable in LSF. Reachability and remediation still require the issue-specific analysis used for work such as #279.

## Execution bounds

The job has a 15-minute outer deadline. Scanner installation, advisory-database clone, remote identity lookup, and the actual audit each have smaller explicit process deadlines. Commands use no repository write token, `pull_request_target`, automatic dependency mutation, automatic merge, or advisory suppression.

There is currently no checked-in RustSec exception list. If a future advisory cannot be removed immediately, #282 requires any exception mechanism to identify the exact finding/package, rationale, owner, and expiry; this slice intentionally does not introduce a blanket ignore path.

## Remaining #282 work

The following remain required before #282 can close:

- activation/evidence of the scheduled/manual matrix after the workflow reaches default `release` through normal promotion;
- inventory and advisory coverage for supported non-Rust SDK ecosystems;
- repository vulnerability-alert/security-update configuration;
- secret scanning and push protection or a documented equivalent where unavailable;
- scoped secret and static-analysis checks, including lightweight coverage for documentation changes;
- expiring, reviewed exception/triage mechanics;
- harmless pass/fail fixtures for vulnerable dependencies, synthetic secrets, expired exceptions, unavailable scanners/databases, and fork permissions;
- final operator/security documentation with representative results and the reviewed repository settings.

The RustSec workflow complements runtime/adversarial evidence under #238 and the Phase 3 gate #240. Passing it does not prove guest isolation, provider safety, capability authorization, or production hardening.
