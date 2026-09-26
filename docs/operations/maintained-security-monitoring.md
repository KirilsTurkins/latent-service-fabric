# Activate and verify maintained-branch security monitoring

## Outcome and supported boundary

Help the repository operator distinguish **configured**, **registered** and
**actually executed** security coverage, activate the approved default-branch
coordinator, and retain a redacted receipt for both maintained branches even when
their lockfiles have not changed. This is the monitoring/promotion slice of
[#282](https://github.com/KirilsTurkins/latent-service-fabric/issues/282) and
[#359](https://github.com/KirilsTurkins/latent-service-fabric/issues/359), not a
new scanner, runtime sandbox certification or automatic dependency updater.

These instructions target the maintained baseline, including the resolved SDK
graphs and every tracked Cargo lock. Use the reviewed current checkout. The
[coordinator](../../.github/workflows/security-baseline.yml),
[settings inventory](../../tools/security_settings.py) and
[scanner](../../tools/security_scan.py) are maintained with their rules and tests.
Monitoring is already active on this repository; the steps below verify it and
explain how a maintainer can run a fresh check.

The [baseline reference](../development/security-baseline.md) is authoritative
for tool pins, inventories, rules, exceptions and boundaries at the selected
source. The [native release procedure](native-release-promotion.md) consumes
security results but has a different workflow, tag identity and reviewer gate.
Neither security success nor GitHub service settings alone authorize an external
capsule, relax credentials/AOT key protection or widen a loopback listener.

## Prerequisites and ownership

- A trusted administration host with Bash, GNU `timeout`, Python 3.12+ and an
  independently installed authenticated GitHub CLI; no node, provider or container
  is needed for these repository reads.
- Administrator visibility to verify security settings and branch protection.
  Keep that credential in the host's protected credential store, not a command
  argument, trace, public artifact or CI job. Never supply it to PR code.
- Parent approval for default-branch/protection changes and workflow dispatches.
  The existing settings inventory is read-only without `--enable`; this guide
  does not ask the reader to enable anything implicitly.
- A parent-reviewed baseline covering the actual integrated manifests: workspace
  and isolated native-fixture Cargo locks, npm/website, Go module/tool/stdlib,
  Maven, NuGet and reviewed C/PyPI inputs where shipped. Missing/unregistered
  graphs are failures, not zero-dependency findings.

The source/package maintainer owns remediation; the security maintainer owns
finding classification and reviewed exceptions; the parent owns activation and
required checks. Suspected real credential exposure follows the private
[security reporting process](../../SECURITY.md), including revocation/rotation.
Do not test a live credential or post its value as evidence.

## 1. Inventory services with a read-only command

From the reviewed integrated checkout:

```bash
set -eu
REPOSITORY=KirilsTurkins/latent-service-fabric
timeout --kill-after=5s 360s python3 tools/security_settings.py
```

Every API request inside the inventory is bounded to 30 seconds. Expected fields:

| Field or exit | Interpretation |
| --- | --- |
| Exit 0 and `settings_enabled:true` | The listed alert/update/disclosure/secret-scanning services are enabled at observation time; this is not schedule or protection acceptance. |
| Exit 1 and `settings_enabled:false` | At least one required service is disabled/paused; parent remediation is needed. |
| Exit 2 or timeout | Required visibility/API data is unavailable; do not classify unknown state as disabled, absent or safe. |
| `default_branch` | The actual default ref. This repository uses `release`; stop and review this runbook if it changes. |
| `scheduled_definition_on_default` | Whether the coordinator file exists on that default ref. Registration alone does not satisfy this. |
| `development_required_checks` | Actual contexts required by the branch; preserve `CI result` and check the parent's separately approved `Security baseline result` protection. |
| `workflow_permissions` | Default token permissions and whether workflows can approve PRs; retain the least-permission baseline. |
| `code_scanning_default_setup` | GitHub's default CodeQL setup only. An unconfigured default is not proof that custom scanning is absent, or that the custom baseline is CodeQL. |

Read the complete service fields, not just the process exit code. The settings
inventory does not change repository policy unless explicitly passed `--enable`;
that mutating mode is outside this read-only procedure. A displayed auto-merge
capability is not approval to automatically merge dependency/workflow changes.

## 2. Verify the default branch and registered coordinator separately

```bash
timeout --kill-after=5s 30s gh api "repos/$REPOSITORY" \
  --jq '{default_branch, administratorVisibility: .permissions.admin}'
timeout --kill-after=5s 30s gh api \
  "repos/$REPOSITORY/contents/.github/workflows/security-baseline.yml?ref=release" \
  --jq '{path, sha, size}'
timeout --kill-after=5s 30s gh api \
  "repos/$REPOSITORY/actions/workflows/security-baseline.yml" \
  --jq '{id, path, state}'
timeout --kill-after=5s 30s gh api \
  "repos/$REPOSITORY/branches/development/protection/required_status_checks" \
  --jq '{strict, contexts, checks}'
```

Expect the coordinator file on `release`, an active workflow registration, and
both `CI result` and `Security baseline result` among development's required
checks. The [activation record](../development/security-baseline-evidence.md)
retains the actual manual and scheduled runs. Refresh the commands above before
relying on repository settings, which can change independently of the source.

The parent promotes the reviewed implementation and patched dependency graphs
through the normal development-to-release review/CI path. Do not transplant only
the YAML: tools, inventories, pins, tests and the source actually being scanned
must be present and reviewed together. Do not force-push the default branch or
disable a finding to make the older release appear clean. The existing native
candidate's VM result does not clear a different dependency graph.

After promotion, repeat the read-only inventory. Add the approved security
aggregate to required checks only with the parent's rollout review and actual
completed checks; do not remove the existing aggregate or make docs-only changes
run full Rust/SDK builds. Source configuration and service settings remain
separate from [the execution threat boundary](../runtime/execution-security-profiles.md).

## 3. Parent runs the coordinator manually once

After the default-branch definition is present, the parent can perform this
**explicit, nonpublishing but mutating dispatch**:

```bash
timeout --kill-after=5s 30s gh workflow run security-baseline.yml \
  --repo "$REPOSITORY" --ref release
```

The coordinator selects **both** maintained refs for manual and scheduled runs.
Its RustSec workflow is a reusable worker, not a second scheduler. Do not launch
independent workers and present the resulting partial set as one coordinated run.
If dispatch response is lost, inspect matching runs before another mutation.

```bash
timeout --kill-after=5s 30s gh run list --repo "$REPOSITORY" \
  --workflow security-baseline.yml --event workflow_dispatch --limit 5 \
  --json databaseId,headSha,headBranch,event,status,conclusion,url
: "${SECURITY_RUN:?Select the actual reviewed coordinator run ID}"
timeout --kill-after=5s 30s gh run view "$SECURITY_RUN" --repo "$REPOSITORY" \
  --json databaseId,headSha,headBranch,event,status,conclusion,jobs,url
```

Expected: completed success with both refs covered by RustSec, SDK advisories,
redacted secrets and selected source/workflow rules; real fail-closed canaries;
and `Security baseline result`. Record the scanner-control commit and **each
scanned source commit** from the redacted receipts, not just the run's default
branch `headSha`. Old release findings may intentionally fail this first audit;
remediate their exact source, do not silently omit the release matrix entry.

PR changes retain path scoping: Markdown/SVG-only changes select lightweight
secret checks and the aggregate, with genuinely unselected heavier jobs skipped.
A required selected job skipped/failed/unknown is not success. No privileged
`pull_request_target`, administrator token or untrusted PR cache is needed.

## 4. Observe a real schedule with unchanged lockfiles

The reviewed coordinator's schedule is Monday at **04:23 UTC**. A cron definition,
an active registration and a successful manual run still do not prove it fired.
Observe a run whose GitHub event is actually `schedule`:

```bash
timeout --kill-after=5s 30s gh api \
  "repos/$REPOSITORY/actions/workflows/security-baseline.yml/runs?event=schedule&per_page=5" \
  --jq '{total_count, runs: [.workflow_runs[] | {id, event, head_sha, status, conclusion, html_url}]}'
```

A zero count is a pending acceptance condition, not an invitation to relabel a
manual run. Delayed or disabled schedules require parent investigation; this
procedure neither polls indefinitely nor mutates cron to manufacture a receipt.
Select the actual schedule run and inspect its jobs as in step 3. Require both
maintained sources, success and the aggregate. Compare the recorded lock hashes
with an earlier exact-source observation to demonstrate unchanged-lock coverage;
if the locks changed, retain that honest result and obtain the missing unchanged
case later. The control source and scanned sources need not be identical.

Retain a compact redacted activation receipt containing:

- UTC settings observation, actual default ref, relevant service/protection
  fields, coordinator path/identity, and manual plus actual scheduled run URLs.
- Each control/source commit and per-lock SHA, including the isolated native
  fixture; resolved SDK manifest/graph identities and known ingestion boundaries.
- Exact pinned tool identity, RustSec DB commit/time/freshness and results; OSV
  endpoint/UTC HTTP Date/request-response digests rather than an invented DB SHA.
- Pass/fail canary outcomes, selected/skipped jobs, aggregate result, finding
  owner and any reviewed exact exception/expiry. Never raw scanner reports,
  matching secret snippets, credentials or uploaded project snapshots.

There is deliberately no security artifact-upload job. Obtain the wrapper's
bounded redacted output/job summaries and API metadata, not a nonexistent
`security-*` artifact or a public copy of native Gitleaks output. Unit permission
fixtures and enabled push-protection settings are not a real fork execution or
an observed server-side rejected synthetic push; retain those acceptance gaps
until the security owner supplies the actual controlled evidence.

## Findings, stale data and recovery

| Observation | Owner and bounded response |
| --- | --- |
| Advisory in an exact package/lock | Package maintainer investigates upstream/reachability and submits a reviewed update. Security review owns any exact finding/package/path exception with rationale, owner and expiry; no blanket suppression. |
| Missing native lock, SDK registration, empty graph or manifest drift | Source/inventory owner supplies the reviewed resolved graph and fixtures. Do not execute arbitrary package setup/build code inside advisory scanning. |
| RustSec DB missing, remote/local commit mismatch, older than 14 days or beyond five-minute future tolerance | Stop and investigate data availability/clock. Do not reuse a stale cache or relax the freshness bound to obtain green. |
| OSV unavailable, HTTP Date older than one hour, malformed/incomplete pagination | Fail unknown coverage visibly; retry only a bounded read after investigation. An empty successful query means no reported match then, not complete upstream ingestion. |
| Synthetic secret/static canary fails to fail, or an exception expires | Security owner repairs the scanner contract or reviews remediation. Never waive the canary or extend expiry automatically. |
| Suspected credential match | Keep raw material private, use the private reporting/rotation process, retain only bounded IDs/paths/fingerprints publicly. Never exercise the credential. |
| GitHub secret services unavailable | Parent/security owner deploy and prove an equivalent private full-history and rejecting promotion/server-side protection gate. Local hooks and PR snapshot scanning alone are not equivalent. |
| Aggregate missing or source changes after review | Refresh exact-source checks and parent protection review; do not replay an old success against a new head. |

The baseline scans tracked text snapshots, not arbitrary archive contents or Git
history. Native source-commit queries do not certify all upstream advisory
ingestion, OS libraries or compiler authenticity. Narrow lexical static rules
are not semantic authorization analysis. Link [advisory triage](../development/wasmtime-security-update.md),
the [security policy](../../SECURITY.md) and
[#238 integrated adversarial evidence](https://github.com/KirilsTurkins/latent-service-fabric/issues/238)
when explaining the supported boundary; never advertise a universal safety pass.

## Cleanup and actual validation level

Read-only inspection starts no node, changes no setting and installs no scanner.
Keep only the small redacted activation receipt in the review handoff. Remove
temporary review files only from the operator-created private directory after
checking its identity; do not delete another worktree, shared scanner state,
retained native backups, protected trust or any user's workloads.

The [activation record](../development/security-baseline-evidence.md) contains
the executed manual/scheduled coverage and the earlier read-only checkpoint.
The [guide review](../development/operator-guide-acceptance.md) is accepted.
Those records preserve their original scope; use the live inventory and the
selected run's results for a new monitoring decision.
