# Security baseline

This is the operator runbook for [#282](https://github.com/KirilsTurkins/latent-service-fabric/issues/282).
The [coordinator](../../.github/workflows/security-baseline.yml) reuses the existing
[RustSec worker](../../.github/workflows/security-rustsec.yml), rather than adding a
second advisory schedule. It adds SDK inventory, redacted secret checks, reviewed
source/workflow rules, expiring exceptions and bounded canaries. Deployment and
finding triage remain explicit gates; implementation is not a claim that #282 is
complete. See the [dated evidence and gaps](security-baseline-evidence.md).

## Events and scope

| Event or changed surface | Selected checks |
| --- | --- |
| Any PR into, or push to, `development` or `release` | Complete Git change selection, exception expiry, changed-present text secret scan, aggregate |
| Only Markdown/SVG, including this runbook | Secret check only; no Rust, Python SDK or other SDK build/install |
| Cargo manifests/lock, toolchain, Cargo config, platform WIT, Wasmtime host/surface or component bindings | RustSec |
| Any supported or newly discovered dependency manifest/lock | SDK inventory and OSV; Cargo changes also select RustSec |
| Source files, workflows, local actions or Dependabot config | Applicable source/workflow static rules; workflow changes also select canaries |
| Scanner controls, policies, fixtures/tests or central `tools/toolchain.toml` | All checks |
| Weekly Monday 04:23 UTC, or manual dispatch | All checks against **both `development` and `release`**, regardless of lockfile changes |

[Scope selection](../../tools/security_scope.py) uses Git object identities and the
complete diff, not a truncated GitHub changed-files page. Empty/unknown change
sets do not select a cheap success. The separate `Security baseline result`
requires successful scope and secrets, success for every selected job and an
actual skip for every unselected job. Failures, cancellations and unexpected
skips cannot pass it. Existing `CI result`, documentation/SVG profiles and cache
ownership are unchanged. The only ordinary `ci.yml` edits disable persisted
credentials on its eight checkout steps; four manual workflows receive the same
fix rather than suppressing existing workflow findings.

GitHub activates schedules from the default branch, currently `release`.
The security coordinator was **not present on `release`** when settings were
observed on 2026-09-19. Merging into `development` alone does not activate weekly
coverage or make default-branch manual dispatch available. Normal centralized
promotion must carry the controls to `release`; this ticket does not bypass it.
After promotion, run a manual both-ref scan and retain the first scheduled
both-ref result with unchanged locks. A green PR is not that evidence.

## Reviewed tools and rules

Official upstream release tags and commits were checked live on 2026-09-19.
[The tool lock](../../.github/security/tools.json) records the complete release
identity plus separate SHA-256 digests for each Linux/Windows x64 archive and
extracted binary. [Installation](../../tools/security_install.py) verifies both
digests before execution, then the exact version. It uses prebuilt binaries, not
`cargo install`, an unpinned installer or PR-controlled package scripts.

| Tool | Reviewed release | Full upstream commit |
| --- | --- | --- |
| cargo-audit | [0.22.2](https://github.com/rustsec/rustsec/releases/tag/cargo-audit%2Fv0.22.2) | `281452c35cf0870969042374110f099a411bc185` |
| Gitleaks | [8.30.1](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1) | `83d9cd684c87d95d656c1458ef04895a7f1cbd8e` |
| zizmor | [1.30.1](https://github.com/zizmorcore/zizmor/releases/tag/v1.30.1) | `99a054ed9283c90abdd2d5b9fb5101d27dde9783` |

External actions keep the [#281 immutable action policy](workflow-action-pins.md):
checkout `11d5960a326750d5838078e36cf38b85af677262` and setup-python
`a26af69be951a213d495a4c3e4e4022e16d87065`. Only static/canary jobs install the
reviewed PyYAML 6.0.3 CPython 3.13 wheel from the
[hash-locked requirements](../../.github/security/requirements.txt), with binary
wheels, `--no-deps` and `--require-hashes`. Docs-only scanning needs no Python
package installation. Tool updates require a new upstream identity/digest review
and canary run, not merely a newer version string.

Gitleaks extends the pinned release's built-in rules with one harmless synthetic
canary rule. zizmor uses its pinned `regular` rules offline, with no discovered
config, ignores or inline suppressions. The existing workflow action-pin
validator also runs. [Nine local source rules](../../.github/security/source-rules.json)
cover conspicuous TLS-verification bypasses in Rust, Python, JavaScript/TypeScript,
Go, Java and C#, Python dynamic execution, C unbounded input and shell download
pipes under `apps`, `crates`, `sdk`, `tools`, `examples` and `tests`.
These are narrow lexical checks, not interprocedural/taint analysis. Aliases,
semantic authorization mistakes and runtime resource ownership require review
and integrated tests; absence of these patterns does not certify source safety.

## Dependency inventory and fresh data

[The inventory](../../.github/security/inventory.json) is checked against discovered
manifests without running package managers, builds, setup scripts or SDK code.

| Surface | Advisory coverage and boundary |
| --- | --- |
| Root `Cargo.toml` / `Cargo.lock` and all declared workspace members, including Rust SDKs | RustSec resolved crate versions; every workspace member must appear in the lock |
| TypeScript SDK and renderer example npm manifests/locks | OSV for every resolved direct/transitive/dev entry; registry.npmjs.org HTTPS sources only |
| `tools/requirements.lock`, source scanner requirements, and caller scanner requirements | OSV exact PyPI versions; unresolved ranges/options fail |
| Go, Java/Gradle and both .NET projects | Reviewed exact manifest hashes establish the current no-external-package state; any change requires inventory review, not an empty advisory success |
| C/C-guest | No package-manager graph; platform C library, compiler, bindgen and generated ABI review remain outside advisory coverage |

Missing locks, empty resolved graphs, manifest/lock drift, Git/private package
sources and new unsupported manifests fail closed. Benchmark `setup.py` modules
are explicitly hashed as non-distribution helpers and are never executed.
The renderer example and source security directory may be entirely absent on an
older maintained ref; that is recorded as `not-shipped-at-source-revision`.
If any file in either directory exists, its expected manifest/lock is mandatory.
The **caller** scanner requirements are always queried, even if the scanned
branch predates the baseline. New SDK dependencies need a resolved-graph parser
and fixtures before their manifest hash is approved. Operating-system packages,
standard libraries, JDK/.NET/Go toolchains and dynamically acquired provider
artifacts are not covered by a zero-package SDK record.

Every RustSec job freshly clones [`RustSec/advisory-db`](https://github.com/RustSec/advisory-db)
`main`, independently resolves remote `main`, and requires identical full commits.
This baseline adds a **14-day maximum commit age** and a five-minute future-clock
tolerance to the original identity-only slice. Even a quiet database exceeding
that bound blocks the scan; an operator must investigate, not silently extend it
or reuse cached data. The runner directly invokes `cargo-audit audit --db ...
--no-fetch --no-yanked --deny warnings --file ... --json` on a bounded staged lock.
It records the independently verified Git commit, timestamp and lock SHA-256,
requires a nonempty advisory database and rechecks unchanged DB HEAD/worktree.
With `--no-fetch`, cargo-audit can emit null DB commit metadata; the receipt does
not misrepresent that as a tool-reported commit. Yanked-crate network checks are
not covered; advisory and warning results are.

Non-Rust graphs query the official [OSV batch endpoint](https://google.github.io/osv.dev/post-v1-querybatch/)
with package ecosystem/name/version only, not repository files or credentials.
Responses require a current HTTP Date (within one hour), exactly one result per
query and no incomplete pagination, errors or unknown result fields. Transport,
schema and freshness failures are not converted into an empty success. An empty
result for one explicit package means only that the service reported no match at
that observation time. OSV exposes no immutable database commit here: receipts
record endpoint, UTC observation, HTTP Date and request/response SHA-256 instead.
This verifies response freshness, not the completeness of upstream ingestion.

## Secret coverage and private handling

PR/push checks scan changed files still present at the selected revision,
including Markdown and SVG. Scheduled/manual checks scan the complete current
tracked text snapshot. Local runs also include non-ignored untracked files and
mark dirty source/control worktrees in their receipts; those are not exact-head
CI evidence. Text is copied as opaque `.txt` files so filename/path exclusions
cannot silently skip SVGs and deep Windows benchmark paths stay bounded.
Findings map back to the original relative path and location.

The wrapper always uses full redaction and ignores neither `.gitleaksignore`,
source baselines nor `gitleaks:allow` comments. Matches, snippets, credential values
and native scanner stderr are never printed or uploaded. Public output contains
only finding IDs, paths, package versions where applicable, positions and
content-bound fingerprints, capped at 50 findings with the full count. There is
no security artifact-upload job. Temporary staged files are removed at job end;
do not retain native scanner reports in issues, public artifacts or commits.

Binary/archive assets are counted but not scanned; known text extensions with
NUL bytes and undecodable text fail rather than silently disappearing. Archives
are not unpacked, and decoding depth is limited to two. This job is a snapshot
check, **not Git history scanning or proof that deleted/intermediate-commit
secrets were absent**. Enabled GitHub secret scanning and push protection provide
the repository service layer for their supported patterns. Non-provider patterns
and live validity checking remain disabled; no credential is exercised for triage.

If those GitHub services become unavailable, the replacement must include a
maintainer-operated full-history scan and a verified server-side/pre-receive or
private promotion gate that rejects synthetic protected pushes before publication,
with private alerts, owner response and retained redacted evidence. Local pre-push
hooks and PR snapshot checks alone are **not equivalent**. Service loss is an
open acceptance/promotion blocker until that equivalent is deployed and tested.

## Trust boundary and execution bounds

The coordinator and reusable worker use only `contents: read`, no inherited
secrets, no write permissions, no `pull_request_target`, no automatic updates or
merges, and no shared caches. Checkout credentials are not persisted. Controls
and input occupy separate checkouts; source `.cargo` settings, scripts and scanner
configs are never executed. Scanner child environments remove authentication and
tool-configuration variables and use temporary HOME/CARGO_HOME with Git prompts
disabled. PR changes to the **control code itself** remain untrusted code running
on a disposable read-only runner: code review and required checks, not directory
separation alone, defend that boundary. Never pass the operator admin token to CI.

Jobs have outer deadlines of two to eight minutes. Inner bounds include 120-second
tool downloads (96 MiB), a 90-second DB clone, 30-second remote lookup,
180-second audit, 120-second native secret/static scans and a four-minute OSV
batch loop. Inputs have a 20,000-path cap; ordinary files/locks are capped at
8 MiB, text-secret inputs at 16 MiB/file and 384 MiB total, scanner output at
8 MiB, and OSV queries at 5,000 packages in batches of 100. Linked/reparse inputs,
duplicate JSON fields and size/deadline breaches fail with fixed diagnostics.
Linux CI kills scanner process groups on timeout; local Windows checks bound the
direct scanner process, not arbitrary hostile descendant trees. No source
packages are built or launched to perform these scans.

## Ownership, updates and exact exceptions

`@KirilsTurkins` owns security triage and routes dependency findings to the
affected SDK/example/runtime maintainer. [CODEOWNERS](../../.github/CODEOWNERS)
routes control, policy, fixture and runbook changes for review; it is not itself
proof that branch protection enforces a review. The parent Phase 3 reviewer
centrally audits the exact PR head and decides merges, promotion and issue closure.

1. Treat suspected live credentials privately under the [security policy](../../SECURITY.md)
   and the enabled private vulnerability-reporting channel. Notify the credential
   owner for revocation/rotation; do not paste values, probe validity or use a
   public finding as evidence of compromise.
2. For advisories, record exact package/version/lock and advisory ID, confirm the
   dependency chain and reachable operation, and review the upstream patch and
   lock diff. Follow [#279](https://github.com/KirilsTurkins/latent-service-fabric/issues/279)
   for advisory-specific triage. A version match alone is not an LSF exploit.
3. Scanner outages, missing data and unknown inventory are failures owned by the
   security maintainer, not permission to waive an analysis or reduce its scope.
4. Submit updates and any temporary exception as reviewed PRs with fresh canaries
   and exact-head checks. No automation approves or merges dependency/workflow code.

[Dependabot configuration](../../.github/dependabot.yml) proposes weekly updates
to `development`, capped at three open version PRs per entry. Default-branch Cargo,
npm and scanner-pip entries use zero version PRs while allowing security proposals.
The seven-day cooldown affects version updates, not security fixes. GitHub security
updates target the default branch; `target-branch: development` does not change
that. These semantics were checked against the official
[Dependabot options reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference).
The nonstandard `tools/requirements.lock` and scanner binary pins retain a manual,
owned update process; OSV still checks their declared package graphs. Dependabot
configuration must also reach the default branch before its scheduling is active.

[Exceptions](../../.github/security/exceptions.json) require exact scanner, finding
ID, package **and version** for advisories, relative path, fingerprint, owner,
reachability/false-positive rationale, review issue/PR, created date and expiry.
Source/secret fingerprints bind the complete normalized file content and exact
line/column; advisory fingerprints bind the finding, package/version and lock
path. No wildcards, broad rule/path ignores, unowned entries or indefinite waivers
are accepted. Expiry is exclusive at UTC midnight, with a maximum 30-day lifetime;
expired or future entries fail every invocation, including docs-only scope checks.
An expired unused entry must still be removed or explicitly re-reviewed.

The initial policy proposed one compatibility waiver: zizmor
`self-repository` on the exact job-level local RustSec call, expiring **2026-10-03**.
GitHub resolves this reusable workflow at the caller commit, unlike a mutable
workspace-relative action step. #281 currently validates `./` references, not the
new `$/` syntax recommended by zizmor 1.30.1. The parent reviewed that exact call
in PR #363. Update the pin policy or re-review before expiry; adding an exception
file alone is not approval. The same reviewed policy now includes 16 exact
noncredential secret-rule occurrences: one labelled API-journal digest, one
synthetic environment-variable name and fourteen historical preparation lookup
identities. Their producer/ownership review and clean snapshot results are in the
[evidence ledger](security-baseline-evidence.md). They expire on 2026-10-03 and
cannot match a changed file, scanner location or rule. No dependency exception,
general digest exemption or path allowlist exists.

## Settings and operator commands

The authorized operator enabled and verified alerts, security-update proposals,
secret scanning/push protection and private reporting on 2026-09-19. The
[evidence snapshot](security-baseline-evidence.md) distinguishes those live states
from pending default-branch deployment and required-check configuration.
Read-only inventory uses an authenticated operator with repository-admin visibility:

```powershell
python tools/security_settings.py
```

`--enable` is the explicit, idempotent operator setting-change mode. API access
failures and disabled services are not success. The script never changes branch
protections, enables auto-merge, creates workflow credentials, probes a secret or
runs from CI. Re-run it at promotion and after service/permission changes.

In an isolated Python 3.13 environment, use a new ignored destination for scanner
installation. Each later scan re-verifies the installed binary and receipt:

```powershell
python -m pip install --only-binary=:all: --no-deps --require-hashes -r .github/security/requirements.txt
python tools/security_install.py --tool cargo-audit --destination target/security-tools
python tools/security_install.py --tool gitleaks --destination target/security-tools
python tools/security_install.py --tool zizmor --destination target/security-tools
python -m unittest discover -s tools/tests -p 'test_security*.py'
python tools/security_selftest.py --tools target/security-tools --scratch target/security-canaries
python tools/security_scan.py rustsec --repo . --tools target/security-tools --scratch target/security-runs
python tools/security_scan.py dependencies --repo . --tools target/security-tools --scratch target/security-runs
python tools/security_scan.py secrets --repo . --tools target/security-tools --scratch target/security-runs
python tools/security_scan.py static --repo . --tools target/security-tools --scratch target/security-runs
```

Do not overwrite an installed tool destination to hide a digest mismatch. Review
the failure and use a fresh destination for a reviewed update. For changed-file
secret scanning, supply `--base` with the full base commit; omitting it scans the
snapshot. `security_scan.py` exits 0 for no unexcepted findings, 1 for findings,
and 2 for unavailable/invalid data. The [fixture guide](../../tools/security_fixtures/README.md)
describes harmless pass/fail coverage, including why canary success means expected
bad fixtures were rejected rather than that vulnerable input was accepted.

## Rustls handshake boundary update

[RUSTSEC-2026-0285](https://github.com/RustSec/advisory-db/blob/main/crates/rustls/RUSTSEC-2026-0285.md),
published on 2026-09-14, affects Rustls 0.23.13 through 0.23.44. The outbound HTTP
and OCI clients previously pinned 0.23.44 and now pin the reviewed
[0.23.45 patch](https://github.com/rustls/rustls/releases/tag/v%2F0.23.45).
`Cargo.lock` selects the same patched version for the shared TLS dependency graph.

The upstream finding concerns accepting TLS 1.3 handshake messages at the wrong
encryption level. The handshake transcript remains authenticated; this update
is not evidence of an LSF interception exploit. Rebuild node and client binaries
and validate actual TLS success/rejection and HTTP/OCI cancellation behavior.
The advisory gate must pass with the updated lockfile; no suppression is added.

## Phase 3 acceptance handoff

[#240](https://github.com/KirilsTurkins/latent-service-fabric/issues/240) requires
#282 alongside [#238 integrated adversarial evidence](https://github.com/KirilsTurkins/latent-service-fabric/issues/238).
Before the parent can claim acceptance, it must review exact exceptions and
findings, audit the final PR head, promote controls normally to default `release`,
retain both-ref manual and scheduled results without changing locks, and require
`Security baseline result` alongside the existing `CI result` once deployed.
The 2026-09-19 snapshot still has only `CI result` required; this implementation
does not prematurely change protection on other in-flight Phase 3 PRs.

The renderer's initial advisory matches are removed by a reviewed, exact
`@bytecodealliance/weval` 0.5.0 override, without changing the renderer's AOT-disabled
profile or ComponentizeJS version. Older `release` lock findings, completed
full-snapshot secret triage and remaining deployment/evidence gaps are listed in the
[evidence ledger](security-baseline-evidence.md), not silently excepted. A real
fork execution and synthetic server push rejection were not performed by this
delivery; static fork-permission fixtures and enabled-service API state should
not be described as those tests. Parent review determines the remaining evidence
needed for acceptance. No scan certifies guest isolation, provider safety,
capability authorization or production hardening.
