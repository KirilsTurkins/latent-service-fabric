# Phase 3 integrated runtime security conformance

Issue [#238](https://github.com/KirilsTurkins/latent-service-fabric/issues/238)
joins existing **executed guests, real scoped providers, shared ingress,
durable catalogs and supervised children** into an exact, bounded selection.
It does not replace those implementations or treat adapter unit tests as proof
of a running system. The dependency/advisory graph and shared SDK real-node
qualification are separate gates.

The executable inventory is
[`tools/phase3_security_cases.py`](../../tools/phase3_security_cases.py).
It defines 27 PR cases and a manual superset of 184 libtest entries, including
three fixture exporters, plus two custom compiler harnesses. The manual run
also executes three maintained separate-node workflows. These numbers count
test entries, not every internal schedule, assertion or provider request.

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
| HTTP/browser isolation (#235) | `browser-ingress`, `web-component`, `actual-browser` | Six real Wasm web-component cases cover authentication, response delivery, deadlines, cutover and revocation. A separate actual Chromium test hydrates/navigates **Node-rendered SSR** over the live shared ingress and checks injection/CSP/MIME/origin boundaries. It is not Angular-Wasm execution or the separately owned T1 renderer follow-up. |
| Protected files and readiness (#278) | `protected-files`, `profile-startup`, `security-profile` workflow | Real descriptors, ACLs, ownership, FIFO/link/ancestor replacement and snapshot mutation fail closed. A privileged disposable fixture explicitly runs the otherwise ignored wrong-owner case. Real `check-config`/`serve` failures occur before readiness/storage creation. |
| Publication identity, corrected SBOM and current authority (#267) | `parent-catalog-evidence`, `evidence-authority`, `current-trust`, `publication` workflow | Same component bytes with different packages/evidence remain independent across two tenants, revocation, renewal, restart and rollback. Historical receipts do not reissue current grants; legacy ambiguity is not resolved by first/latest selection. |
| Parent parsing and native currentness (#279) | `parent-package-parsers`, `parent-catalog-evidence`, `evidence-authority`, `guest-native_aot_cache` | Bounded malformed metadata/evidence is rejected before preparation authority. Engine mismatch, replaced native bytes, wrong host key, revoked publication and stale trust cannot authorize deserialization/reuse. The runner first requires the reviewed Wasmtime **47.0.4** lock/toolchain boundary. |
| Real compiler failure and actual isolation (#273/#280) | `guest-isolated_aot`, `compiler-supervisor`, `compiler-sandbox`, `current-trust`, `security-profile` workflow | Real child PID/input rendezvous, kernel denial and reaping cover deadline, resource failure, crash, malformed output, cancellation and unrelated guest availability. The adversarial supervisor fixture is not the production sandbox; both mains run separately. Compiler containment is not guest-process containment. |
| Native signed provider workflow (#226) | `provider-management` workflow | Existing real CLI/node/protected HTTP/blob workflow publishes maintained signed guests, invokes success/domain/denial paths, restarts, inspects exact selected revisions and revokes authority. Upstream request counts and clean provider/node shutdown are checked. No SDK participant or provider server is duplicated. |

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

CI can reuse its existing `$RUNNER_TEMP/lsf-workspace-tests.jsonl` instead of
building again, passing `$GITHUB_SHA`. The parent integration owner adds this
post-inventory hook; this ticket does not overwrite that owner's workflow work.
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
python3 tools/build_guest_capsules.py --output target/phase3-security/guest-capsules
cargo build --locked -p latent-toolchain-smoke --example web-contract \
  --target wasm32-unknown-unknown --release
wasm-tools component new target/wasm32-unknown-unknown/release/examples/web_contract.wasm \
  -o target/phase3-security/web.component.wasm
npm --prefix examples/renderer-profile ci --ignore-scripts --no-audit --no-fund
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
  --browser-toolchain /workspace/examples/renderer-profile
```

Replace explicit tool paths with the prepared image's paths. Host output must
be beneath this checkout's own `target` and must not already exist. The wrapper
uses the inspected immutable container ID for execution and, on success,
failure or cancellation, bounded stop plus inspection. It never removes a
container/volume. A Docker/OS failure to verify stop is a cleanup failure, not a
successful manual receipt. Start only that owned stopped container if a rerun
is needed; preserve other owners' work and volumes.

The inner manual command has its own bounds, but its receipt deliberately says
`enclosingContainerStopRequired: true`. Only the host wrapper can replace that
with verified stopped-container evidence. This matters for Playwright's
detached browser descendants: a process-group-only wrapper cannot honestly
claim to own them. The test container adds no production T2 guest-host feature.

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
- The two `harness = false` compiler mains are never invoked with `--list`.
  Their exact source/artifact identity and distinct successful completion
  markers are checked. Each is one custom entry, not a fabricated number of
  libtest successes. The source mains assert their own real child schedules.
- PR/manual budgets are 600/2400 seconds, with serial execution, 30-second
  listing bounds, 90-second ordinary cases and a 180-second supervisor bound.
  Maintained node workflows keep their existing 180/300-second budgets and run
  **in process** under their existing process owners, not in a killable outer
  interpreter that could abandon separately grouped nodes.
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

Unselected vendor fixtures, renderer/T1 follow-up, SDK clients, load campaigns,
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
