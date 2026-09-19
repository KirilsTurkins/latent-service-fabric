# Security baseline evidence: 2026-09-19

This is compact, redacted milestone evidence for
[#282](https://github.com/KirilsTurkins/latent-service-fabric/issues/282) and
[PR #363](https://github.com/KirilsTurkins/latent-service-fabric/pull/363), not an
acceptance/merge or runtime-security certificate. The parent must refresh checks
for the final exact PR head; the observations below are deliberately dated.
Operation, limits and triage are in the [runbook](security-baseline.md).

## Revisions and repository settings

- Implementation milestone: `68d60404417a8262bc62ab44896dffe98a6a331e`.
- Legacy-ref/dirty-observation correction: `8de6441ca7f6640be717a4c6fae1dbd7d7a6393c`.
- Integration base: `9c271713276b124aed39921cc70b6c2745c2ca47` (`development`, including #343/#335).
- Independently scanned maintained `release`: `44891f4158a663de5c08b177431686ec70c0bdf3`.
- Settings observed via operator API at `2026-09-19T14:00:58.032729+00:00`.

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

## Local bounded checks

- At `8de6441c`, 31 security unit/workflow/settings tests pass; one Windows symlink
  construction test is skipped. Hosted Linux canaries passed on the earlier
  implementation head; final-head Linux status remains a separate check.
- Existing CI-profile/action-policy suite: 30 tests pass, one host skip.
- Action policy: 82 immutable/local references across seven workflows validate.
- Parsed `ci.yml` equals base `9c271713` after removing only the eight new
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

## Unsuppressed findings and acceptance gaps

### Development renderer dependency

Both local and hosted OSV scans match `npm:decompress@4.2.1` in
`examples/renderer-profile/package-lock.json`, transitively introduced by
`@bytecodealliance/weval@0.4.1`:

- [GHSA-h39j-r5qq-r9mm](https://github.com/advisories/GHSA-h39j-r5qq-r9mm).
- [GHSA-jwp9-9v96-94mx](https://github.com/advisories/GHSA-jwp9-9v96-94mx).
- [GHSA-mp2f-45pm-3cg9](https://github.com/advisories/GHSA-mp2f-45pm-3cg9).

Official advisory lookup on 2026-09-19 gives no patched version of the unscoped
`decompress` package. A differently scoped package is not an automatic safe
substitution. The renderer/build owner must assess reachable archive handling
and review remediation; this scanner-only ticket does not alter that package
graph or assert an LSF exploit. No advisory exception was introduced.

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
  review, including decoded contexts; path/hash-looking metadata alone is not
  sufficient to dismiss them.

Only redacted positions/fingerprints and counts were retained locally; no raw
matches, credential tests, blanket path/rule ignores or secret exceptions were
published. These matches do not establish that a credential was found or leaked.

### Central acceptance work

The parent retains authority to review the exact compatibility exception
(expires 2026-10-03), triage/remediate findings, audit final-head CI, promote the
coordinator/config normally to default `release`, and require
`Security baseline result` without removing `CI result`. Then capture actual
manual and periodic both-ref runs with unchanged locks, plus any required real
fork/server-push protection evidence. The
[#240 completion gate](https://github.com/KirilsTurkins/latent-service-fabric/issues/240)
and [#238 integrated tests](https://github.com/KirilsTurkins/latent-service-fabric/issues/238)
remain separate. No PR was merged and no issue was closed by this delivery.
