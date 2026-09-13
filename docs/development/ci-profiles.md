# CI validation profiles

The [CI workflow](../../.github/workflows/ci.yml) selects validation from the
complete changed-path inventory, then publishes one `CI result` check. It does
not use workflow-wide path exclusions that could leave a check pending.

| Profile | Selection | Validation |
| --- | --- | --- |
| Documentation | Every changed path is an approved documentation Markdown file or a product documentation SVG. | Local document links, heading anchors, Markdown fences, SVG structure/accessibility and focused validator/profile regression tests. |
| Full | Any code, dependency, workflow, configuration, schema, artifact, evidence or unrecognized path changes; manual runs; unavailable comparison history. | Documentation checks plus all six existing Rust, MSRV, catalog, contracts, registry and SDK jobs. |

The conservative path allowlist lives in [the classifier](../../tools/ci_profile.py).
File extensions alone do not establish that a file is documentation. In
particular, benchmark evidence and the frozen Phase 2 resource profile stay on
the full path. A mixed Markdown/code change also runs full validation.

PR selection compares the exact base/head merge base with the head. Pushes
compare the event's before/after commits. Git provides the complete inventory
without the changed-file cap of workflow path filters. Renames include their
old and new paths, and deletions are included. Bounded shallow fetches request
commit/tree history without downloading historical benchmark blobs. Missing
history selects full validation; malformed events or Git failures fail the
selection job. Manual dispatch always runs the full profile, with the separate
100,000-release probe still disabled unless explicitly requested.

The documentation validator checks the current tracked document inventory,
including references to other tracked files and directories. It does not run
the full Python suite, compile Rust, start a registry or replay benchmark
receipts. It checks local links; external URL availability and visual layout
still need review when they change. SVG render inspection remains appropriate
for layout edits.

`CI result` runs even if selection or another job fails. It accepts only a known
profile with every selected job successful. Under the documentation profile,
the six full-suite jobs must be skipped; their skipped status alone is not the
validation result. Use `CI result` as the branch-protection status context.
Existing review requirements remain independent of profile selection.

Full jobs can reuse [dependency caches](ci-caching.md), but cache hits never
replace tests. The run summary records the selected profile, reason and changed
file count. Inspect those fields before attributing a shorter run to caching.
To force a complete check without a code change, manually dispatch CI on the
branch with the heavy catalog option left false.
