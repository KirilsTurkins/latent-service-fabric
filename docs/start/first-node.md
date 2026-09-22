# First node and retained invocation

## Outcome

Run a native node from source-built artifacts, publish the maintained echo guest,
invoke it, inspect a declared application failure, restart without republishing,
invoke the retained deployment, and stop cleanly. The walkthrough also deliberately
checks invalid configuration, an invalid capsule, wrong credentials and a stopped
node. It does not install a service or require a registry/container runtime.

## Supported version and prerequisites

This is the Linux **development**, `local-experimental-v1` / `trusted-local`
contributor path, not the externally supplied capsule profile. Use a new, private,
clean checkout of the reviewed guide commit, with the
[pinned toolchain](../development/toolchain.md), Python 3.13.5, a local filesystem
supporting catalog locks/directory synchronization and readable Linux CPU/memory
pressure observations. Do not reset somebody else's worktree or share a mutable
Cargo target. Native-bundle operators instead follow [installation](../installation.md).

The full implementation is [the first-node runner](../../tools/run_first_node_guide.py)
and its [scenario](../../tools/first_node_guide.py). They reuse the existing
[operator process owner](../../tools/phase2_operator_process.py). The runner
never builds/downloads artifacts, reads commands from Markdown or silently retries
an invocation, publication or deployment mutation. Existing
[interactive commands](../development/standalone-quickstart.md) remain available
for inspecting each step manually.

## Build the exact inputs

Run these commands from that clean repository root. The commit is recorded before
building; it identifies the source chosen by the build owner, not an attestation
inferred from an executable filename.

```bash
set -euo pipefail
umask 077
test -z "$(git status --porcelain=v1 --untracked-files=all)"
SOURCE_COMMIT=$(git -c gc.auto=0 rev-parse HEAD)
export CARGO_TARGET_DIR="$PWD/target"
python3 -m pip install -r tools/requirements.lock
cargo build -p latent -p latentd --locked
make echo-capsule
```

Expected: both native binaries under `target/debug/`, and the generated component,
capsule manifest, contracts, deployment and input under `target/capsules/echo/`.
The checked-in echo publication template contains placeholder digests and is not
a substitute for those generated inputs. Compilation alone has not invoked LSF.

## Run and inspect the walkthrough

The result directory is private and new. The runner separately owns temporary
node, client and package directories, never an installed node's data directory.

```bash
RESULTS=$(mktemp -d "${TMPDIR:-/tmp}/latent-first-node-results.XXXXXXXX")
python3 tools/run_first_node_guide.py \
  --cli "$CARGO_TARGET_DIR/debug/latent" \
  --node "$CARGO_TARGET_DIR/debug/latentd" \
  --echo-root "$CARGO_TARGET_DIR/capsules/echo" \
  --source-commit "$SOURCE_COMMIT" > "$RESULTS/receipt.json"
```

The scenario has a 180-second useful-work deadline and uses the maintained
separate process-cleanup deadlines. It creates fresh random credentials directly
in mode-0600 files under private directories. Tokens are neither arguments nor
public receipt fields. The listener is literal loopback with an ephemeral port;
only the owned node's validated startup record supplies the client endpoint.
Authenticated `node get` must report readiness before invocation. A bound socket
alone does not prove readiness.

| Stage | Expected observation |
| --- | --- |
| Configuration | `latentd check-config` accepts the protected local profile, rejects format version zero, and creates no node storage. |
| Local validation | Generated capsule/deployment validate; a deliberately invalid capsule is `local-error` before dispatch. |
| Authentication | A separately generated wrong-token client is rejected. The valid configuration remains unchanged. |
| Publication and deployment | Raw local admission returns the component digest and exact publication; a separate client manifest selects that publication. Deployment creation uses expected generation zero and retains the returned generation. |
| Invocation | `first-node-before` returns the positional WIT result `[{"ok":"hello"}]`; status is `completed`. `first-node-empty` is a separate `declared-error`, not success or a transport failure. |
| Restart | The same private catalog reopens, retains the release/deployment generation, and `first-node-after` returns hello without republishing or reapplying. |
| Removal and shutdown | Delete compares the retained generation, subsequent lookup is not found, and both node processes report clean shutdown and are physically reaped. |
| Unavailable node | A read against the stopped endpoint is a transport failure. No probe invocation or mutation retry is made. |

Check the bounded receipt rather than printing configuration or arbitrary logs:

```bash
python3 - "$RESULTS/receipt.json" <<'PY'
import json, sys
with open(sys.argv[1], "rb") as source:
    raw = source.read(65537)
if len(raw) > 65536:
    raise SystemExit("Receipt is too large")
record = json.loads(raw)
if record.get("schemaVersion") != "latent.first-node-guide.v1" or record.get("passed") is not True:
    raise SystemExit("The first-node walkthrough did not pass")
if (record["successfulInvocations"] != 2 or record["declaredErrors"] != 1
        or not record["retainedDeploymentInvokedAfterRestart"]
        or not record["temporaryOutputsRemoved"]
        or len(record["shutdowns"]) != 2
        or not all(item["clean"] and item["reaped"] for item in record["shutdowns"])):
    raise SystemExit("Missing invocation, recovery or cleanup evidence")
print("Two successful invocations, one declared error, retained restart, two clean stops.")
PY
```

A passing receipt includes exact CLI/node, collector, lock/toolchain and five
input-file hashes, rechecked after execution, plus the supplied build source.
It does not contain credentials, private directory names or raw child output.
The source field is explicitly caller-supplied: preserve the associated clean
build record rather than claiming the runner independently proves binary origin.

## Diagnose failures without changing authority

| Observation | Next action |
| --- | --- |
| `guide-check-failed` or nonzero exit | Stop and inspect the selected artifacts/profile and the [validation procedure](../development/core-guide-validation.md). No success is inferred from a partial run. The public runner deliberately withholds raw exceptions and child output. |
| `local-error` | Check selected file/manifest/configuration and local bounds. A local output error after a completed RPC can still retain remote completion; inspect `outcomeKnown` and the original identity. |
| Wrong credentials / permission denial | Verify the selected private profile and tenant, not a token pasted into argv. Do not disable authentication or widen the listener. |
| Node starts but is not ready | Inspect authenticated inventory and pressure/resource conditions. Read-only readiness polling does not authorize Invoke retries. |
| `declared-error` | Inspect the declared WIT result. Empty echo input is the intentional failure here, not a guest trap. |
| Timeout / transport failure / interruption | Query the original activation or operation identity where retained. A client timeout or not-found lookup does not prove non-execution; do not reinvoke blindly. |
| Shutdown or restart mismatch | Treat the walkthrough as failed. Republish/redeploy would hide the retention defect rather than repair its evidence. |

For manual diagnostics, use the exact [CLI categories and exits](../reference/operator-cli.md#output-and-exits)
and the [node configuration/profile contract](../reference/standalone-node.md).
The interactive quickstart and this runner create separate disposable state;
do not try to attach a second client to a runner directory after it has been removed.

## Cleanup, validation and next step

Normal completion/failure cleans the runner's own processes and temporary state.
SIGINT/SIGTERM use the maintained cancellation owner; forced supervisor death and
deliberate child session escape are outside that owner contract. The receipt is
not marked passed until cleanup succeeds. Keep only the small redacted receipt
and its source/build association. Remove the exact `RESULTS` directory you created
after review; leave any installed catalogs, other worktrees and shared caches alone.

The [synthetic regression suite](../../tools/tests/test_first_node_guide.py) tests
sequence rejection and process ownership, not LSF behavior. A real CLI/node run
under the selected source and a rendered newcomer review are separate acceptance
checks in the [validation record](../development/core-guide-validation.md).

Next: [author your first capsule](../learn/author-your-first-capsule.md), then
[trusted package delivery and recovery](../learn/deliver-and-recover-a-capsule.md).
