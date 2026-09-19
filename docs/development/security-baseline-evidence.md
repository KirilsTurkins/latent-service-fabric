# Security baseline evidence: 2026-09-19

This is compact, redacted milestone evidence for
[#282](https://github.com/KirilsTurkins/latent-service-fabric/issues/282) and
[PR #363](https://github.com/KirilsTurkins/latent-service-fabric/pull/363), not an
acceptance/merge or runtime-security certificate. The parent must refresh checks
for the final exact PR head; the observations below are deliberately dated.
Operation, limits and triage are in the [runbook](security-baseline.md).

## Revisions and repository settings

- Original implementation milestone, before integration rebase: `68d60404417a8262bc62ab44896dffe98a6a331e`.
- Original legacy-ref/dirty-observation correction: `8de6441ca7f6640be717a4c6fae1dbd7d7a6393c`.
- Current integration base: `13d94f021dcce9bed2abf3e5231dd20f246c1312` (`development`, including #343/#335/#336).
- Rebased implementation tested before this evidence update: `f110b5300756e69f12aa43f738aece75d7cc7a1f`.
- Independently scanned maintained `release`: `44891f4158a663de5c08b177431686ec70c0bdf3`.
- Settings refreshed via operator API at `2026-09-19T14:36:48.110758+00:00`.

| Setting | Verified observation |
| --- | --- |
| Vulnerability alerts | Enabled (HTTP 204) |
| Dependabot security updates | Enabled, not paused |
| Secret scanning / push protection | Both enabled |
| Private vulnerability reporting | Enabled |
| Non-provider secret patterns / live validity checks | Both disabled; no credential-validity probes |
| CodeQL default setup | Not configured; custom source/workflow checks are used instead |
| Default workflow token / PR review approval | Read / false |
| Default branch | `release` |
| Coordinator on default branch | Absent; periodic activation pending normal promotion |
| Required development contexts | `CI result` only; security aggregate protection pending deployment |
| Repository auto-merge capability | Already enabled at repository level; no baseline auto-approval/merge workflow exists or was used |

Settings can drift. `python tools/security_settings.py` refreshes this inventory;
admin visibility is required to distinguish disabled state from permission loss.
No account token or raw secret findings are retained in this ledger.

## Representative hosted workflow

### Initial failure detected

[Security run 35447295927](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35447295927)
is a `pull_request` run for exact PR head
`68d60404417a8262bc62ab44896dffe98a6a331e`. GitHub scanned its synthetic merge
revision `addd7e14a0bc3ec1ed433504cd360966ca1ef3ab`, not an unnamed branch tip.

| Job | Result |
| --- | --- |
| Scope | Pass, all checks selected for control changes |
| RustSec | Pass |
| Changed-present redacted secrets | Pass |
| Source/workflow rules | Pass with one exact compatibility exception, pending owner approval |
| Fail-closed canaries | Pass with actual Linux scanner releases and fresh RustSec data |
| SDK advisories | **Fail**, the three real matches listed below |
| Security baseline result | **Fail**, correctly propagates the SDK result |

This is positive evidence that detection and the aggregate fail closed, **not a
fully green baseline**. No failing job was rerun until green by suppression.
The ordinary CI and final-head checks must be consulted independently on the PR.
No scheduled/manual both-ref hosted run is claimed while the coordinator is
absent from default `release`.

### Actual advisory remediation passes

[Security run 35448635149](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35448635149)
passes every selected job, including SDK advisories and `Security baseline result`,
at exact PR head `eefa978f0ebc3c2b0670173986c41ae74c254c44`; its synthetic merge
revision is `49cd9f39524674b2d2770b1777ff149a863f927c`. Hosted Linux runs all 34
security tests without skips and all eight real-scanner canary categories pass.
This closes the actual SDK failure from run 35447764981 without an advisory
exception. The corresponding ordinary CI run 35448635129 was still running when
integration advanced to #336; full Linux renderer qualification is not inferred
from the security pass.

The four implementation milestones rebased cleanly onto `13d94f02`. Fresh
dependency and static scans pass at `f110b530` (zero dependency findings, one
unchanged exact static compatibility exception), with both source and controls
recorded clean. These are local integration checks, not hosted checks of the
subsequent documentation commit. The parent must inspect the final pushed head;
the delivery does not wait idly for CI or claim a pending result is green.

## Local bounded checks

- At rebased `f110b530`, 34 security unit/workflow/settings tests run: 33 pass and
  one Windows symlink construction test is skipped. The hosted Linux result above
  has no skip; final-head Linux status remains a separate check.
- Existing CI-profile/action-policy suite: 30 tests run, 29 pass and one host skip.
- Action policy: 82 immutable/local references across seven workflows validate.
- Documentation validation after #336: 293 documents, five SVGs, 1,969 local
  links and 87 anchors, with no errors.
- Parsed `ci.yml` equals base `13d94f02` after removing only the eight new
  `persist-credentials: false` checkout settings: profiles, caches, permissions,
  commands and aggregate logic are otherwise identical.
- Eight real canary categories passed locally and in the representative hosted
  job. Known-vulnerable dependencies and synthetic secrets remained fixture data;
  no runtime dependency graph was changed.
- Development lock RustSec scan: 432 packages, 1,251 database advisories, no match;
  lock SHA-256 `59b2b6ad36257d13ffd951e8aa0405275c8273b41cec96faf6801447a74f8327`.
- Fresh RustSec DB identity for both local lock scans:
  `d5c17953a895cf19e8d3ce66eaa42b6fcfe1fb16`, commit timestamp `1789807347`.
  Development verification was at 13:58:27 UTC, release at 14:02:43 UTC.
- A clean detached release source scan inventories all its shipped SDK manifests
  and passes OSV. It explicitly records the absent renderer/control source
  directories while still querying caller scanner dependencies. This is not
  evidence that the release's Rust graph or workflows pass.

## Findings, remediation and acceptance gaps

### Development renderer dependency

The initial local and hosted OSV scans match `npm:decompress@4.2.1` in
`examples/renderer-profile/package-lock.json`, transitively introduced by
`@bytecodealliance/weval@0.4.1`:

- [GHSA-h39j-r5qq-r9mm](https://github.com/advisories/GHSA-h39j-r5qq-r9mm).
- [GHSA-jwp9-9v96-94mx](https://github.com/advisories/GHSA-jwp9-9v96-94mx).
- [GHSA-mp2f-45pm-3cg9](https://github.com/advisories/GHSA-mp2f-45pm-3cg9).

Official advisory lookup on 2026-09-19 gives no patched version of the unscoped
`decompress` package. A differently scoped package is not an automatic safe
substitution. On the parent's explicit request to resolve the failing SDK job,
this delivery adds the narrow upstream remediation below rather than a finding
exception. The initial match is not a claim of an LSF exploit.

The official [weval 0.5.0 release](https://github.com/bytecodealliance/weval/releases/tag/v0.5.0),
published 2026-09-10, resolves to full upstream commit
`04191f69e9cdf624a272be01887dfbe5cf306bfa`. Its reviewed npm wrapper replaces the
old `decompress` family with `tar` and `fflate`, keeping the default `getWeval`
export. The renderer manifest now pins that exact transitive override; the
lockfile resolves `tar` 7.5.22 and `fflate` 0.8.3. The npm archive integrity is
retained in the lock. ComponentizeJS remains 0.22.0 and the existing renderer
profile still disables AOT, so the native weval compiler is not selected.

Only weval changes version among retained package entries. Seven entries are
added and 77 unused extractor-related entries removed, reducing the resolved
renderer graph from 344 to 274 entries. The resulting lock SHA-256 is
`86e664dcd26735c9e7ca655442c1f3c957eab2a0a10da005e63432ef5105cd0a`.
It was regenerated from the existing lock in an isolated ignored directory with
package scripts disabled, then applied as a focused patch. A clean
`npm ci --ignore-scripts` succeeds, a fresh full `npm audit` reports zero
vulnerabilities, and the fresh repository OSV scan reports zero matches.
No unrelated retained package versions, runtime/SDK/provider code or parent Node
worktree were changed. Final exact-head hosted checks still require review.
The added import smoke checks the real pinned weval/ComponentizeJS modules; it
does not claim a full Windows build. An attempted Windows componentization probe
failed in existing Wizer default-cache configuration. Full compatibility must
pass the existing Linux renderer CI, with the profile and engine unchanged.

Additional security tests prevent reintroduction of the unpatched extractor and
verify inventory of the parent's pinned Node runtime `@bufbuild/protobuf` 2.15.0
and development `@types/node` 24.13.6 with `24.19.x` engines. Both dependency kinds
are queried; the inventory does not drop development packages or run Node code.
Central toolchain changes select all lightweight security analyses. The parent
#365 toolchain/setup-node changes are preserved through normal integration, not
duplicated in this worktree.

### Older maintained release

The fresh RustSec scan of unchanged release lock
`a3bbfde83d057cc90f0968aa397de8d86ecc64b10f585be62de53df381209a1e`
finds `RUSTSEC-2026-0268` and `RUSTSEC-2026-0269` on `wasmtime@47.0.3`, plus
`RUSTSEC-2026-0285` on `rustls@0.23.44`. Existing #279/Rustls fixes on development
still need normal promotion; a development pass does not erase release findings.
There are no release-only suppressions.

The legacy release static scan also fails with `workflow-action-pin-policy`:
its older workflow definitions do not meet the already-reviewed #281 policy.
Normal promotion must carry those controls too; the scanner does not relax the
pin policy for an older maintained branch.

### Full-snapshot secret triage

The local full development snapshot scanned 4,073 text files and counted 222
unscanned binary/archive files. It reports **16 unsuppressed generic-rule
occurrences across three paths**. A changed-file PR pass does not clear them.

- A benchmark README occurrence is consistent with an API-journal digest.
- A local-secret test occurrence is consistent with an environment-variable name.
- Fourteen occurrences in a historical benchmark aggregate need complete private
  review. Private in-memory follow-up maps every matched value to
  `runs[*].direct_execution.prepared_handle`; none of these fourteen is a decoded
  finding. A digest-shaped preparation identifier is not, by shape alone, proof
  that publication is harmless or that a finding can be waived.

Only redacted positions/fingerprints and counts were retained locally; no raw
matches, credential tests, blanket path/rule ignores or secret exceptions were
published. These matches do not establish that a credential was found or leaked.

After fixing Windows extended-length input handling without relaxing link/path
validation, the unchanged legacy-release snapshot also completes: 3,259 text
files, 222 counted binaries/archives and 15 unsuppressed generic-rule occurrences.
Its missing newer local-secret test explains the lower count; neither snapshot
is described as secret-clean. The control-worktree observations and final hosted
revision must be distinguished when reviewing these local receipts.

### Central acceptance work

| #282 acceptance area | Implemented or verified | Remaining acceptance evidence |
| --- | --- | --- |
| Coherent pinned dependency baseline | Existing RustSec worker reused; both-ref schedule selection, fresh identities and stale/unavailable rejection tested | Promote coordinator to default `release`; capture actual periodic both-ref run |
| SDK inventory and repository alerts | Resolved runtime/development dependencies inventoried, real renderer advisory removed, alerts and security proposals enabled | Promote existing release dependency fixes; review future manifest changes |
| Secret/static coverage and protection | Reviewed scoped rules, redacted evidence, enabled secret scanning/push protection, unavailable-service equivalent documented | Complete private snapshot triage and review the exact static exception |
| Relevant PR scope and isolation | Docs/SVG profile, read-only permissions, no security caches, complete diff and fail-closed aggregate tested | Parent checks final hosted head; no real fork run claimed |
| Ownership and exceptions | Named owner, exact finding/package/path/fingerprint, review reference, maximum 30-day expiry and expired-entry failure | Owner approval of the one proposed compatibility waiver |
| Harmless pass/fail evidence | 34 hosted tests and eight native canary categories; unchanged-lock scheduling and fork permissions validated as fixtures | Actual both-ref hosted schedule/manual evidence and any required server push-rejection exercise |
| Runbook and phase gates | Current settings, historical failure/pass runs, #279/#238 links and #240 requirement recorded | Deploy required security aggregate alongside `CI result`, then parent acceptance review |

The parent retains authority to review the exact compatibility exception
(expires 2026-10-03), triage/remediate findings, audit final-head CI, promote the
coordinator/config normally to default `release`, and require
`Security baseline result` without removing `CI result`. Then capture actual
manual and periodic both-ref runs with unchanged locks, plus any required real
fork/server-push protection evidence. The
[#240 completion gate](https://github.com/KirilsTurkins/latent-service-fabric/issues/240)
and [#238 integrated tests](https://github.com/KirilsTurkins/latent-service-fabric/issues/238)
remain separate. No PR was merged and no issue was closed by this delivery.
