# Ownership-local CI command contracts

Current workflow contracts retain required job identities, while ordinary test
cases are discovered from their prepared executable or Python module.
`tools/ci_coverage.py` reads reviewed expectations from `tools/ci/contracts/` and
compares them with the source under test. It never writes expected records.
`tools/ci/suites.json` remains the single Rust suite/selection catalogue.

## What is reviewed, and where

Every semantic fragment declares `latent.ci.contracts.v1`, its kind and a review reason.
The reader discovers fragments in deterministic path order without a global
fragment index or aggregate checksum. Workflow filenames retain their `.yml` or
`.yaml` extension so equal stems cannot collide.

| Fragment | Review boundary |
| --- | --- |
| `workflows/ci.yml/workflow.json` | Workflow-wide policy and required job identities |
| `workflows/ci.yml/jobs/rust.json` | Complete ordered current job/step definitions |
| Delegated scripts and test controllers | Protected code-owner review; source digests are generated diagnostics |
| Python modules | Current discovery and recorded execution, with targeted suppression controls |

The workflow model retains every parsed field, including unfamiliar fields. It
protects triggers/filters, `needs`, conditions, runners, matrices, permissions,
environments, defaults, shell and directory inheritance, tolerated failures,
timeouts, concurrency, ordered prerequisites, action inputs, reusable-workflow
inputs/secrets, and aggregation. Unknown fields cannot disappear during
comparison. JSON unknown envelope fields, duplicate identities, duplicate/merge
YAML keys, aliases/tags, unsafe paths, symlinks and unsupported schemas fail closed.

Historical Python and owner records remain readable by the isolated migration
fixture, but active validation does not compare ordinary case names, setup ASTs,
or delegated script bytes to committed snapshots. Discovery fails on an empty
suite, duplicate cases, missing execution, failures, unauthorized skips and
expected failures. Named special qualifications remain explicit obligations.

Step lists are never sorted. Use an explicit step `id` for new commands. Existing
name-based run identities remain supported. An existing explicit ID takes
precedence over a display name. A renamed command needs review of its current
replacement; a pin update is not permission to rename it.

## Action revisions are not command fingerprints

The structural contract retains the action repository/path and the full
invocation, but not the immutable revision. The actual revision stays in the
workflow and is independently checked by the existing
[action-pin policy](../development/workflow-action-pins.md). That policy still
requires immutable references, readable version comments, safe local paths and
maintainer review of upstream source changes.

Updating only the reviewed immutable revision of the same action (or its
version comment/YAML presentation) needs **no command-contract edit**. Replacing
the action repository/path, changing inputs, adding permissions or moving a
prerequisite is a structural change and fails until its contract is reviewed.
A different immutable SHA is different executable upstream code; structural
identity is not behavioral equivalence, approval, or evidence that upstream is
safe. Workflow/shared-tooling changes retain conservative full CI selection.
There is no auto-approval, auto-merge or privileged PR execution path.

## Scoped contributor commands

Install the existing pinned `tools/requirements.lock` dependencies. From the
repository root, validate without changing any tracked file:

```sh
python3 tools/validate_workflow_actions.py
python3 -m unittest tools.tests.test_ci_coverage tools.tests.test_ci_contracts
python3 tools/ci_coverage.py
```

For an intentional existing job change, prepare one **untracked proposal**:

```sh
python3 tools/ci_contracts.py propose job .github/workflows/ci.yml --job rust \
  --reason 'Retain existing runtime coverage and add the reviewed prerequisite'
```

Review the proposed workflow or job fragment under `target/ci/proposals/`
against its corresponding current record. Script edits and ordinary test
additions do not require a fingerprint or case-list proposal. Run the tests
that exercise the changed behavior and request the required owner review for
protected controllers. Source-observation receipts do not approve changes.

## Generated evidence and diagnostics

The documentation path invokes the validator once, in the receipt-producing
step before its Python tests. Its exit status is required and the receipt upload
runs with `always()` when a receipt could be written.

A bounded pre-change execution observation is development CI run `40861664839`
on 2026-10-29 (`29b0cc3e4eff`): Ubuntu 24.04 and Python 3.13.5; the docs job
ran its native-required tooling group (336 tests, no skips), native-required
process group (94 tests, one skip) and deterministic group (16 tests, no skips).
The full-profile Python contract job ran unittest discovery (8,551 tests, 50
skips) without the native-required environment variable, after its own toolchain
and fixture setup. Job elapsed times were 2m30s and 9m24s respectively; their
sum was 11m54s, excluding other jobs. These are a single historical sample,
not a measured saving. The deterministic modules have no native-required
environment or external service prerequisites: the full profile runs them in its
Python discovery job, while docs, website and fast profiles retain the docs-job
execution. The native-required tooling and process groups remain in the docs job
because the full Python context has different prerequisite and skip behavior.
A completed comparable hosted run is needed before reporting any savings.

The validator writes `target/ci/observed-inventory.json`, including on validation
failure when source/Git inspection is possible. The documentation lane runs it
before the broader tooling tests and uploads that receipt with `always()` under
`ci-contracts-<event-sha>`. The artifact label is not the source identity: the
receipt's `testedCommit` comes from the **actual checked-out Git HEAD**, including
GitHub's tested PR merge commit when applicable. A dirty-worktree flag and the
actual relevant source paths/digests distinguish local modifications.

Receipts contain schema version, observed workflow policy/job digests, command
digests, observed Python case identities, and script/source fingerprints. They do not copy the process environment, raw workflow `env` values,
run scripts, secret values or exception text. Malformed source retains the safe
available path hashes and observation-error categories rather than erasing the
failure. Receipt destinations must be untracked and under `target/ci/`; source
contracts and symlinked destinations cannot be overwritten.

`validationStatus: passed` means contract validation passed, **not** that the
commands or tests executed successfully. Existing execution/discovery logs and
result aggregation remain authoritative. Missing outputs, failed/cancelled jobs,
unexpected skips and incomplete job sets still fail `CI result` through the
existing `ci_result.py` owner. An unconditional complete result topology and its
untolerated invocation are additionally checked independently of the snapshot.

A structural mismatch names its workflow/job. Review script and test changes
in their actual source, and inspect discovery and execution results. Receipts are diagnostics, not replacement
expectations. Never copy an observed aggregate back into reviewed inputs.

## Protected controller review

On 4 November 2026, the GitHub branch-protection API for `development` reported
one required approval, required code-owner review, and dismissal of stale
approvals. The current CODEOWNERS file covers workflows, CI contracts, test
controllers and their policy tests. The API reported no CODEOWNERS syntax
errors. The protected aggregate contexts remain `CI result` and `Security
baseline result`. Administrators are not subject to protection enforcement and
can bypass it; an admin merge is not evidence that a code-owner approved the
change. Review source changes and verify the current protection configuration
rather than treating a generated digest as an approval token.

Python suppression checks compare the current test sources with the
GitHub-provided event base without executing a second base-branch test build.
The Python runner records discovered, executed, skipped and failed identities
against the tested source and recipe. Existing platform exceptions are checked
against their baseline source. Direct new skip or discovery controls fail closed;
review must also examine indirect helper and environment changes. A missing comparison commit is a failure, not an approval.

## Lossless migration and rebasing existing PRs

The migration source is development
`2c52ff1a9d260da2fbcd81aa0c420926a5820d98`. Its byte-preserved historical inventory
is `tools/ci/history/commands-v1.json`: **88 historical obligations, 208 current
run blocks, 124 delegated owners, 260 Python modules and 2,675 exact cases**.
Initial sharding compares every `before`, `after`, `coverage`, owner, module/case
and baseline-revision record for exact equality before writing output. The
initial workflow/owner byte hashes must also match, so running migration on a
stale or combined snapshot fails instead of blessing it.

The archive remains unchanged for historical inspection and the one-time
migration tool validates a self-contained old input before converting it.
Current job records no longer carry the old baseline revision, command copies,
or replacement table. Ordinary validation compares current workflow structure
and commands to their ownership-local records and independently checks action
pins and the unconditional result topology. An archived success does not qualify
later source.

At development commit `e8e6b20ffd851ae1f032c8a66943214fe4c628de`, the
transition review checked all 88 archived before rows against the old local
coverage rows and verified that each mapped to a current command in its owner
job. No historical row needed an unmapped retirement. This one-time audit is
not a current source-identity or execution receipt. The obligations map to
current owners as follows:

| Retained obligation | Current owner and evidence |
| --- | --- |
| Profile selection, unconditional aggregate and missing/failing job refusal | `ci.yml` profile/result jobs, `ci_profile.py`, `ci_result.py` and their tests |
| Docs, repository contracts and SDK checks | Current `ci.yml` docs/contracts/sdks job contracts and their maintained validators |
| Rust, doctests, signing compatibility and MSRV | Current `ci.yml` rust/msrv contracts, `ci_cargo.py` recipes and suite discovery |
| OCI/provider and browser execution | Current `ci.yml` OCI and Rust lane contracts, provider/renderer owners and execution receipts |
| Resource/catalog and phase measurements | Current catalog and phase measurement workflow contracts and their resource owners |
| Native release, candidate, VM, attestation and publication | Current native-runtime and native-runtime-release workflow contracts and release gate tests |
| Security scope, secrets, static analysis, dependency audits and fail-closed canaries | Current security-baseline/security-rustsec workflow contracts and security tests |

Exact legacy step spelling, global totals, manual-mode string substitutions and
dated feature-branch exceptions are retired as migration mechanics, not as
runtime evidence. The C qualification tests retain current ordinary PR,
development push and manual-mode coverage. The derived historical C workflow
is frozen at `tools/ci/history/c-guest-closed-filesystem.yml` and checked against
its recorded SHA-256 and historical job identities. The scratch qualification
test checks the current workflow directly. Archived source checks do not execute
or qualify today's workflow. Current job contracts still detect a removed
step or changed prerequisite until its owner is reviewed.

Rebase onto current `development` and transfer only affected current workflow
or job records. Do not regenerate the archive or
add a shared migration exception for independent owner changes. Real conflicts
in the same current job or test still require joint review. The isolated Git
fixture exercises independent job and test-module changes without a shared
migration table.

## Dependency grouping evaluation

The existing Dependabot configuration already limits GitHub Actions proposals
and schedules weekly updates to `development`. Grouping related minor/patch
action updates could reduce concurrent PR volume, but also combines more upstream
executable changes into one review and complicates isolating regressions. Keep
major migrations separate and retain manual pin/provenance review in either
case. This change leaves grouping unchanged: ownership-local structural contracts
solve the artificial hash conflict without depending on grouping or changing the
supply-chain review policy.
