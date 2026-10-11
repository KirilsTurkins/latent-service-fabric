# PR 790 duplicate-command reconciliation

[PR #790](https://github.com/KirilsTurkins/latent-service-fabric/pull/790) contributes
bounded command notification, duplicate admission and result recovery to
[#387](https://github.com/KirilsTurkins/latent-service-fabric/issues/387).
The existing `9977333b` head had 51 successful hosted checks. Its normal merge
with development `2c817bbf` includes #787's complete command envelopes, #797's
original shared store capacity, #775's stream owners and #784's current guest
authoring. Those historical checks do not qualify the reconciled source.

## Preserved work and conflict decisions

The [cleanup draft #850](https://github.com/KirilsTurkins/latent-service-fabric/pull/850)
and [Portable handoff #978](https://github.com/KirilsTurkins/latent-service-fabric/pull/978)
identify the original code and qualification checkpoints. The deduplication
checkpoint `6dbbf49f` in
[#853](https://github.com/KirilsTurkins/latent-service-fabric/pull/853), waiter
checkpoint `7ccc3291` and ownership checkpoint `9ba17e05` are already ancestors
of the published PR head. Their implementation is retained; the old interrupted
merge is not reapplied. The separate #959 integration handoff records installed
workflow qualification and keeps its historical receipts at their original heads.

The source merge preserves bounded waiter slots, original attempt and fingerprint
identity, current result-read authorization, prepaid ingress reservations, retained
response ownership, retry associations and the conservative storage/recovery
checks. Development's physical cancellation/commit fences and all original tests
remain. The bounded storage getter shares the existing deterministic age-check
path, retaining both size refusal before copying and the original snapshot expiry
boundary. A merge mismatch in the atomic test seed is corrected without changing
its namespace setup or effect authority.

CI fragments are reconciled through semantic comparison and a lossless case/guard
union. Every original case, ignore, platform predicate, recipe and resource limit
is retained. Development's current compiler-download fingerprint remains enforced;
the additional Rust guest execution job and result-boundary variant are preserved.
One new unignored factory case is registered in exact discovery.

## Binding regression and actual guest checks

The first fresh 23-case guest campaign failed before execution: the merged linker
registered the same scoped transaction imports twice. The linker now installs
them once, after the optional activation-runtime bindings. Transaction support
still requires the explicit configuration flag and invocation authority.

The new supervised factory test initializes both ordinary and transactional
configurations, checks that initialization creates no guest Store/host state or
active invocation, and verifies original worker retirement. It runs in the normal
library suite rather than only in the explicit guest campaign.

All three maintained Rust variants compile with the pinned tools, reproducible
bindings and exact component surface checks. The reconciled components are:

| Variant | Component SHA-256 |
| --- | --- |
| Aggregate | `1be7c58d51a1b8400e5a348f2ee5dd8de13463e2cdba6cc425a543c28e74d5c3` |
| Forbidden HTTP | `44ffed921e3f5a82e99cb2754a403f25afc99f06b606a4deb01c1b67ec60b7cb` |
| Result boundary | `8760add5c91207a7905c6463bf2a982d2cff0ad3b167fe5ae863fc8a26da0e15` |

The original 23 explicit real-component RPC/manager scenarios now pass. Their
actual guest execution/Store counts, commits, result bodies and effect identities
remain the oracles. Coverage includes duplicate/conflicting input, dropped waiters,
lost and rejected responses, current caller/token rotation/revocation, shared and
delegated scopes, compatible rollout, namespace recreation, pending/committed
restart and process loss, retention pressure/expiry, maximum/oversized results,
confirmed-abort retries and preserved attempt history. Fresh cleanup observations
retain their original assertions. The trusted-local component catalog is explicit;
this is not a signed-package or full installed standalone qualification claim.

## Validation and delivery boundary

The ten selected native library suites pass 1,935 cases on pinned Rust 1.97.1
Linux with ext4 scratch storage. Exact discovery matches the unioned case and
ignore sets; all 59 original ignores remain. The full Wasmtime library adds
352 passes with two original ignores and exact 354-case discovery, including
the new factory regression. A relative
catalog-root fixture initially hit the read-only source mount; its unchanged test
passes from owned ext4 scratch. Failed attempts remain in local evidence.

All 104 focused schema, transaction, authoring, compiler, workflow and diagnostic
tests pass on Python 3.13.5 Linux without skips. Windows retains its seven original
platform skips. Ordinary selected Clippy and the repository's four-package
warnings-as-errors gate pass. The exploratory stricter node lint run retains
existing warnings; no lint policy or execution guard is weakened. Formatting,
repository/docs validation and read-only CI coverage pass. Coverage preserves
88 baseline and 274 current required run blocks and 144 delegated script owners.

The PR closes no issue. Full signed admission and installed standalone new-boot,
restore and distribution workflows still require their own current-source
qualification. Current hosted CI is required and is not awaited for publication.

## CI profile follow-up

The `06855284` CI run exposed four merged suite counts that counted runnable
tests instead of every discovered case, including ignores. The exact catalogue
requires the latter. ControlStore, Policy, Wasmtime and latentd now register
265, 147, 354 and 329 cases respectively. Every case and ignore list is unchanged.
The original pull-request event selects full validation, and all 44 profile,
inventory, discovery and result tests pass on Python 3.13.5 Linux without skips.
The separate SDK security failure reports newly published Go 1.27.1 advisories;
its compiler/runtime remediation is tracked independently of this count repair.

## Go security follow-up

The SDK scan reported 13 newly published Go advisories in each of the client and
guest dependency locks. Both now use Go 1.27.2, including the actual patched
compiler/standard library, regenerated module inventories and manifest hashes.
The [upstream patch release](https://go.dev/doc/devel/release#go1.27.2) and its
official Linux archive SHA-256
`ecbadb99091a3f46e31f5f934b068b1864eafa7995211b39eaddf76996045fe5`
remain the source of the compiler bytes. Modules and their checksums are unchanged.
The live unchanged security scanner now reports zero findings over 3,339 packages;
no security exception or advisory suppression is added.

The async guest fork has no matching 1.27.2 release. Its reviewed five-file
`wasiOnIdle` scheduler change is assembled into a fresh private copy of the exact
upstream Go source tree, with all preimage/postimage hashes checked. The upstream
input and compiler binary stay unchanged. Invocation builds retain their original
read-only GOROOT and clock/entropy source-overlay controls. Both developer bundle
assembly and the maintained CI/local guide stage this same profile explicitly.
Compiler selection validates the derived runtime sources before invoking the
generator, whose unsupported-compiler fallback would otherwise download 1.27.1.
The failed fallback attempt is preserved separately.

All nine current Go SDK fixtures build and all ten signed component/runtime
cases pass, including suspension, cancellation, owned resources, denial, fresh
state and cleanup. Both authored transaction variants and the upstream/constrained
probe build; the real diagnostic preserves full-width/UTF-8 results, declared
rejection, the original controlled trap and a successful fresh call. External
client RPC generation/check, dependency reproduction, all Go tests and vet pass.
The five new source-assembly/overlay controls pass on Windows and Linux. All 144
focused Linux version/capture/dependency/packaging tests pass without skips;
Windows's local symlink-privilege limitation does not alter the hosted guard.

Reviewed CI contract updates preserve all original case names, skip predicates,
commands, resource limits, required artifacts and historical obligations. The
added direct source-assembly owner is fingerprinted; coverage retains 88 baseline
and 274 current required run blocks with 145 delegated owners. Current-host CI is
not awaited after the fixes are pushed. #387 still has no automatic closure.

## CI contract and fixture follow-up

The `96bf0411` hosted run exposed four failed jobs. Documentation and the Python
lane both rejected the historical Go probe's changed compiler path. Its migration
test now reviews exactly that substitution while keeping every other command
byte, output and execution guard. The Python lane also found three stale source
hashes in the developer composition matrix. The transaction-aware native surface,
explicit node configuration and structural packaging definitions are reviewed
against their committed bytes and refreshed; every support row and its structural
qualification boundary stays unchanged.

The S3 build failed at its exact compiler-version check: its image digest still
selected Go 1.27.1 while the recipe required 1.27.2. The builder now pins the
official Linux amd64 Go 1.27.2 image
`sha256:55395706e9703db746cc507abfc4eb2aea75918f8a8024e4848e2cb81004f5ad`.
The [official image source](https://github.com/docker-library/golang/blob/8380885ec449224702b989d8792d2e1470a46e89/1.27/bookworm/Dockerfile)
and actual image execution confirm the version. All source/module digests, recipe
checks and original container resource limits remain required.

The C tool bundle failed before receiving a response from the pinned Zig mirror.
Only that source may retry up to three opening timeouts under the original
600-second download deadline and 60-second socket bound. Partial-body failures,
permanent errors, invalid archives and other compiler sources retain immediate
failure. Six new regressions cover the retry boundary, exhaustion, shared deadline,
permanent errors, partial-body cleanup and invalid attempt counts; every previous
case and guard remains. A fresh actual mirror download verifies the original
55,478,392-byte archive and SHA-256 without a cache or alternate endpoint.

CI ownership and Python case fingerprints are explicitly refreshed for these
repairs. Coverage retains 88 baseline and 274 current required run blocks with
145 delegated owners. All 96 focused repair tests pass. The complete 3,670-case
Python suite passes on pinned Python 3.13.5 with an unprivileged Linux user:
3,652 passes and 18 existing platform/environment skips. All ten tracked edits
match the source bytes copied to Linux storage; the initial slow Windows-mount
attempt and incomplete container setup attempts remain separate diagnostics.
The tests are unchanged when supplying their required compiler and archive tools.

The actual S3 fixture builds with Go 1.27.2, passes its source/module and static
binary checks, and retires its compiler with exit zero and no OOM. The generated
binary records Go 1.27.2 in its build information. Repository, build foundation,
docs and reviewed coverage validation pass. The hosted result still needs a fresh
run after publication; that run is not awaited. The PR closes no issue.
