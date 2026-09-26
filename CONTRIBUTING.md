# Contributing

Contribute bug fixes, tests, documentation and new capabilities through pull
requests into `development`. Start with the step-by-step
[contributor guide](docs/contribute/index.md), then use the rules below for the
kind of change you are making.

To build an application on LSF, use the [packaged developer workflow](docs/start/application-development.md).
It includes the six guest-language toolchains, project templates and real-node
tests. The contributor toolchain below is for changing LSF itself.

Read the full issue and its existing pull requests before starting. Current
implementation and documented supported contracts determine behavior; proposed
interfaces and historical measurements do not establish a delivered feature.
Maintainer planning and acceptance records are collected separately in
[engineering records](docs/development/engineering-records.md).

## First contribution

Start with the live [open `good first issue` queue](https://github.com/KirilsTurkins/latent-service-fabric/issues?q=is%3Aissue%20is%3Aopen%20label%3A%22good%20first%20issue%22). Read the selected issue completely, check its assignee and linked or existing pull requests, and coordinate on the issue before starting work that could overlap another contribution.

Create your branch from the current `development` branch and target `development` in the pull request, even though the repository's GitHub default branch is `release`. Follow the existing branch conventions for the kind of change, for example `chore/<short-description>` for documentation or maintenance and `feat/<short-description>` for feature work.

Install the pinned prerequisites from the [development toolchain guide](docs/development/toolchain.md), then select checks appropriate to the change using [VALIDATION.md](VALIDATION.md). Keep expensive scale probes, profiling, calibration, and resource soaks opt-in unless the issue or acceptance criteria explicitly require them.

For exact local planning, preparation, execution, and failure reproduction, use the [local test entry point](docs/development/local-tests.md). It reads the same registered suite/recipe inventory as CI; `run` never compiles or broadens a selection.

For timing and cancellation tests, use the [deterministic testing guide](docs/development/deterministic-tests.md), shared clock and current-readiness helpers, and executable deadline/cancellation examples. Assert actual resource ownership; do not use sleeps or yield counts as readiness witnesses.

## Change categories

- **ADR:** a decision that changes a core invariant, dependency direction, execution model, or compatibility promise.
- **RFC:** a proposal requiring review before contracts are changed.
- **Interface change:** a compatible or incompatible update to WIT, Protobuf, JSON Schema, Rust traits, or an SDK surface.
- **Implementation change:** code behind an accepted interface.

## Interface rules

LSF is in alpha. Remove obsolete APIs, adapters, formats, command aliases and
deprecated code when their replacements are adopted; no deprecation waiting
period or compatibility with superseded Phase 1/2 behavior is required. Update
callers, generated surfaces, tests and current documentation in the same change.
Record breaking changes and any required fresh-state setup explicitly. Keep only
compatibility that serves a current supported contract, such as a specifically
qualified native upgrade pair. Historical evidence records what was tested at
its original revision; it does not require the old implementation to remain.

1. WIT is authoritative for guest-visible component contracts.
2. Protobuf is authoritative for control-plane and generic management RPCs.
3. JSON Schema is authoritative for declarative resources.
4. Rust crates must keep the dependency graph acyclic.
5. Platform errors and domain errors must remain separate.
6. No API may imply that a remote or isolated invocation is infallible.
7. No service API may require a persistent service-owned process, listener, thread, or pool.
8. New external effects require explicit idempotency and retry semantics.
9. Experimental paging, fusion, and native isolation work stays under `research/` until promoted by ADR.

## Pull requests

A pull request should include:

- the affected contract surfaces,
- compatibility impact,
- security and resource-accounting impact,
- relevant ADR or RFC,
- conformance tests or a test specification,
- generated artifacts only when generation is reproducible.

The root [`.editorconfig`](.editorconfig) records repository whitespace and newline defaults for supporting editors. It intentionally exempts byte-sensitive fixtures, generated output, pinned upstream WIT data, and retained benchmark evidence. EditorConfig complements rather than replaces `cargo fmt`, generators, or repository validation.

Run `make help` for a concise list of root contributor commands before selecting validation work.

Run checks appropriate to the change using [VALIDATION.md](VALIDATION.md).
Normal validation excludes expensive ignored acceptance tests; request
100,000-release catalog scaling, native profiling, and long resource soaks only
through their documented explicit commands or manual workflow inputs.

For the isolated compiler and native-cache tests, see the
[prepared AOT test input guide](docs/development/aot-test-inputs.md) for build-free
execution, exact executable authentication, and explicit equal-case cost comparisons.
