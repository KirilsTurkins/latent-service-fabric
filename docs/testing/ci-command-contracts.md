# Ownership-local CI command contracts

Issue #732 removes artificial aggregate-file conflicts without changing the
suite selector, test runner, required job names or protected result checks.
`tools/ci_coverage.py` reads reviewed expectations from `tools/ci/contracts/` and
compares them with the source under test. It never writes expected records.
`tools/ci/suites.json` remains the single Rust suite/selection catalogue.

## What is reviewed, and where

Every fragment declares `latent.ci.contracts.v1`, its kind and a review reason.
The reader discovers fragments in deterministic path order without a global
fragment index or aggregate checksum. Workflow filenames retain their `.yml` or
`.yaml` extension so equal stems cannot collide.

| Fragment | Review boundary |
| --- | --- |
| `workflows/ci.yml/workflow.json` | Workflow-wide policy and required job identities |
| `workflows/ci.yml/jobs/rust.json` | Complete ordered job/step definitions and that job's historical replacement obligations |
| `owners/tools/validate_contracts.sh.json` | Exact delegated script fingerprint, retained pending verified approval enforcement |
| `python/test_ci_coverage.py.json` | Exact nonempty module/case identities and reviewed execution/skip guards |

The workflow model retains every parsed field, including unfamiliar fields. It
protects triggers/filters, `needs`, conditions, runners, matrices, permissions,
environments, defaults, shell and directory inheritance, tolerated failures,
timeouts, concurrency, ordered prerequisites, action inputs, reusable-workflow
inputs/secrets, and aggregation. Unknown fields cannot disappear during
comparison. JSON unknown envelope fields, duplicate identities, duplicate/merge
YAML keys, aliases/tags, unsafe paths, symlinks and unsupported schemas fail closed.

Step lists are never sorted. Use an explicit step `id` for new commands. Existing
name-based run identities are retained during this migration so their historical
before/after relationships remain lossless. An existing explicit ID takes
precedence over a display name. A renamed legacy command needs explicit review
of its replacement; a pin update is not permission to rename it.

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

For a script-body change or a Python test addition, select only its owner:

```sh
python3 tools/ci_contracts.py propose owner tools/validate_contracts.sh \
  --reason 'Review the changed contract implementation and its regression tests'
python3 tools/ci_contracts.py propose python tools/tests/test_ci_coverage.py \
  --reason 'Add the explicit regression cases without removing existing cases'
```

Review the proposed file under `target/ci/proposals/` against the corresponding
file in `tools/ci/contracts/`. Copy only the reviewed fragment into that location,
then rerun validation. Proposals refuse to overwrite existing output; inspect or
remove previous proposal output before preparing another version. A workflow-wide
change uses `propose workflow .github/workflows/ci.yml`; a new job gets its own
job fragment plus an explicit workflow-local required-job addition.

The proposal command does **not** change an `unchanged` historical obligation
into an `extended` one, invent a replacement reason, accept a removed job/command,
or bless removed/renamed cases or newly skipped existing tests. Those changes
require explicit manual review of the affected local records and regression
coverage. Historical `before` records remain intact; every `coverage.after`
reference must name an actual required command in its owning job. Adding a case
cannot silently change the Rust catalogue or a custom-harness contract.

## Generated evidence and diagnostics

The validator writes `target/ci/observed-inventory.json`, including on validation
failure when source/Git inspection is possible. The documentation lane runs it
before the broader tooling tests and uploads that receipt with `always()` under
`ci-contracts-<event-sha>`. The artifact label is not the source identity: the
receipt's `testedCommit` comes from the **actual checked-out Git HEAD**, including
GitHub's tested PR merge commit when applicable. A dirty-worktree flag and the
actual relevant source paths/digests distinguish local modifications.

Receipts contain schema version, observed workflow policy/job digests, command
digests, exact Python case identities, guard digests, and script/source
fingerprints. They do not copy the process environment, raw workflow `env` values,
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

A structural mismatch names its workflow/job; owner mismatches require reviewing
the actual script and its local fingerprint; test mismatches require reviewing
that module's names and guards. Receipts are diagnostics, not replacement
expectations. Never copy an observed aggregate back into reviewed inputs.

## Delegated-owner approval: deliberately retained intermediate state

The implementation attempted to inspect the current `development` protection
configuration through GitHub's branch-protection API on 2026-09-29. The integration
returned HTTP 403, `Resource not accessible by integration`. The available branch
metadata reports protected CI result contexts but does not establish required
owner approvals and stale-approval invalidation. Existing `CODEOWNERS` entries
alone are not proof of that enforcement.

Therefore this change **does not complete the owner-fingerprint-to-receipt-only
migration**. Every delegated script keeps its mandatory SHA-256 in its individual
owner contract, in addition to generated execution evidence. The new structural
reader/parser helpers are explicitly named as delegated owners in the reviewed
validation run block. Script changes require reviewing the actual diff, behavioral
regressions and their local fingerprint updates. No branch protection is changed.

Before deleting an owner's committed fingerprint, a follow-up must verify
required approval by the responsible owner, invalidation of stale approvals when
the reviewed change changes, and coverage of the actual owner-script paths;
alternatively it must implement and qualify an equivalent trusted approval gate
bound to that change. Capture enforcement evidence and adversarial regression
results. Until then, retaining fingerprints is the issue's specified safe
intermediate state, not a claim that unenforced `CODEOWNERS` is sufficient.

## Lossless migration and rebasing existing PRs

The migration source is development
`2c52ff1a9d260da2fbcd81aa0c420926a5820d98`. Its byte-preserved historical inventory
is `tools/ci/history/commands-v1.json`: **88 historical obligations, 208 current
run blocks, 124 delegated owners, 260 Python modules and 2,675 exact cases**.
Initial sharding compares every `before`, `after`, `coverage`, owner, module/case
and baseline-revision record for exact equality before writing output. The
initial workflow/owner byte hashes must also match, so running migration on a
stale or combined snapshot fails instead of blessing it.

All historical before/coverage relationships are now active in their destination
job fragments. The archived monolith is read only by migration/regression tools,
never by normal coverage validation. The rollout adds a receipt-validation run
block and explicit parser/storage owners, extends the existing tooling-test
invocation, and updates qualification artifact inputs to retain the contract
directory. These are reviewed additions, not a reset to whatever source exists.

Rebase an existing PR onto the new `development`. For a pin-only update, retain
the reviewed workflow SHA/comment changes and discard that PR's obsolete active
monolith edit; run pin validation and coverage without regenerating contracts.
For semantic changes, inspect the original PR diff and transfer only the affected
workflow/job, script-owner or Python-module expectations. Do not regenerate the
archive or accept either branch's stale aggregate hash. The one-time `migrate`
command is not a rebase/refresh command.

Real conflicts remain real: two changes to the same command, job policy, module
expectation or historical replacement need joint review. Never use union merges,
blanket ours/theirs, weakened selection, or automatic expected-inventory refresh.
The regression suite demonstrates real non-overlapping temporary Git branches
that update different pins in one workflow, and independently modify different
jobs and Python modules; their merged source validates without a central-index
edit or inventory refresh.

## Dependency grouping evaluation

The existing Dependabot configuration already limits GitHub Actions proposals
and schedules weekly updates to `development`. Grouping related minor/patch
action updates could reduce concurrent PR volume, but also combines more upstream
executable changes into one review and complicates isolating regressions. Keep
major migrations separate and retain manual pin/provenance review in either
case. This change leaves grouping unchanged: ownership-local structural contracts
solve the artificial hash conflict without depending on grouping or changing the
supply-chain review policy.
