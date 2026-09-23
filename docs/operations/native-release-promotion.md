# Review and promote a native runtime release

## Outcome and supported version

Give the parent release maintainer an auditable path from reviewed source to a
publisher-authenticated native bundle, a genuine compatible-version VM test and
an explicitly approved publication. This is a development runbook for
[#308](https://github.com/KirilsTurkins/latent-service-fabric/issues/308), not a
download announcement or production/hostile-multitenancy certification.

The current **version names** are `0.1.0-alpha.4-rc.2` for the foundation and
`0.1.0-alpha.4` for the final bundle. Their source commits, immutable tags, archive
digests and successful release-identity runs still require parent approval and
observation. Neither a version name nor a green candidate authorizes release.
The historical `0.1.0-alpha.3` tag remains unchanged and source-only.

The current rc.2 foundation is now qualified in
[release run 35811188306](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35811188306), at source
`a53b7b219a46f6ca91ae7bc7830669f8aa4bbe2e`. Its
[authenticated receipt](../evidence/native-foundation-35811188306.json) supplies the actual
archive identity committed for `0.1.0-alpha.4`. Final compatible-pair VM
acceptance and protected publication remain pending; the steps below retain
their separate exact-source and artifact checks.

The earlier unpublished `0.1.0-alpha.4-rc.1` foundation and its receipts remain
historical evidence. Its HTTP table format is now obsolete, so it is no longer
a declared upgrade source. Qualify the distinct rc.2 foundation with current
storage formats; do not restore a legacy reader or move the rc.1 tag.

The first native profile is Ubuntu Server 24.04, Linux x86_64, with the
[installer's actual host prerequisites](../../packaging/linux/INSTALL.md#prerequisites-and-independent-bootstrap-trust).
Use `local-experimental-v1` only for controlled local workloads;
`external-capsule-v1` requires enforced admission and the real isolated compiler
probe, not a fallback to the local profile. Rootless evaluation is foreground
local execution, not a user systemd service. There is no Docker, Podman,
Kubernetes, guest compiler or source-checkout prerequisite in an installed guest.

## Keep the three publication authorities separate

| Lane | Authority and prerequisite | What it does not prove |
| --- | --- | --- |
| Native runtime | Parent-selected exact version commit and existing tag; `.github/workflows/native-runtime-release.yml`; protected `native-runtime-publish` environment for publication | A candidate attestation, installed rootless node or green source CI is not a released bundle or a compatible-version test. |
| Maintained security monitoring | The coordinator on the actual default `release` branch schedules scans of both `release` and `development`; see [activation](maintained-security-monitoring.md) | Workflow registration or a manual run is not an observed scheduled scan. |
| Documentation | Reviewed, version-bound `docs/` sources and the single protected development publisher owned by [#355](https://github.com/KirilsTurkins/latent-service-fabric/issues/355) | Default-release promotion must not create a second Pages writer or revive separately edited Wiki prose. |

The parent owns merges, version commits/tags, default-branch promotion, repository
protections and publication. Guide authors and operators do not bypass those
decisions. [#240](https://github.com/KirilsTurkins/latent-service-fabric/issues/240)
consumes honest documentation and release evidence; its closure is **not** a
prerequisite for publishing existing alpha docs or labelled development guides.

## Prerequisites and complete source

Use a clean checkout of the parent-reviewed integrated source, including the
scoped security baseline, isolated native-fixture Cargo manifest/lock registration
and all-lock RustSec checking. Frozen f8d candidate CI predates that additional
coverage. [The reviewed edec integration](../evidence/native-runtime-edec84fa.json)
has its own successful CI/security and both native VM profiles. The parent
squash-merged its identical tree as development `f4231d07`; that does not retag
the edec binary or turn its candidate certificate into release authority.
Do not run these steps from another agent's worktree or a moving branch checkout.

The authoritative implementation is the [release workflow](../../.github/workflows/native-runtime-release.yml),
[release gate](../../tools/native_release_gate.py), [builder](../../tools/build_native_runtime.py),
[VM harness](../../tools/run_native_vm.py), [pinned guest profile](../../tools/native-vm-profile.json)
and [compatibility declaration](../../packaging/linux/compatibility.json).
The [maintainer contract](../development/native-release-gate.md) describes the
gate; the [installation contract](../../packaging/linux/INSTALL.md) supplies the
actual install, readiness, backup, upgrade, removal and purge commands. This
runbook does not create a second installer or a new publisher trust key.

Maintainer examples below use Bash, GNU `timeout`, GitHub CLI and Python 3.12+ on
a trusted administration host. Provision GitHub CLI 2.96.0+ and Sigstore roots
independently of LSF. Repository reads need suitable visibility; settings and
reviewer inspection need administrator visibility. Never print an access token,
put it in a command argument or pass an administrator token to a PR workflow.
The existing workflow uses its own narrowly scoped job permissions.

## 1. Inspect registration without changing it

These are bounded, read-only commands. Check the returned default branch before
using the explicit `release` lookups. Any timeout, denied response or missing
required object stops promotion; do not reinterpret it as a successful check.

```bash
set -eu
REPOSITORY=KirilsTurkins/latent-service-fabric
timeout --kill-after=5s 30s gh api "repos/$REPOSITORY" \
  --jq '{default_branch, administratorVisibility: .permissions.admin}'
timeout --kill-after=5s 30s gh api \
  "repos/$REPOSITORY/contents/.github/workflows/native-runtime-release.yml?ref=release" \
  --jq '{path, sha, size}'
timeout --kill-after=5s 30s gh api \
  "repos/$REPOSITORY/actions/workflows/native-runtime-release.yml" \
  --jq '{id, path, state}'
timeout --kill-after=5s 30s gh api \
  "repos/$REPOSITORY/environments/native-runtime-publish" \
  --jq '{name, requiredReviewers: [.protection_rules[]? | select(.type == "required_reviewers") | {prevent_self_review, reviewerCount: (.reviewers | length)}]}'
```

Expected after parent promotion: the reviewed file is present on the default
branch, the registered workflow has the exact path and is active, and the
publication environment has a nonempty required-reviewer rule. A file on a
feature branch alone is insufficient. A 404 without administrator visibility
can also mean inaccessible state; ask the parent rather than creating a duplicate.

The [2026-09-19 read-only checkpoint](../evidence/operator-release-prerequisites-2026-09-19.json)
observed default `release` at `44891f4158a663de5c08b177431686ec70c0bdf3`, absent
native release registration/default-branch file, absent reviewer environment and
neither new tag. It is a dated observation, not current permission to create them.
OAuth workflow scope is available; it is not the remaining activation gate.

## 2. Parent prepares the genuine foundation

After integration review, the parent prepares a new version commit whose actual
workspace/package version is `0.1.0-alpha.4-rc.2`, promotes the reviewed workflow
normally to the default branch, obtains maintained `.github/workflows/ci.yml`
success at the exact selected source and creates the new immutable tag. A merge
commit is a different source: a green PR head cannot qualify it by association.
Security inventory/advisory results must cover the integrated source, including
both Cargo locks; a native VM pass does not waive renderer/SDK findings.

Independently approve this foundation publisher identity **before** consuming it:

```text
repository: KirilsTurkins/latent-service-fabric
certificate SAN: https://github.com/KirilsTurkins/latent-service-fabric/.github/workflows/native-runtime-release.yml@refs/tags/0.1.0-alpha.4-rc.2
issuer: https://token.actions.githubusercontent.com
source digest and signer digest: the same independently reviewed full foundation commit
runners: GitHub-hosted only
```

The following is a **parent-only future dispatch**, not a command run to validate
this guide. Supply the approved full commit and its own successful CI run ID.
`publish=false` still builds and attests real binaries and boots both VM profiles;
it does not publish a GitHub release or satisfy the cross-version gate.

```bash
: "${FOUNDATION_COMMIT:?Set the approved full foundation source commit}"
: "${FOUNDATION_CI_RUN:?Set the successful maintained CI run for the exact foundation source}"
FOUNDATION_VERSION=0.1.0-alpha.4-rc.2
timeout --kill-after=5s 30s gh workflow run native-runtime-release.yml \
  --repo "$REPOSITORY" --ref "$FOUNDATION_VERSION" \
  -f version="$FOUNDATION_VERSION" -f commit="$FOUNDATION_COMMIT" \
  -f ci_run="$FOUNDATION_CI_RUN" -F publish=false
```

Dispatch is a mutation. If its response is lost or times out, inspect workflow
runs for the exact tag/source before deciding whether another dispatch is safe;
do not automatically repeat it. Select the actual run, not simply the newest run:

```bash
timeout --kill-after=5s 30s gh run list --repo "$REPOSITORY" \
  --workflow native-runtime-release.yml --event workflow_dispatch --limit 10 \
  --json databaseId,headSha,headBranch,event,status,conclusion,url
: "${FOUNDATION_RUN:?Select and verify the exact foundation workflow run ID}"
timeout --kill-after=5s 30s gh run view "$FOUNDATION_RUN" --repo "$REPOSITORY" \
  --json databaseId,headSha,headBranch,event,status,conclusion,jobs,url
```

Require completed success, the approved full source, the release workflow and
successful build plus both VM jobs. Inspect the retained decision and receipts:
the foundation may honestly have `acceptanceComplete:false` and the sole gap
`declared-compatible-native-version-pair-not-yet-selected`. It must not be
described as a completed upgrade test. Artifacts are retained for 90 days; their
availability is a prerequisite for the final run, not an indefinite archive.

## 3. Authenticate the foundation and pin its actual archive

Download the exact named artifact into a new private review directory. This
downloads data; it does not execute the bootstrap, extract binaries or install
the runtime. Keep independently provisioned roots/policy outside this directory.

```bash
umask 077
REVIEW_DIRECTORY=$(mktemp -d "${TMPDIR:-/tmp}/lsf-native-review.XXXXXX")
timeout --kill-after=5s 120s gh run download "$FOUNDATION_RUN" \
  --repo "$REPOSITORY" --name "native-runtime-release-$FOUNDATION_COMMIT" \
  --dir "$REVIEW_DIRECTORY/release"
```

Follow the [independent bootstrap verification sequence](../../packaging/linux/INSTALL.md#prerequisites-and-independent-bootstrap-trust)
in that directory: approved tag/source policy, independently installed `gh`,
separately provisioned roots and `SHA256SUMS.sigstore.json`; authenticate
`SHA256SUMS`, check all listed hashes and explicitly require the bootstrap hash
**before the first downloaded Python invocation**. The installer then repeats
verification. A GitHub Actions ZIP digest is not the native archive digest.

Offline operators receive the roots through their own trusted provisioning
channel and the exact attestation material as data; no login, network refresh,
artifact-supplied root or new untrusted Ed25519 bootstrap key is a substitute.
The candidate workflow's branch certificate is a different authority and cannot
be accepted by adding `--allow-candidate` to this release procedure. Capsule
admission and the host AOT key remain separate from runtime publisher trust.

Only after that verification, read the authenticated manifest as data to produce
the predecessor entry. This does not import or execute downloaded code:

```bash
python3 -I - "$REVIEW_DIRECTORY/release/release.json" "$FOUNDATION_COMMIT" <<'PY'
import json
from pathlib import Path
import sys

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if manifest["version"] != "0.1.0-alpha.4-rc.2" or manifest["sourceCommit"] != sys.argv[2]:
    raise SystemExit("Authenticated foundation does not match the approved identity")
print(json.dumps({"version": manifest["version"], "sourceCommit": manifest["sourceCommit"],
                  "archiveSha256": manifest["archive"]["sha256"]}, indent=2))
PY
```

The parent commits that **observed** object into `upgradeFrom` in
`packaging/linux/compatibility.json` as part of the final `0.1.0-alpha.4` source.
Preserve the actual installer/config/storage/host-ABI compatibility contract; a
version string alone is not compatibility. Do not guess a digest, rename the
foundation binaries, move a tag or use same-version reinstall as an upgrade.

## 4. Qualify the final source against that foundation

The parent reviews the final version/compatibility commit, obtains its own exact
CI/security results and creates its distinct immutable final tag. Independently
approve the release certificate ending in `@refs/tags/0.1.0-alpha.4`, with both
source and signer pinned to that final source, not to the foundation or a PR base.

The **parent-only** nonpublishing rehearsal selects the actual foundation run:

```bash
: "${FINAL_COMMIT:?Set the approved full final source commit}"
: "${FINAL_CI_RUN:?Set the successful maintained CI run for the exact final source}"
FINAL_VERSION=0.1.0-alpha.4
timeout --kill-after=5s 30s gh workflow run native-runtime-release.yml \
  --repo "$REPOSITORY" --ref "$FINAL_VERSION" \
  -f version="$FINAL_VERSION" -f commit="$FINAL_COMMIT" \
  -f ci_run="$FINAL_CI_RUN" -f predecessor_run="$FOUNDATION_RUN" -F publish=false
```

Retain the actual run ID and inspect both
`native-runtime-release-vm-<profile>-<FINAL_COMMIT>` artifacts. Require all of:

- `sourceCommit` **and** `harnessSourceCommit` equal the final full source,
  `purpose:"release"`, the exact final archive SHA, and authenticated release
  workflow/tag/source policy. Diagnostic artifact reuse across revisions fails.
- `passed:true`, `acceptanceComplete:true`, empty `gaps`, distinct real boot IDs,
  and successful `initial`, `retained`, `upgrade` phases for both profiles.
  The local profile additionally has the actual UID-nonzero `rootless` phase.
- The declared predecessor equals the authenticated foundation version, source
  and TAR SHA. The guest installs that old bundle, publishes/invokes, upgrades
  explicitly, retains the publication/configuration/credentials/AOT identity and
  rejects an unsupported binary downgrade without mutating retained state.
- The same run proves native non-root systemd, actual reboot/retained invocation,
  stopped consistent backup/full-set restore, removal/reinstall recovery and
  separately confirmed purge. Test fixtures or a container are not clean-VM proof.

The release gate checks these relationships, not just job colour. If the compiler
changes compatibly, the installer requires explicit approval of that exact
compiler SHA; it does not regenerate the AOT key or silently discard trust.
Binary downgrade is not an inverse storage migration.

## 5. Parent reviews publication, then observes its result

Only the parent may select `publish=true` after all gates. The existing workflow
builds/attests again and reruns both VM profiles for those exact new artifact
bytes, rechecks live CI and waits for the required-reviewer environment. A
nonpublishing run's TAR hash must not be asserted for a later rebuild.
The gate authenticates the acceptance documents and creates one prerelease with
`--verify-tag`; it does not create tags or overwrite an existing release.

An interrupted/failed publish is uncertain, not authorization to delete/recreate
or retry. Inspect the exact remote release, asset states/digests and retained
`native-publication-result.json`. Escalate partial upload or mismatched bytes to
the parent. The separately attested fixture helper is test infrastructure, not a
runtime release asset. Keep credentials, AOT keys, VM disks and backups private.

## Failure, cleanup and validation boundary

| Observation | Safe next action |
| --- | --- |
| Missing default workflow, reviewer rule, exact CI or tag | Stop at the parent integration/promotion gate; do not create another workflow, signing key or unprotected environment. |
| Wrong issuer/repository/workflow/tag/source, absent attestation or hash mismatch | Execute no downloaded code. Quarantine the staged files and obtain the independently approved identity/material. |
| New advisory, missing isolated Cargo lock or unregistered SDK graph | Ask the security/source owner to remediate and rerun exact-source checks; a VM pass is not a waiver. |
| Green foundation/candidate with incomplete acceptance | Retain its scoped evidence; require the genuine final compatible pair. |
| Failed readiness, interrupted upgrade or uncertain lifecycle response | Stop mutation retries; use the [installer's journal/backup/removal contract](../../packaging/linux/INSTALL.md#reinstall-upgrade-and-recovery) and bounded read-only status. Never delete state or regenerate a key as a repair shortcut. |
| Expired/missing foundation artifact or changed source | Parent selects and reviews a new qualification plan; no silent predecessor substitution or moved historical tag. |

This guide itself installs no service and changes no repository setting. Retain
only compact public receipt/digest/run-ID records from the private review
directory. After handoff, remove only files in that newly created, verified review
directory; do not remove independently provisioned trust, another worktree,
installed state, a VM image owned by another run or user containers/volumes.

The [frozen candidate evidence](../evidence/native-runtime-f8d0c51a.json) binds
source and harness `f8d0c51a9a76bf123fa8b397fb3a0e15099cd3f5` to real offline
authentication, both native VM profiles, reboot/retention/recovery/removal and
rootless execution. It explicitly leaves genuine cross-version upgrade,
unsupported binary downgrade, release-identity qualification and publication
unperformed. Its old CI does not satisfy the later all-lock security requirement
or qualify a parent's integration commit.

The [separate merged-candidate evidence](../evidence/native-runtime-edec84fa.json)
records actual native run `35455114202` at source/harness `edec84fa`, including
both real changed boot IDs and retained publication identities, with CI
`35454985599` and security `35454985745`. The PR jobs execute checkout `05360c50`;
the parent squash `f4231d07` is not their recorded source. A fresh Windows
data-only check accepts the exact candidate certificate, rejects the old source
digest and matches all three authenticated assets plus both original VM receipt
hashes. It does not execute the downloaded bootstrap or claim a new local VM.
This candidate also has no declared predecessor and incomplete version-pair
acceptance. The parent still owns the genuine rc.1/final commission.

The [guide review handoff](../development/operator-guide-acceptance.md)
separates retained execution, command/source checks and pending rendered human
review; none of these future parent dispatches is recorded as executed.
