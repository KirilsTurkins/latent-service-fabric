# Phase 3 integrated runtime security conformance

Issue [#238](https://github.com/KirilsTurkins/latent-service-fabric/issues/238)
joins existing **executed guests, real scoped providers, shared ingress,
durable catalogs and supervised children** into an exact, bounded selection.
It does not replace those implementations or treat adapter unit tests as proof
of a running system. The dependency/advisory graph and shared SDK real-node
qualification are separate gates.

The executable inventory is
[`tools/phase3_security_cases.py`](../../tools/phase3_security_cases.py).
It defines 27 PR cases and a manual superset of 186 libtest entries, including
four fixture exporters, plus two custom compiler harnesses. The manual run
also executes four maintained separate-node workflows. These numbers count
test entries, not every internal schedule, assertion or provider request.

## Retained qualification on 2026-09-20

The [current raw manual receipt](../evidence/phase3-security-2026-09-20/manual-current.json)
([SHA-256](../evidence/phase3-security-2026-09-20/manual-current.json.sha256))
records a complete PASS at source
`c2a7635f0925af5e158af632696d26663e233752` in 523,245 ms:
186 libtest entries, both custom compiler mains and all four separate-node
workflows. The supervisor's 23 internal cases are checked individually; they
remain one custom entry in the aggregate. The actual publication, T1 security
profile, provider-management and Angular T1 workflows all passed.

The run used Linux x86_64 (WSL2 kernel `6.6.87.2-microsoft-standard-WSL2`),
Python 3.13.5, Rust 1.97.1 and Wasmtime 47.0.4 inside the explicitly owned
2-CPU, 8-GiB container. Fixture and executable hashes are retained. Temporary
outputs were removed, the enclosing container stopped, and its target volume
was preserved. Root was limited to this disposable fixture environment; these
results do not qualify an arbitrary deployment or unsupported host.

The [preceding failed receipt](../evidence/phase3-security-2026-09-20/superseded-output-contract-failure.json)
is preserved: its 186 libtest entries passed, but the runner still required the
obsolete compiler completion format, so later workflows were not executed.
The corrected runner requires every current start/pass record and exact summary.
It does not relabel that earlier failed run. The separate intermittent CI
publication-admission failure remains under investigation; this receipt records
one complete bounded observation, not a universal liveness guarantee.

## Evidence boundaries

| Concern | Exact inventory groups | Actual boundary and observation |
| --- | --- | --- |
| Import, requested/deployment policy, principal and operation intersection | `guest-broker`, `guest-http`, `authority-intersection` | Real guest imports use the retained policy/catalog/activation owner. Forged scope is rejected before store/provider creation; a provider rendezvous revokes authority between two calls. The exhaustive intersection cases are explicitly supporting broker tests, not substitutes for these executions. |
| Stale handles and fresh activations | `guest-local_blobs`, `guest-streaming_http`, `guest-broker` | Real Wasm resource handles cannot cross activation incarnations; trap, cancellation and store retirement preserve then release actual I/O/buffer owners. Warm compiled code does not imply a warm guest instance. |
| Child privilege, conserved budgets and occupied cells (#272) | `guest-local_service` | Two real components use normal node admission, a fresh child principal/lineage and conserved grants. Concurrent imports cannot reuse a spent grant. A parent occupying the only cell receives prompt bounded rejection; parent cancellation/awaiter abandonment drives child cleanup. |
| SSRF, private networks, DNS rebinding, redirects and framing | `guest-http`, `guest-streaming_http`, `http-network` | Real loopback TCP/TLS and controlled DNS peers exercise the production provider. Original deadlines, credential destination checks, response framing limits and physical socket/buffer retirement remain visible. Address-grammar checks are supporting tests. |
| Registry authority and cleanup (#270) | `registry-network` | Real authenticated TLS/UDP/TCP peers exercise registry/token/content/upload distinctions, denied redirects/rebinding, lost or cancelled mutations and retained cleanup reservations. This reruns deterministic transport regressions, not the separately qualified hosted registry vendor campaign. |
| Blob paths, leases, corruption and uncertain publication | `guest-local_blobs`, `blob-storage`, `guest-s3_blobs` | Real local storage and controlled S3 protocol peers check scoped handles, pinned reads, corrupt ranges, failed unlink/sync and multipart cleanup after restart. Uncertain external state is not silently refunded or retried. |
| Secret rotation and redaction | `guest-local_secrets`, `guest-vault_secrets`, `http-network` | Actual guest reads, protected local files and controlled Vault/TLS peers exercise generation replacement, a held old read, expiry/clock rollback, opaque credential purpose and audit redaction. Old owners remain charged until retirement. |
| Event acceptance versus uncertainty (#271) | `guest-nats_events`, `guest-guest_sdk` | Production NATS transport and the maintained compiled Rust event guest use controlled TLS protocol peers. A received publication can have an invalid/lost acknowledgement; a later denied call cannot undo an earlier acknowledged publication. Counts and explicit unknown outcomes rule out implicit retry. Neither acceptance nor audit proves consumer processing, an atomic batch, an outbox or exactly-once effects. |
| Two occupied gRPC slots (#277) | `grpc-residency` | Silent, partial and unauthenticated HTTP/2 peers reach measured connection occupancy. EOF/retirement precedes refund; fresh authenticated status work still succeeds. PING, bad authentication, age drain, disconnect and shutdown cannot silently renew residency. |
| HTTP/browser isolation (#235) | `browser-ingress`, `web-component`, `actual-browser`, `actual-browser-application` | Six real Wasm web-component cases cover authentication, response delivery, deadlines, cutover and revocation. Two Chromium cases hydrate/navigate **Node-rendered SSR** over live shared ingress and check injection/CSP/MIME/origin boundaries. The public-application case executes the real public HTTP component and denies management RPC paths, credential forwarding and cookie-derived authentication. This is not browser hydration of Angular-Wasm output. |
| Protected files and readiness (#278) | `protected-files`, `profile-startup`, `security-profile` workflow | Real descriptors, ACLs, ownership, FIFO/link/ancestor replacement and snapshot mutation fail closed. A privileged disposable fixture explicitly runs the otherwise ignored wrong-owner case. Real `check-config`/`serve` failures occur before readiness/storage creation. |
| Publication identity, corrected SBOM and current authority (#267) | `parent-catalog-evidence`, `evidence-authority`, `current-trust`, `publication` workflow | Same component bytes with different packages/evidence remain independent across two tenants, revocation, renewal, restart and rollback. Historical receipts do not reissue current grants; legacy ambiguity is not resolved by first/latest selection. |
| Parent parsing and native currentness (#279) | `parent-package-parsers`, `parent-catalog-evidence`, `evidence-authority`, `guest-native_aot_cache` | Bounded malformed metadata/evidence is rejected before preparation authority. Engine mismatch, replaced native bytes, wrong host key, revoked publication and stale trust cannot authorize deserialization/reuse. The runner first requires the reviewed Wasmtime **47.0.4** lock/toolchain boundary. |
| Real compiler failure and actual isolation (#273/#280) | `guest-isolated_aot`, `compiler-supervisor`, `compiler-sandbox`, `current-trust`, `security-profile` workflow | Real child PID/input rendezvous, kernel denial and reaping cover deadline, resource failure, crash, malformed output, cancellation and unrelated guest availability. The adversarial supervisor fixture is not the production sandbox; both mains run separately. Compiler containment is not guest-process containment. |
| Native signed provider workflow (#226) | `provider-management` workflow | Existing real CLI/node/protected HTTP/blob workflow publishes maintained signed guests, invokes success/domain/denial paths, restarts, inspects exact selected revisions and revokes authority. Upstream request counts and clean provider/node shutdown are checked. No SDK participant or provider server is duplicated. |
| Actual selected Angular under protected T1 (#226) | `fixture-angular`, `angular-t1` workflow | The maintained actual Angular build is freshly signed by the existing exporter, then the existing separate-node T1 runner checks enforced publisher/builder/SBOM admission, isolated compilation, selected renders, cancellation/disconnect reclamation, stale grants, independent same-component publication revocation and restart. A native-cache hit must be newer than the pre-restart high-water mark. No T0 receipt, backend grant, reference-app browser result or staged canary is substituted. |

Existing fixtures use their own bounded rendezvous: accepted request/frame,
provider gate, actual child input marker, observed store/connection ownership,
or controlled clock. A watchdog expiring is not by itself evidence that work
started or cleanup finished. Some contracts deliberately retain a quarantine,
remote uncertainty or durable cleanup reservation; the suite does **not** turn
all terminal responses into an invented all-zero resource snapshot.

## Narrow PR command

Use Python 3.13+, Linux x86-64 and the repository's locked Rust toolchain.
Produce the inventory in the same checkout/job as the tests:

```sh
mkdir -p target/phase3-security
cargo test --workspace --all-targets --all-features --locked --no-run \
  --message-format=json,json-render-diagnostics > target/phase3-security/inventory.jsonl
python3 tools/phase3_security.py --profile pr \
  --inventory target/phase3-security/inventory.jsonl \
  --source-commit "$(git rev-parse HEAD)" \
  --output target/phase3-security/pr-receipt.json
```

CI reuses its existing `$RUNNER_TEMP/lsf-workspace-tests.jsonl` instead of
building again, passing `$GITHUB_SHA`. The narrow hook runs after the current
Cargo inventory and Python 3.13 setup, under a 12-minute outer watchdog, and
retains `target/phase3-security/pr-receipt.json` as a commit-labelled artifact.
The PR selection has no external provider, browser or guest-toolchain build
prerequisite beyond the ordinary workspace test build. It uses 27 exact
already non-ignored tests. It does not claim the broader manual profile passed.

## Explicitly owned manual command

Run the broader profile only in a **dedicated disposable Linux x86-64
container**. It requires root inside that container for the wrong-owner file
fixture, POSIX ACL support and the actual Landlock/seccomp compiler profile.
The browser's OS sandbox is disabled by the existing fixture when run as root;
this is recorded, not described as browser-process containment.

The host wrapper
[`tools/phase3_security_container.py`](../../tools/phase3_security_container.py)
accepts an already prepared container only if:

- its `latent.phase3-security.owner` label exactly matches the caller's label;
- `/workspace` is this checkout, with no Docker socket, privileged/host-PID
  mode, added capabilities, host networking or device grants;
- init is enabled and limits are positive and no larger than 2 CPUs, 8 GiB and
  512 PIDs; auto-remove is disabled so stopped state can be inspected.

For example, create a uniquely named container using an explicitly selected
local toolchain image. Do not reuse a parent/other agent's container or target
volume. The image must provide the pins in
[`tools/toolchain.toml`](../../tools/toolchain.toml), `wit-bindgen-cli 0.60.0`,
Node 24.19.0 and an explicitly selected Chromium binary. The validated browser
dependencies come from the renderer profile's existing `package-lock.json`.
Linux x86-64 Chromium 153.0.8010.47 is the local qualification target; the
receipt records the actual version and executable hash.

```sh
docker run -d --init --name lsf-phase3-security-owned \
  --label latent.phase3-security.owner=phase3-security-owned \
  --cpus=2 --memory=8g --pids-limit=512 \
  --mount "type=bind,source=$PWD,target=/workspace" \
  --mount type=volume,source=lsf-phase3-security-owned,target=/workspace/target \
  --workdir /workspace \
  --env CARGO_BUILD_JOBS=2 --env CARGO_INCREMENTAL=0 \
  --env CARGO_PROFILE_DEV_DEBUG=0 --env CARGO_PROFILE_TEST_DEBUG=0 \
  YOUR_EXPLICIT_TOOLCHAIN_IMAGE sleep 10800
```

A Windows git worktree also needs its common `.git` directory mounted read-only
and `GIT_DIR`, `GIT_COMMON_DIR`, `GIT_WORK_TREE=/workspace` pointing at the
corresponding **own** worktree inside that mount. The runner uses
`GIT_OPTIONAL_LOCKS=0`; it must not rewrite another worktree's index or branch.
Do not infer source identity from an environment variable instead of these
readable git objects.

Prepare inputs inside the owned container using maintained builders. Install
the browser dependency tree using Node 24.19.0; keep the repository's separate
SDK toolchain pin intact. Builds are prerequisites, not test evidence:

```sh
mkdir -p target/phase3-security
cargo build --locked -p latent -p latentd -p latent-wasmtime --bins
cargo build --locked -p latent-wasmtime --bin latent-aot-compiler --release
python3 tools/build_guest_capsules.py --output target/phase3-security/guest-capsules
cargo build --locked -p latent-toolchain-smoke --example web-contract \
  --target wasm32-unknown-unknown --release
wasm-tools component new target/wasm32-unknown-unknown/release/examples/web_contract.wasm \
  -o target/phase3-security/web.component.wasm
npm --prefix examples/renderer-profile ci --ignore-scripts --no-audit --no-fund
python3 tools/build_angular_package.py \
  --input-root examples/angular-application \
  --toolchain-root examples/renderer-profile --cli target/debug/latent \
  --target-root target/phase3-security/angular-build \
  --output target/phase3-security/angular-build/actual \
  --cargo-target-dir "$PWD/target" \
  --repository https://github.com/KirilsTurkins/latent-service-fabric
cargo test --workspace --all-targets --all-features --locked --no-run \
  --message-format=json,json-render-diagnostics > target/phase3-security/inventory.jsonl
```

Give large builds their own finite external watchdogs. The existing guest
builder itself has bounded commands and a 900-second build budget. Do not
update generated bindings or fixture ceilings to make a test pass. If debug
sections make the approved compiler too large, use the existing CI recipe's
`objcopy --strip-debug` into a separate owned output, not Cargo's executable.

From this checkout on the host, with Python 3.13+ and the Docker CLI:

```sh
python3 tools/phase3_security_container.py \
  --container lsf-phase3-security-owned --owner phase3-security-owned \
  --output target/phase3-security/manual-receipt.json -- \
  --inventory /workspace/target/phase3-security/inventory.jsonl \
  --source-commit "$(git rev-parse HEAD)" \
  --cli /workspace/target/debug/latent \
  --node /workspace/target/debug/latentd \
  --compiler /workspace/target/debug/latent-aot-compiler \
  --guest-capsules /workspace/target/phase3-security/guest-capsules \
  --web-component /workspace/target/phase3-security/web.component.wasm \
  --browser-node /opt/phase3-node/bin/node \
  --browser-chrome /usr/lib/chromium/chromium \
  --browser-toolchain /workspace/examples/renderer-profile \
  --angular-build /workspace/target/phase3-security/angular-build/actual \
  --angular-compiler /workspace/target/release/latent-aot-compiler
```

Replace explicit tool paths with the prepared image's paths. Host output must
be beneath this checkout's own `target` and must not already exist. The wrapper
uses the inspected immutable container ID for execution and, on success,
failure or cancellation, bounded stop plus inspection. It never removes a
container/volume. A Docker/OS failure to verify stop is a cleanup failure, not a
successful manual receipt. Start only that owned stopped container if a rerun
is needed; preserve other owners' work and volumes.

The Angular builder must resolve the pinned Node and `wit-bindgen` through its
explicitly provisioned `PATH`; the browser's separate executable argument does
not configure build tools. The manual profile requires actual `observation.json`
and package bytes, not a copied success receipt. It hashes that complete build
before and after execution. Fresh signing occurs inside the selected Cargo
exporter. The optimized Angular compiler is separately hashed; ordinary compiler
failure/current-trust fixtures retain their own supplied compiler identity.

The inner manual command has its own bounds, but its receipt deliberately says
`enclosingContainerStopRequired: true`. Only the host wrapper can replace that
with verified stopped-container evidence. This matters for Playwright's
detached browser descendants: a process-group-only wrapper cannot honestly
claim to own them. The test container adds no production T2 guest-host feature.

The private container-entry protocol also returns bounded negative receipts.
The host CLI exits **nonzero** for `latent.phase3.security.failure.v1` and retains
`passed: false`, the public failing stage/classification, validated cases, the
active attempted case and the cases/workflows not executed. An accepted command
is distinct from an accepted test result. Only a verified outer stop can mark
container cleanup complete. Transport/OS failures before a receipt remain
unclassified failures, not invented zero-test successes.

Failure receipts additionally retain at most eight public top-level `tools/`
source filenames and line numbers from the bounded exception stack. Private
paths, source text, exception messages, locals and arbitrary metadata are not
included. The enclosing owner validates those coordinates before retaining a
receipt. This keeps an otherwise generic workflow failure diagnosable without
relaxing error-output redaction or changing execution/retry behavior.

## Startup fixture CI regression

[CI run 35456162060](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35456162060)
at `dc7f636b5e31bf6be8ea3ed22eaa2ab679045cf8` failed the Rust 1.97.1
strict Clippy step with 11 `large_futures` diagnostics: 16392–16408-byte
futures in the shared asset/browser and measurement startup fixtures. The
correction reuses parent changes `0af1589e` and `0b20cf9c`: box the awaited
node startup in the asset harness and catalog opening in the measurement
fixture. Both remain awaited by the same owner; no detached task, lint
suppression, timeout increase or production recovery change is introduced.

Subsequent Rust build/test and browser steps in that run were **not executed**.
The missing browser artifact upload is a consequence of those skipped steps,
not independent evidence of a browser regression. This diagnosis does not
attribute earlier unclassified manual failures to startup recovery.

## Inventory, bounds and retention

- Selection uses Cargo's successful terminal JSON inventory, exact package,
  target kind/name and source path. Executables must be regular files under
  this checkout's `target/debug/deps`; no hashed-filename glob or cached test
  result is trusted. Library and integration targets cannot substitute for one
  another. This is a caller-supplied **current-job build inventory**, not a
  cryptographic build attestation.
- Every selected libtest is checked against both complete and ignored lists,
  then executed by `--exact --test-threads=1`. Its individual result must be
  exactly one passed, zero failed/ignored/measured. Missing tests, changed ignore
  state, zero matches and duplicate/ambiguous artifacts fail. The 16 selected
  ignored fixtures/cases are intentionally executed in the manual profile,
  never counted as skipped successes.
- The browser child's inherited stdout is matched byte-for-byte to its bounded,
  schema-checked on-disk probe receipt. Only that record may interrupt its named
  libtest status line; arbitrary logs, duplicate records, fabricated component
  rendering and altered result counts are not normalized into a pass.
- The two `harness = false` compiler mains are never invoked with `--list`.
  Their exact source/artifact identity and distinct successful completion
  records are checked. The supervisor must emit one exact 23-case summary and
  one start/pass record for every maintained readiness and ownership case.
  Each main is one custom entry, not a fabricated number of libtest successes.
  The source mains assert their own real child schedules.
- PR/manual budgets are 600/2400 seconds, with serial execution, 30-second
  listing bounds, 90-second ordinary cases and a 180-second supervisor bound.
  Maintained node workflows keep their existing 180/300-second budgets; the
  Angular T1 workflow keeps its existing 1200-second budget. All run
  **in process** under their existing process owners, not in a killable outer
  interpreter that could abandon separately grouped nodes. Publication requires
  three reaped, clean node lifetimes; security-profile and provider-management
  each require two, as does Angular T1. An absent or extra shutdown record fails
  the exact profile. Angular additionally requires the actual protected T1
  controls, explicit and disconnect cancellation, unchanged native cache files
  and a strictly post-restart cache-hit sequence.
- Capture is bounded per command, Cargo input to 32 MiB, ordinary files to
  1 GiB, fixture trees to 4096 entries/128 MiB and final receipts to 128 KiB.
  Helpers retain the leader until group cleanup/reaping. Deliberate OS/session
  escape, uninterruptible creation and abrupt supervisor death are not claimed
  as capabilities of that helper; the manual container owner is the outer
  cleanup boundary.
- Receipts retain the exact source/lock/matrix, test executable and fixture
  identities, selected names, platform/engine/tool facts, explicit ignored
  executions and compact validated workflow summaries. Raw provider responses,
  credentials, private paths and large logs are not retained. Runner failures
  expose only a selected public case ID and a bounded classification.

Unselected vendor fixtures, parent-owned #236 reference-app browser/backend/canary
qualification, shared SDK clients, load campaigns,
non-Linux platforms and stronger guest-host profiles are explicit exclusions,
not silently ignored matrix successes. See the existing
[browser boundary qualification](browser-boundary.md),
[trusted AOT boundary](../runtime/trusted-aot.md) and
[security architecture](../architecture/security.md).

Runner contract tests are independent supporting evidence:

```sh
python3 -m unittest tools.tests.test_phase3_security
```

Their observed descendant timeout/retirement case is Linux-only. A Windows
skip of that test is not Windows qualification of the runtime matrix.
Interrupted Docker runs contribute neither pass nor application failure
evidence; rerun in the recovered, explicitly owned container.

## Recovered evidence and current integration

The [complete integrated receipt](../evidence/phase3-238-manual-742b6e4f.json)
passes at clean source `742b6e4feaebf0d71e19d4ebd7e7dbfeb9465b3e`:
188 test entries, including both custom compiler harnesses, all four separate-node
workflows and 18 explicitly selected ignored cases. The runner executes 245
commands in 556141 milliseconds. The actual public browser application runs with
zero browser errors, and the selected Angular T1 workflow passes. The outer
owner verifies that its container stopped and that its volumes were preserved.
The raw receipt retains the source, binary, fixture and browser identities.

The preceding attempt used an older public web-component fixture and failed the
application browser case. Rebuilding that fixture from the selected source
passed the isolated case and then this entire manual profile. That failed
attempt contributes no success evidence. The receipt above qualifies its exact
source; subsequent CI repairs still require their own current-head checks.
The #236 reference application, shared SDK matrix, hosted vendor campaigns,
load and T2 containment retain their separate qualification boundaries.

The prior worker's preserved `manual-3ef67953.json` is a genuine complete pass on
`3ef67953b5a26e6080d821544f397e74d2ae9fb4`: 184 libtest entries, two custom compiler
mains and all three then-selected node workflows, in 366546 milliseconds. The
outer owner verified container stop. Earlier negative receipts, including the
isolated blob failure at `380f4d52`, remain retained and are not rewritten by this
later success.

The reconciled branch includes provider/development merge `bcd902cd` and the
qualified #226 T1 code through `3b5dbcf7`, plus parent Node descriptor correction
`946f9b82`. Its expanded 188-entry/four-workflow profile requires fresh
source-clean execution; the recovered older pass does not qualify the new
browser schema, Angular workflow or current CI head. The added runner checks
reject T0/partial Angular receipts, stale restart hits and browser observations
from the wrong fixture.

At source `0d9ca338620c01470c1a130191f08d4cf298f21d`:

- The [narrow PR receipt](../evidence/phase3-238-pr-0d9ca338.json) passes all 27
  entries in 67264 milliseconds, with clean tracked source and removed temporary
  outputs.
- The [expanded manual negative receipt](../evidence/phase3-238-manual-0d9ca338.failure.json)
  validates all 186 libtests, both custom compiler mains and the first three
  node workflows, then fails `workflow:angular-t1` with the generic
  `fixture-or-process-error` classification after 484255 milliseconds. The outer
  owner verifies container stop and preserves its volume. This is **not** a
  manual-profile pass, and it does not make the final unchanged-input claim.
- A subsequent [independent maintained T1 run](../evidence/phase3-238-angular-t1-0d9ca338.json)
  passes actual protected Angular admission, cold/warm selected rendering,
  cancellation/disconnect, independent publication revocation, HTTP lifecycle
  and restart. Its cache-hit sequence is 35, strictly newer than the prior
  high-water mark 19; both node lifetimes are reaped cleanly and native cache
  bytes remain unchanged. Cold preparation takes 24370 milliseconds. The
  integrated receipt validator independently accepts this result. It does not
  erase or explain the failed integrated attempt.

The independently passing T1 run uses the owned optimized compiler at
`/workspace/target/release/latent-aot-compiler`, SHA-256
`2bf91a38265241ae0948af1bb9b8a7646de8129ec7fc2d57dd1c55adf1b95566`.
All three committed receipts preserve the original generated bytes. Neither the
isolated T1 pass nor these narrow local results qualify the parent-owned #236
reference browser/backend/canary or a shared SDK matrix.

[CI run 35463162061](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35463162061)
at that head passes security, SDK surfaces, repository contracts, documentation,
MSRV and bounded catalog checks, but Rust workspace testing fails the protected
local-blob 32-start fixture at startup 6 with `configured-provider-unavailable`.
The subsequent absent browser artifact is a skipped-step consequence. Runtime
repair is carried by #424. The complete manual rerun above supersedes this
historical execution gap; current-head CI and the remaining Phase 3 gates
are still required before final acceptance.
