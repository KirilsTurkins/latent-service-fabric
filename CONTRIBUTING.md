# Contributing

Contribute bug fixes, tests, documentation and new capabilities through pull
requests into `development`. Start with the step-by-step
[contributor guide](docs/contribute/index.md), then use the rules below for the
kind of change you are making.

To build an application on LSF, use the [packaged developer workflow](docs/start/application-development.md).
It uses the published toolkit, project templates and real-node tests. Newer
source workflows have separate requirements in
[Changes since alpha.5](docs/start/development-changes.md). The contributor
toolchain below is for changing LSF itself.

Read the full issue and its existing pull requests before starting. Current
implementation and documented supported contracts determine behavior; proposed
interfaces and historical measurements do not establish a delivered feature.
Maintainer planning and acceptance records are collected separately in
[engineering records](docs/development/engineering-records.md).

Follow the [Code of Conduct](CODE_OF_CONDUCT.md) in issues, reviews and other
project spaces. Its [reporting section](CODE_OF_CONDUCT.md#reporting) explains
how to raise conduct concerns through the SolutionWCMD contact form.

Report suspected vulnerabilities through [SECURITY.md](SECURITY.md), keeping
credentials, exploit details and business snapshots out of public issues and PRs.

## First contribution

Start with the live [open `good first issue` queue](https://github.com/KirilsTurkins/latent-service-fabric/issues?q=is%3Aissue%20is%3Aopen%20label%3A%22good%20first%20issue%22). Read the selected issue completely, check its assignee and linked or existing pull requests, and coordinate on the issue before starting work that could overlap another contribution.

Create your branch from the current `development` branch and target `development` in the pull request, even though the repository's GitHub default branch is `release`. Follow the existing branch conventions for the kind of change, for example `chore/<short-description>` for documentation or maintenance and `feat/<short-description>` for feature work.

Install only the pinned prerequisites needed for your change from the
[development toolchain guide](docs/development/toolchain.md). Native runtime and
process qualification use the declared Linux x86_64 environment; the
[Windows portable subset](docs/component-development/portable-tests.md) does not
replace those checks. Use [VALIDATION.md](VALIDATION.md) to select the boundary
and distinguish local feedback from complete acceptance.

## Change categories

- **ADR:** a decision that changes a core invariant, dependency direction, execution model, or compatibility promise.
- **RFC:** a proposal requiring review before contracts are changed.
- **Interface change:** a compatible or incompatible update to WIT, Protobuf, JSON Schema, Rust traits, or an SDK surface.
- **Implementation change:** code behind an accepted interface.

Read the [ADR index](adr/README.md) and current implementation guide together.
Acceptance of a decision does not establish feature availability. Resolve a
changed invariant through an explicitly scoped ADR; do not silently rewrite an
accepted decision to match code. The recorded
[restore identity variance](adr/0062-host-own-serializable-transactions-and-durable-outcomes.md#implementation-status-and-restore-identity)
is an outstanding example of that distinction.

## Interface rules

LSF is in alpha. Remove obsolete APIs, adapters, formats, command aliases and
deprecated code when their replacements are adopted; no deprecation waiting
period or compatibility with superseded Phase 1/2 behavior is required. Update
callers, generated surfaces, tests and current documentation in the same change.
Record breaking changes and any required fresh-state setup explicitly. Keep only
compatibility that serves a current supported contract, such as a specifically
qualified native upgrade pair or retained transaction format. Alpha status is
not permission to discard durable command outcomes, pending effects or protected
recovery state. Review [state/schema compatibility](docs/architecture/application-schema-compatibility.md)
and [deployment/migration rules](docs/architecture/versioning-and-deployment.md)
before changing persistent formats or recommending a fresh state directory.
Historical evidence records what was tested at its original revision; it does
not require the old implementation to remain.

1. WIT is authoritative for guest-visible component contracts; execution still requires a supported host ABI and installed bindings.
2. Protobuf is authoritative for control-plane and generic management RPCs.
3. JSON Schema is authoritative for declarative resources; a valid declaration grants no capability or runtime authority.
4. Rust crates must keep the dependency graph acyclic.
5. Platform errors and domain errors must remain separate.
6. No API may imply that a remote or isolated invocation is infallible.
7. No service API may require a persistent service-owned process, listener, thread, or pool.
8. New external effects require explicit idempotency and retry semantics.
9. Experimental paging, continuation eviction, fusion and native software fault isolation stay under `research/` until promoted by ADR and conformance evidence. The implemented isolated compiler is a separate boundary.

Use the owning [generation workflow](docs/development/build-foundation.md).
Update authoritative WIT/Protobuf/schema inputs, exhaustive input manifests and
affected generated projections together. Regenerate checked-in SDK models with
their owning generator; do not hand-edit them or introduce another wire schema.
Rust build products belong in Cargo `OUT_DIR` or ignored output directories,
with only explicitly reviewed reproducible fixture exceptions.

When copying or modifying upstream source, retain its license and attribution
texts and record the exact original source and changes. Update [NOTICE](NOTICE)
when its source attributions change. Check that the affected distribution carries
the project notice alongside the applicable upstream texts and inventory;
dependency declarations or an SBOM do not replace those texts.

Guest SDKs and external clients have separate contracts and qualification:
[guest authoring](docs/component-development/guest-sdk.md) covers compiled
components, while the [client profile](sdk/profile/README.md) covers native
transports. Transactional changes additionally require the
[installed runtime](docs/development/installed-transaction-rpc.md) and
[recovery checks](docs/testing/installed-transaction-recovery.md). Preserve atomic
state/outbox/outcome/inbox settlement, original identities, current result and
dispatch authority, and actual native retirement. A compiler capture, model or
fixture double does not establish signed live-node or packaged qualification.

## Validation and tests

[VALIDATION.md](VALIDATION.md) owns check selection. The complete changed-path
and dependency graph selects `docs`, `website`, `fast` or `full`; a crate name or
Markdown extension alone cannot waive obligations. Follow the emitted package
list and [CI profile guide](docs/development/ci-profiles.md). Bare `make` lists
commands; the [Make guide](docs/development/make-commands.md) covers focused tests,
explicit preparation and website targets. `make validate` requires a clean tracked
Linux checkout and a fresh owned output root; it is not every CI,
website/browser, native or packaged acceptance programme. Expensive scale probes,
profiling, calibration and resource soaks remain explicit selections.

Use the [local test entry point](docs/development/local-tests.md) for exact
planning, preparation, execution and failure reproduction. `list`, `explain` and
`plan` inspect metadata; `prepare` may explicitly build inputs; `check` validates
them; `run` never compiles or broadens a selection. Keep the same exact case
selection and fresh owned inventory through preparation and execution.
Prepared bytes, executable discovery and a completed test are different results.
See [prepared AOT inputs](docs/development/aot-test-inputs.md) for custom harnesses
and native compiler/cache ownership.

Register Rust target/case changes and deliberate ignores in the reviewed
[suite catalogue and fragments](docs/testing/ci-suite-inventory.md). Missing,
renamed, unexpectedly ignored or zero-test execution is a failure, not a pass.
For workflow, delegated-script or Python-test changes, use the
[ownership-local CI contract guide](docs/testing/ci-command-contracts.md). Prepare
only the affected review fragments, retain historical obligations, and run the
read-only coverage validator. Immutable action-pin-only changes do not require a
contract refresh; upstream action review and full CI remain mandatory.

For timing and cancellation tests, use the
[deterministic testing guide](docs/development/deterministic-tests.md), shared
clocks and current-readiness helpers. Do not use sleeps or yield counts as
readiness witnesses. Assert actual resource retirement through the
[owned process helpers](docs/development/owned-test-processes.md), retaining the
original deadline and private fixtures. Preserve the dependency DAG: low-level
tests cannot import a runtime harness that depends back on their crate.

## Documentation and examples

Update current guides, reference pages and affected runnable examples in the
same change as their implementation. The website reads `docs/` and `adr/`
directly; do not create a second prose tree. Examples come from owning projects
through [registered source extraction](docs/development/website-examples.md),
not replacement SDK implementations inside the website.

Describe installed behavior and remaining gates explicitly. Development changes
must not appear as features of an older published toolkit. Preserve immutable
released snapshots and use the reviewed
[version/correction workflow](docs/development/website-versions.md) when needed.
Consolidate redundant current prose; retain original source IDs, digests and
outcomes when retiring historical reports through the engineering-records index.

Run [documentation and website checks](docs/development/website.md), including
the rendered journeys appropriate to the change. Keep meaningful anchors and
navigation, follow the [SVG standard](docs/svg-style.md), and review whether a
reader can complete the guide. Automated checks do not certify human usability
or runtime support.

## Pull requests

Use the [pull request template](.github/pull_request_template.md). Include:

- the affected contract surfaces,
- compatibility impact,
- security and resource-accounting impact,
- relevant ADR or RFC,
- conformance tests or a test specification,
- checks actually run, their source/environment and results, including failures,
  unavailable checks and remaining acceptance gates,
- generated artifacts only when generation is reproducible.

The root [`.editorconfig`](.editorconfig) records repository whitespace and newline defaults for supporting editors. It intentionally exempts byte-sensitive fixtures, generated output, pinned upstream WIT data, and retained benchmark evidence. EditorConfig complements rather than replaces `cargo fmt`, generators, or repository validation.

Keep the description aligned with the final change and reviewed base. A draft
records unfinished work; it does not waive required checks, conformance or the
issue's acceptance criteria. Record prepared identities and actual cleanup when
they determine what a test establishes. Redact private paths and payloads from
public diagnostics.

## Commit history and evidence

For temporary stacked review, target the parent branch and identify the parent
PR in the description. Review only the child leaf with
`git log origin/<parent-branch>..HEAD` and
`git diff origin/<parent-branch>...HEAD`. Preserve temporary integration history
on separate refs while the parent is under review.

After the parent has actually been squash-merged, reconstruct the reviewed leaf
on current `development` and restore the PR base to `development`. Before final
review, inspect both `git log origin/development..HEAD` and
`git diff origin/development...HEAD`: they must describe the actual PR diff
without presenting the parent's original commits, checkpoint merges or already
delivered work as new changes. Run fresh main and security CI on that final
head and base. Branch-filtered security workflows may not run against a
temporary parent base; earlier stacked checks do not replace final-base CI.

Use factual commit messages. Describe what the commit changes; claim a test,
qualification, merge or issue closure only when the recorded evidence establishes
that outcome for its exact source. A compiler build, signed package or focused
test pass does not establish full runtime or ticket acceptance. Do not fabricate
authors, dates, test results or completion claims to make a history appear clean.

Before rewriting an existing PR branch, coordinate ownership, preserve its exact
old head on a separate ref, and compare the resulting tree and diff against the
intended source. Push with an explicit `--force-with-lease` for the observed old
head; stop if another writer has advanced it. Do not discard another contributor's
work or erase failed attempts and source snapshots to simplify the history.

Rewritten commit IDs do not change what historical evidence tested. Keep its
original source IDs and artifact digests, rerun the affected checks, and require
fresh CI on the rewritten head. Review is incomplete until the PR description,
commit history, final diff and validation claims agree.
