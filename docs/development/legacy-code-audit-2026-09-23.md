# Legacy code and test audit

Audited `development` at `8eea5c73` on September 23, 2026, after the Phase 0
runner retirement and the catalog, SDK, capability, and audit API cleanups.
The audit covered tracked application/crate sources, SDKs, repository tools,
test registration, workflow commands, and recent removals. Open SDK authoring
and Windows workflow PRs were checked for overlap.

Candidates were traced through source references, entry points, Cargo targets,
and the exact CI inventories. A legacy name alone is not a removal criterion.
The removals below have no live runtime, CLI, or workflow caller; their only
remaining consumers were tests of the unused helpers themselves.

## Removed surfaces

| Removed code and tests | Evidence and maintained coverage |
| --- | --- |
| `tools/tests/phase0_test_environment.py` and its two unit tests | The shell-runner tests that imported the environment sanitizer and fake native-Linux tools were removed in PR #493. Only the sanitizer's own test module remained. The real build-environment policy and its tests still serve current optimization tooling. |
| `test_target` and `test_filters` in the OCI registry runner, plus their old argument-list test | The runner now uses the registered suite and prepared executable through `selected_contract` and `execute`; neither helper participates. The replacement regression calls the runner entry point for normal registry, observed-provenance, and web modes and checks the exact selected suite/cases. |
| `ci_lanes.require_job_results` and its five synthetic job-result tests | No coordinator or workflow calls this alternate policy. The actual merge gate is `ci_result.validate`; its existing tests exercise every CI profile, failed/cancelled/skipped jobs, missing outputs, and unexpected jobs. |
| `ci_cargo_cache.writer_allowed` and its synthetic event/ref matrix | Cache writes are selected by GitHub expressions in `ci.yml`, not by the Python helper. The retained workflow regression checks those expressions and the cache scope directly. |
| `security_scope.validate_results` and tests of the duplicate model | The security workflow executes its own inline aggregate. The failure/cancellation matrix now executes that exact script, including missing jobs/selection outputs and unexpected success or skip states. |

The reviewed Python case/module inventory and changed delegated-owner hashes in
`tools/ci/commands.json` are updated alongside these removals. Workflow commands,
job requirements, and the Rust suite inventory retain their existing contracts.

## Retained after review

- The Wasmtime Phase 0 echo facade still drives maintained echo and containment
  integration tests through `tools/validate_contracts.sh`. Its cancellation,
  isolation, resource ownership, and cleanup coverage is current.
- Catalog and RPC tests that reject obsolete formats protect current input and
  persistence boundaries. They are not tests of a supported migration path.
- Historical evidence readers, exact legacy dependency-inventory exceptions,
  and benchmark build recipes support pinned source revisions and archive replay.
  Removing them based on their names would break retained evidence validation.
- SDK semantic entry points with old identity-oriented names now invoke the
  current shared profile tests; they are still registered and executable.
- CI lane inventory validators are used by tests that inspect the real workflow
  and suite inventory. A test-only caller is appropriate for these checks.

## Validation scope

Run the affected Python suites, the real CI result/ownership/inventory guards,
repository and foundation validation, and documentation validation. Use Linux
for symlink and native process ownership tests; Windows without symlink
privileges cannot execute the existing cache symlink regression. This cleanup
does not require catalog-scale runs, profiling campaigns, or resource soaks.
