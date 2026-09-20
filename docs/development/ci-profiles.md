# CI validation profiles

The [CI workflow](../../.github/workflows/ci.yml) selects validation from the
complete changed-path inventory, then publishes one `CI result` check. It does
not use workflow-wide path exclusions that could leave a check pending.

| Profile | Selection | Validation |
| --- | --- | --- |
| Documentation | Every changed path is approved Markdown or a product documentation SVG. | Document links, anchors, fences, SVG accessibility and validator regressions, plus the actual static website checks. |
| Website | Documentation mixed with known website TS/JS/CSS/config/lock/metadata, or published MDX. | The same docs checks plus website types, unit tests, both production base paths and browser journeys. Product builds remain skipped. |
| Full | Product or SDK/example source, shared tools, workflows, schemas, frozen profiles, benchmark evidence or unknown/mixed paths; manual runs; unavailable history. | Docs and website checks plus all six existing Rust, MSRV, catalog, contracts, registry and SDK jobs. |

The conservative path allowlist lives in [the classifier](../../tools/ci_profile.py).
File extensions alone do not establish that a file is documentation. In
particular, benchmark evidence and the frozen Phase 2 resource profile stay on
the full path. A mixed website/product change also runs full validation. MDX is
executable website source and always receives the website build/type/unit/browser
suite. Symlinks and executable-mode changes cannot select either narrow profile.

PR selection compares the exact base/head merge base with the head. Pushes
compare the event's before/after commits. Git provides the complete inventory
without the changed-file cap of workflow path filters. Renames include their
old and new paths, and deletions are included. Bounded shallow fetches request
commit/tree history without downloading historical benchmark blobs. Missing
history selects full validation; malformed events or Git failures fail the
selection job. Manual dispatch always runs the full profile, with the separate
100,000-release probe still disabled unless explicitly requested.

The documentation validator checks the required and nonempty document inventory,
including references to other tracked files and directories. It does not run
the full Python suite, compile Rust, start a registry or replay benchmark
receipts. It checks local links; external URL availability and visual layout
still need review when they change. SVG render inspection remains appropriate
for layout edits.

`CI result` runs even if selection or another job fails. Its
[tested aggregator](../../tools/ci_result.py) accepts only a complete inventory
with every selected job successful. Under the documentation and website profiles,
the six full-suite jobs must be skipped; their skipped status alone is not the
validation result. Use `CI result` as the branch-protection status context.
Existing review requirements remain independent of profile selection.

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

Within the full Rust job, the Angular qualification step reuses the already
built Rust probe. It runs for renderer sources, the Wasmtime/bindings crates,
the web WIT, Cargo/toolchain inputs and the CI selector/workflow. Empty or
uncertain comparisons and manual dispatch select it too. Unrelated source
changes do not rebuild Angular; documentation-only changes still skip Rust.
The step uses a separate locked npm cache, disables dependency lifecycle scripts,
and executes native Wasmtime failure probes plus actual browser hydration.

The same selection also covers the maintained Angular build recipe, its signing
and admission code, package CLI, source/evidence schemas and process/inventory
helpers. It reuses the provisioned npm tree and existing Cargo test harnesses
to build a real application, verify its publisher/builder/SBOM evidence, render
fresh activation state and hydrate the exact generated browser bundle. Build and
runtime probes have separate finite deadlines. SDK-only changes and
documentation-only changes do not select these Angular build probes.
