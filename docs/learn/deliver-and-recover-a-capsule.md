# Deliver, invoke and recover a capsule

## Outcome and choose your path

Learn the actual package-to-invocation and controlled-update sequence: build and
inspect a package, verify its supplied trust, transfer it through an authenticated
registry, publish to a node, deploy, invoke, inspect uncertain results, promote
only observed healthy traffic, roll back and recover after restart.

Choose the right environment before running commands:

| Goal | Path |
| --- | --- |
| Evaluate a verified native bundle as an ordinary user | [Rootless evaluation and first retained invocation](../../packaging/linux/INSTALL.md#rootless-evaluation). No compiler, Docker or system service is required. Approved native release artifacts still depend on the [parent release gate](../operations/native-release-promotion.md). |
| Install a persistent native server | [Non-root systemd installation](../../packaging/linux/INSTALL.md#persistent-server), with explicit profile, protected credentials/trust and authenticated readiness. Do not replace this with a container installation. |
| Learn/reproduce the controlled source-based delivery workflow | The Linux contributor scenario below, using the existing maintained harness and a disposable registry fixture. Docker is only that test registry's host prerequisite, not an LSF installer prerequisite. |

This guide covers the delivered standalone, stateless development profile under
[#357](https://github.com/KirilsTurkins/latent-service-fabric/issues/357), not
transactional guest state, a durable outbox, distributed routing or workflows.
One node owns shared workers/caches; dormant deployments gain no per-app process,
listener or provider pool. Configured budgets and this small scenario are not
performance or hostile-multitenancy guarantees.

## Prerequisites, version and complete source

Use a clean, private checkout of the reviewed development source on Linux x86_64,
the [pinned contributor toolchain](../development/toolchain.md), Python **3.13.5**,
OpenSSL and the Docker CLI/daemon for the owned registry fixture. The node needs
readable Linux pressure observations and local filesystem locking/synchronization.
Do not run in another user's worktree or reuse their mutable Cargo target.

The complete scenario is [the operator runner](../../tools/run_phase2_operator_workflow.py),
[node/CLI sequence](../../tools/phase2_operator_scenario.py),
[canary sequence](../../tools/phase2_operator_canary.py) and
[finite process owner](../../tools/phase2_operator_process.py).
The [fixture exporter](../../crates/latent-policy/src/supply_chain/tests/operator_fixture.rs)
generates two test capsules, short-lived public policy and signed synthetic test
observations. Signing keys remain in memory and are not exported. These are
controlled fixtures, not a production publisher identity, real build provenance
or credentials/admission policy to install on an operator's server.

The delivery scenario enforces its supplied package-admission policy. That alone
does not establish the complete `external-capsule-v1` compiler/storage boundary;
the [security-profile workflow](../../tools/run_security_profile_workflow.py) and
[profile contract](../runtime/execution-security-profiles.md) qualify that
separately. Never silently weaken a profile to make a walkthrough pass.

## 1. Build the paired CLI and node, then export fresh inputs

Run from the clean repository root. This is source-based contributor validation,
not a downloaded-bundle bootstrap. The archive installer has its own independent
publisher-authentication-before-code sequence.

```bash
set -euo pipefail
umask 077
test -z "$(git status --porcelain=v1 --untracked-files=normal)"
SOURCE_COMMIT=$(git -c gc.auto=0 rev-parse HEAD)
export CARGO_TARGET_DIR="$PWD/target"
timeout --kill-after=15s 1800s cargo build -p latent -p latentd \
  --all-features --locked --jobs 2
REGISTRY_IMAGE=$(python3 -c 'from tools.run_oci_registry_tests import IMAGE; print(IMAGE)')
timeout --kill-after=15s 300s docker pull "$REGISTRY_IMAGE"
FIXTURE_PARENT=$(mktemp -d "${TMPDIR:-/tmp}/latent-operator-guide.XXXXXXXX")
LSF_OPERATOR_FIXTURE_ROOT="$FIXTURE_PARENT/inputs" \
  timeout --kill-after=15s 1800s cargo test -p latent-policy --lib \
  --all-features --locked --jobs 2 export_operator_workflow_fixture \
  -- --ignored --test-threads=1
test -f "$FIXTURE_PARENT/inputs/fixture.json"
```

Expected: a successful build, the actual exporter test executes, and a new
`inputs/fixture.json` exists. Zero matching tests or a missing file is not an
export. The registry image is selected by its reviewed immutable digest from
the maintained fixture owner, not a moving tag. No container is adopted, and
the runner must never remove another test's containers, images or volumes.

Export immediately before the next step. An expired fixture is a deliberate
failure: choose a fresh private parent directory and export again rather than
editing timestamps, overwriting inputs or accepting an old signed observation.

## 2. Run the real controlled CLI/node sequence

```bash
python3 -m unittest tools.tests.test_phase2_operator_workflow \
  tools.tests.test_phase2_operator_canary
timeout --kill-after=15s 360s python3 tools/run_phase2_operator_workflow.py \
  --cli "$CARGO_TARGET_DIR/debug/latent" \
  --node "$CARGO_TARGET_DIR/debug/latentd" \
  --fixture-root "$FIXTURE_PARENT/inputs" --source-commit "$SOURCE_COMMIT" \
  > "$FIXTURE_PARENT/operator-receipt.json"
```

The unit checks are not the real workflow: the second command starts a separate
native node and separate CLI processes. It owns a loopback TLS registry, private
node/client directories, protected explicit test credentials and finite process
groups. Its internal useful-work deadline is 300 seconds, with separate bounded
cleanup. It does not build binaries or pull an image implicitly.

Follow the source sequence while it runs:

| Stage | Action and expected observation |
| --- | --- |
| Package | Build and inspect blue/green packages; component digest identifies executable bytes, package digest includes package metadata. Inspection states `trustEvaluated:false` and `executionAuthorized:false`. |
| Transfer and trust | Push/pull exact package/evidence bytes through the authenticated TLS fixture; verify against the explicitly supplied test policy. Wrong registry credentials fail without publishing a partial output directory. Verification is not a node execution grant. |
| Publish and deploy | Publish each package to the test tenant and retain its publication reference. Apply with an explicit operation ID, deployment generation and node state precondition. The receipt, component, package, publication and routed revision are different identities. |
| Invoke | Use the real CLI/node RPC boundary and bounded guest input/output. Retain invocation identity before uncertainty can occur; a client timeout does not prove no execution. |
| Update | Reconcile an exact already-identified operation, change manual stages, reject promotion with no candidate observations, then use the bounded observed healthy window. Do not add arbitrary retries/calls until a canary turns green. |
| Recover | Look up the original operation after the short-deadline mutation attempt, retain unknown outcomes honestly, restore the recorded rollback target and verify the retained route after a process restart. |
| Revoke and stop | Exercise release lifecycle denial, bounded audit pages, clean node shutdown and reap the owned process groups. Audit observation is not durable external action. |

Read a bounded public summary rather than dumping credentials or node config:

```bash
python3 - "$FIXTURE_PARENT/operator-receipt.json" <<'PY'
import json
import sys

with open(sys.argv[1], "rb") as source:
    payload = source.read(65537)
if len(payload) > 65536:
    raise SystemExit("Workflow receipt exceeds its documented bound")
record = json.loads(payload)
if record.get("schemaVersion") != "latent.operator.workflow-test.v1" or record.get("passed") is not True:
    raise SystemExit("No successful operator workflow receipt")
print(json.dumps({"passed": record["passed"], "cliProcesses": record["cliProcesses"],
                  "successfulInvocations": record["successfulInvocations"],
                  "zeroDataCanaryVerdict": record["zeroDataEvaluation"]["assessment"]["verdict"],
                  "deadlineLookup": record["deadlineOperationLookup"]["disposition"],
                  "temporaryOutputsRemoved": record["temporaryOutputsRemoved"]}, indent=2))
PY
```

In the [retained real CI receipt](../evidence/core-operator-walkthrough-35454985599.json),
this scenario uses 114 CLI processes, two packages and 18 successful guest
invocations. The no-data canary stays `CANARY_VERDICT_NO_DATA`; a separate
healthy window observes 12 candidate and four baseline invocations. The short
deadline operation lookup is **`DEPLOYMENT_OPERATION_LOOKUP_DISPOSITION_UNKNOWN`**,
not proof of commit or non-execution. These are that run's observations, not
universal counts or a guarantee that a later schedule returns the same outcome.

## 3. Diagnose failure without adding authority or retries

| Failure | What to inspect; what not to do |
| --- | --- |
| Invalid/expired fixture or incompatible node/compiler | Check the selected source/toolchain and profile. Re-export only after the old owned run stops; never change signed timestamps or disable admission/isolation. |
| Wrong node/registry credentials | Check the protected selected client/profile path and tenant. Keep tokens out of argv/logs; do not widen the listener or reuse test credentials on a real installation. |
| No-data canary promotion rejected | Inspect selected/admitted/terminal observations and retained window identity. Rejection leaves the route unchanged; do not reinterpret missing data as health. |
| Deadline or lost mutation response | Query the exact operation ID under the same tenant and precondition. `unknown` stays unknown; do not send a new mutation or infer non-execution from an absent retained receipt. |
| Restart does not recover the same route/receipt | Preserve the private diagnostic context and stop. A successful new publish/deploy would hide a retention failure. |
| Shutdown/registry cleanup fails | Treat the run as failed. Reap only the owned process/container identity; no broad process kills, Docker pruning or deletion of another run's state. |

The [offline workflow](../../tools/run_phase2_offline_workflow.py) separately
proves retained invocation while the owned registry is stopped, failed new
transfer and revoked-invocation denial. The
[publication workflow](../../tools/run_publication_workflow.py) separately checks
publication/tenant identity, renewal, rollback and restart. Their compact actual
receipts are linked with the same CI build identity; do not substitute these
scenarios for a missing provider or language-client walkthrough.

## Cleanup, evidence and next step

On success or ordinary interruption, the runner removes its own node/client/
registry outputs and reaps its owned processes. The explicitly created
`FIXTURE_PARENT` still contains the exported inputs and small receipt for review.
After retaining only the redacted receipt/digests, remove only that verified
new directory; never remove an installed node's retained state. A stopped source
test is not a native uninstall or installation-ID-confirmed purge.

The recorded CI run reviews PR head `edec84fa17460b11e166cbb25a9e51f7ea15e78b`,
but its executed checkout/build receipt is
`05360c50eb6c40212111ad0d87198db5dead78a5`. The evidence preserves **both**, actual
CLI/node hashes and all eight collector hashes, checked against the integrated
guide base `1ed9ef3c`. This reuses executed retained evidence with a fresh source
binding check; it is not a new local Linux run, same-head VM receipt or release
attestation. A process restart here is not the [real native VM reboot evidence](../evidence/native-runtime-f8d0c51a.json).

Next, [reconcile a policy change](../how-to/reconcile-a-policy-change.md), or use
the [native retained-invocation instructions](../../packaging/linux/INSTALL.md#first-retained-invocation)
on an independently approved bundle. Rendered/newcomer review and the remaining
first-node/client/provider/Angular paths remain in the
[guide acceptance handoff](../development/operator-guide-acceptance.md).
