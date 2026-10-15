# CI validation profiles

The [CI workflow](../../.github/workflows/ci.yml) selects validation from the
complete changed-path inventory, then publishes one `CI result` check. It does
not use workflow-wide path exclusions that could leave a check pending.

| Profile | Selection | Validation |
| --- | --- | --- |
| Documentation | Every changed path is approved Markdown, a product documentation SVG, or a known GitHub issue form / optional chooser configuration. | Document links, anchors, fences, SVG accessibility, bounded offline issue-form YAML validation and validator regressions, plus the actual static website checks. |
| Website | Documentation mixed with known website TS/JS/CSS/config/lock/metadata, or published MDX. | The same docs checks plus website types, unit tests, both production base paths and browser journeys. Product builds remain skipped. |
| Host correctness (`fast`) | Source changes whose complete reverse-dependent closure remains inside the catalogue's approved narrow packages. | Docs, website, selected host formatting/check/Clippy/build/discovery/execution and selected MSRV checks. |
| Full | Runtime-sensitive product or SDK/example source, shared tools, workflows, schemas, frozen profiles, benchmark evidence or unknown/mixed paths; manual runs; unavailable history. | Docs and website, selected host correctness, and the Rust, MSRV, catalog, contracts, registry and SDK job families. |

The conservative path allowlist lives in [the classifier](../../tools/ci_profile.py).
File extensions alone do not establish that a file is documentation. In
particular, benchmark evidence and the frozen Phase 2 resource profile stay on
the full path. A mixed website/product change also runs full validation. MDX is
executable website source and always receives the website build/type/unit/browser
suite. Symlinks and executable-mode changes cannot select either narrow profile.
The only GitHub issue-template YAML eligible for the documentation profile is
`.github/ISSUE_TEMPLATE/bug_report.yml`, `architecture.yml`, and the optional
exact `config.yml`; unknown issue-template files and other `.github` changes stay
on the full profile.

The [suite selector](../../tools/ci_suite_inventory.py) reads actual workspace
manifests, including inherited, optional, development, build and target-specific
edges. The entire reverse-dependent closure must fit `narrowPackages`; being in
the larger `fastPackages` candidate list does not make a package host-only.
Current state/core changes require full CI; an isolated workflows change can
select `fast`. Full changes also get host feedback, which cannot replace their
runtime/provider/browser obligations. Manifest changes, deletions and unknown
inputs conservatively select full validation. Inspect the emitted package list
and expected jobs rather than copying a historical selection.

PR selection compares the exact base/head merge base with the head. Pushes
compare the event's before/after commits. Git provides the complete inventory
without the changed-file cap of workflow path filters. Renames include their
old and new paths, and deletions are included. Bounded shallow fetches request
commit/tree history without downloading historical benchmark blobs. Missing
history selects full validation; malformed events or Git failures fail the
selection job. Manual dispatch always runs the full profile, with the separate
100,000-release probe still disabled unless explicitly requested.

The documentation validator checks the required and nonempty document inventory,
including references to other tracked files and directories. It also runs the
bounded issue-form validator against the known form paths and optional chooser
configuration. That validator reads at most 64 KiB per ordinary UTF-8 file,
rejects duplicate keys, aliases/anchors/tags, multiple YAML documents and
unsupported shapes, and validates only the repository's currently supported
`markdown`, `input` and `textarea` subset plus bounded HTTPS contact links. It
does not contact GitHub or attempt to support future form element types
implicitly.

The documentation job does not run the full Python suite, compile Rust, start a
registry or replay benchmark receipts. It checks local links; external URL
availability and visual layout still need review when they change. SVG render
inspection remains appropriate for layout edits.

`CI result` runs even if selection or another job fails. Its
[tested aggregator](../../tools/ci_result.py) accepts only a complete inventory
with every selected job successful. Under the documentation and website profiles,
the six full-suite families and unselected host job must be skipped; their
skipped status alone is not the validation result. Use `CI result` as the
branch-protection status context.
Existing review requirements remain independent of profile selection.

The host-only profile additionally requires `fast` and `msrv` but skips the other
full-suite families. The full profile requires its selected host job and every
full family. [The expected-job contract](../../tools/ci_suite_inventory.py)
is recomputed by the result gate; an absent job is not an intentional skip.
Security uses its own independent coordinator and result aggregate.

The [reusable website workflow](../../.github/workflows/docs-site.yml) uses pinned
Node/npm/dependencies and Chromium, fresh isolated npm installation with lifecycle
scripts disabled, and no Pages permissions, inherited secrets or dependency cache.
The package manager itself is pinned in `website/toolchain/package-lock.json`;
its bundled dependencies are included in the repository's advisory inventory.
Its artifact name binds the current source SHA, run and attempt; only the project
build and explicitly listed browser receipts are uploaded. Skipped, cancelled or
failed site jobs fail `CI result`. This validation artifact alone is not a Pages
publication or documentation-gate completion.

The workflow policy accepts GitHub.com's documented
[`$/` same-commit references](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows#calling-a-reusable-workflow),
while still rejecting dynamic, escaped or `@ref`-suffixed local paths and inspecting
the referenced executable dependencies. External actions retain full-SHA pins.
This syntax is not supported on GitHub Enterprise Server.

Full jobs can reuse [dependency caches](ci-caching.md), but cache hits never
replace tests. The run summary records the selected profile, reason and changed
file count. Inspect those fields before attributing a shorter run to caching.
To force a complete check without a code change, manually dispatch CI on the
branch with the heavy catalog option left false.

## Full execution layout

The [runtime matrix](../testing/ci-lanes.md) has eight required variants: checks,
tests, qualification, provider, renderer-public, renderer-angular, publications
and angular-t1. Each producing runner retains its own current workspace Cargo
inventory. Complete ordinary tests, custom harnesses, separate doctests and
signing compatibility remain in the tests lane; physical qualification stays
separate from provider/renderer runners.

Contracts have seven variants: Python, bindings, runtime, standalone,
SDK-provider, measurement smoke and optimization smoke. The complete Python suite
runs without concurrent native fixture writers. Each native lane prepares its
own registered inputs; the default local contract command still runs all lanes.

The existing renderer decision selects actual Angular build/admission/runtime,
public browser and T1 work for affected renderer/Wasmtime/WIT/build/source inputs
and uncertain/manual selection. Preparation, execution, negative controls,
hydration and physical cleanup keep their separate owners and deadlines. Normal
CI configures two bounded provider/renderer coordinator workers; manual dispatch
can select one or two, independently of Actions matrix parallelism. See
[performance and coverage](ci-performance.md) for source-bound observations.

## Selected process ownership

See [owned selected test processes](owned-test-processes.md) for prerequisite,
prepared-artifact, deadline, cleanup and diagnostic contracts.
