# Standalone echo quickstart

The first sequence retains the Phase 1 trusted-local compatibility workflow.
For authenticated packages, managed receipts, canary promotion and rollback,
use the [bounded Phase 2 workflow](#bounded-phase-2-operator-workflow) below.

This Linux Bash sequence builds the maintained echo component, starts one local
node, and uses separate `latent` processes for publication, deployment, invocation,
status, and inventory. It performs one guest activation. Install the
[pinned toolchain and Python requirements](toolchain.md) first, then run from the
repository root. The node needs readable Linux pressure observations and a local
filesystem supporting catalog locks and directory synchronization.

Node data, client credentials/results, and the component package have separate
directories. The CLI sends package bytes over RPC; it never reads the node's
release or deployment directories. Tokens are generated into private files and
never passed as command-line arguments. The temporary directory is left in place
for explicit inspection or a later restart with the same node configuration.

```bash
set -euo pipefail
umask 077
export CARGO_TARGET_DIR="$PWD/target"
cargo build -p latent -p latentd --locked
make echo-capsule

export LSF_QUICKSTART_DIR
LSF_QUICKSTART_DIR=$(mktemp -d "${TMPDIR:-/tmp}/latent-quickstart.XXXXXXXX")
BIN="$CARGO_TARGET_DIR/debug"
mkdir "$LSF_QUICKSTART_DIR/node" "$LSF_QUICKSTART_DIR/client" \
      "$LSF_QUICKSTART_DIR/package"
cp "$CARGO_TARGET_DIR/capsules/echo/echo-capsule.wasm" \
   "$CARGO_TARGET_DIR/capsules/echo/capsule.json" \
   "$CARGO_TARGET_DIR/capsules/echo/contracts.json" \
   "$CARGO_TARGET_DIR/capsules/echo/deployment.json" \
   "$CARGO_TARGET_DIR/capsules/echo/input.json" \
   "$LSF_QUICKSTART_DIR/package/"

python3 - <<'PY'
import json, os, secrets
from pathlib import Path
root = Path(os.environ["LSF_QUICKSTART_DIR"])
token = secrets.token_urlsafe(32)
node = {
    "formatVersion": 1, "dataDirectory": "data", "bind": "127.0.0.1:0",
    "nodeId": "quickstart-node",
    "execution": {"maximumWallTimeMillis": 5000},
    "credentials": [{"token": token, "subject": "quickstart-operator",
                     "tenant": "examples", "role": "operator"}],
}
client = {"formatVersion": 1, "defaultProfile": "local", "profiles": [{
    "name": "local", "endpoint": "http://127.0.0.1:1", "tenant": "examples",
    "token": token, "connectTimeoutMillis": 2000, "rpcTimeoutMillis": 5000,
}]}
for path, document in [(root / "node/node.json", node),
                       (root / "client/client.json", client)]:
    with path.open("x", encoding="utf-8") as output:
        json.dump(document, output)
        output.write("\n")
PY

NODE_PID=
stop_node() {
    if [[ -n "$NODE_PID" ]]; then
        local pid=$NODE_PID result=0
        NODE_PID=
        kill -TERM "$pid" 2>/dev/null || true
        for ((attempt=0; attempt<100; attempt++)); do
            if ! kill -0 "$pid" 2>/dev/null; then break; fi
            sleep 0.05
        done
        if kill -0 "$pid" 2>/dev/null; then
            kill -KILL "$pid" 2>/dev/null || true
            result=1
        fi
        wait "$pid" || result=1
        return "$result"
    fi
}
trap 'stop_node >/dev/null 2>&1 || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"$BIN/latentd" serve --config "$LSF_QUICKSTART_DIR/node/node.json" \
    >"$LSF_QUICKSTART_DIR/node/status.jsonl" \
    2>"$LSF_QUICKSTART_DIR/node/diagnostic.jsonl" &
NODE_PID=$!
export NODE_PID

# Wait at most ten seconds and inspect at most 64 KiB per output file.
# A bound endpoint is not itself proof that activation admission is ready.
python3 - <<'PY'
import ipaddress, json, os, time
from pathlib import Path
root = Path(os.environ["LSF_QUICKSTART_DIR"])
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    for name in ("status.jsonl", "diagnostic.jsonl"):
        try:
            with (root / "node" / name).open("rb") as source:
                data = source.read(65537)
        except FileNotFoundError:
            continue
        if len(data) > 65536:
            raise SystemExit("Node startup output exceeded its bound.")
        if name != "status.jsonl":
            continue
        for line in data.splitlines(keepends=True):
            if not line.endswith(b"\n"):
                continue
            record = json.loads(line)
            if (record.get("schemaVersion") != "latent.standalone.status.v1"
                    or record.get("event") not in ("ready", "started")):
                continue
            endpoint = record["endpoint"]
            host, port = endpoint.rsplit(":", 1)
            if (record["nodeId"] != "quickstart-node"
                    or not ipaddress.ip_address(host.strip("[]")).is_loopback
                    or not 1 <= int(port) <= 65535):
                raise SystemExit("Node returned an invalid startup endpoint.")
            path = root / "client/client.json"
            client = json.loads(path.read_text(encoding="utf-8"))
            client["profiles"][0]["endpoint"] = "http://" + endpoint
            path.write_text(json.dumps(client) + "\n", encoding="utf-8")
            raise SystemExit(0)
    try:
        os.kill(int(os.environ["NODE_PID"]), 0)
    except ProcessLookupError:
        raise SystemExit("Node exited before publishing its endpoint.")
    time.sleep(0.05)
raise SystemExit("Node startup time allowance expired.")
PY

cli() { "$BIN/latent" --config "$LSF_QUICKSTART_DIR/client/client.json" --output json "$@"; }
field() {
    python3 - "$@" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as source:
    value = json.load(source)
for key in sys.argv[2:]:
    value = value[key]
if not isinstance(value, str):
    raise SystemExit("Expected a string receipt field.")
print(value)
PY
}
PACKAGE="$LSF_QUICKSTART_DIR/package"
RESULTS="$LSF_QUICKSTART_DIR/client"

"$BIN/latent" --output json validate capsule "$PACKAGE/capsule.json"
"$BIN/latent" --output json validate deployment "$PACKAGE/deployment.json"
cli node get quickstart-node >"$RESULTS/inventory-before.json"
python3 - "$RESULTS/inventory-before.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as source:
    inventory = json.load(source)["data"]["inventory"]
if not inventory["health"]["ready"]:
    raise SystemExit("The node is not ready for activation admission; inspect its inventory.")
PY

cli release publish --manifest "$PACKAGE/capsule.json" \
    --component "$PACKAGE/echo-capsule.wasm" --contracts "$PACKAGE/contracts.json" \
    >"$RESULTS/published.json"
DIGEST=$(field "$RESULTS/published.json" data release digest)
cli release get "$DIGEST" >"$RESULTS/release.json"
cli release list --service examples/echo --page-size 1 >"$RESULTS/releases.json"

# Use the returned digest, even though the generated deployment already contains it.
python3 - "$PACKAGE/deployment.json" "$RESULTS/deployment.json" "$DIGEST" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as source:
    deployment = json.load(source)
deployment["spec"]["release"] = sys.argv[3]
with open(sys.argv[2], "x", encoding="utf-8") as output:
    json.dump(deployment, output)
    output.write("\n")
PY
cli deployment apply "$RESULTS/deployment.json" --expected-generation 0 >"$RESULTS/applied.json"
GENERATION=$(field "$RESULTS/applied.json" data deployment generation)
cli deployment get echo-production >"$RESULTS/deployment-get.json"
cli deployment list --service examples/echo --page-size 1 >"$RESULTS/deployments.json"
cli route get >"$RESULTS/routes.json"

cli invoke --service examples/echo --contract examples:echo/api@0.1.0 \
    --function echo --activation-id quickstart-echo --input "$PACKAGE/input.json" \
    >"$RESULTS/invoked.json"
python3 - "$RESULTS/invoked.json" <<'PY'
import base64, json, sys
with open(sys.argv[1], encoding="utf-8") as source:
    result = json.load(source)
assert result["category"] == "success"
payload = result["data"]["payload"]
assert payload["encoding"] == "base64"
assert payload["mediaType"] == "application/vnd.latent.wit-values.v1+json"
raw = base64.b64decode(payload["data"], validate=True)
assert len(raw) == int(payload["byteLength"])
assert json.loads(raw) == [{"ok": "hello"}]
print(raw.decode("utf-8"))
PY
cli activation get quickstart-echo >"$RESULTS/status.json"
cli node get quickstart-node >"$RESULTS/inventory-after.json"
cli node list >"$RESULTS/nodes.json"
cli deployment delete echo-production --expected-generation "$GENERATION" >"$RESULTS/deleted.json"

stop_node
python3 - "$LSF_QUICKSTART_DIR/node/status.jsonl" <<'PY'
import json, sys
with open(sys.argv[1], "rb") as source:
    raw = source.read(65537)
if len(raw) > 65536:
    raise SystemExit("Node status output exceeded its bound.")
records = [json.loads(line) for line in raw.splitlines()]
assert records[-1]["event"] == "stopped" and records[-1]["clean"] is True
print("One echo activation completed and the node reported clean shutdown.")
PY
printf 'Private working directory: %s\n' "$LSF_QUICKSTART_DIR"
```

The result files use the [operator CLI schema](../reference/operator-cli.md).
The invocation ID is known before dispatch and can be queried or explicitly
cancelled from a second process. This sequence does not retry mutations. If a
response is lost, use the known release digest, deployment ID, or activation ID
to inspect current state before deciding on another operation.

To restart, reuse the same private node configuration. Port zero can select a
different endpoint, so refresh the client profile from the new startup record.
The published release remains durable; this script deliberately deletes its
deployment. Activation history and the resident prepared cache do not persist
across restart. Optional authenticated native caching is a separate node setting.
The finite run demonstrates this workflow and its reported cleanup; it is not
the scale, soak, or completion evidence required by Phase 1 issue #16.

## Bounded Phase 2 operator workflow

Run this Linux Bash sequence from the repository root with Python 3.13, the
pinned toolchain, Docker and OpenSSL available. It builds the current CLI and
node before exporting fresh test evidence. The runner does not build binaries
or pull an image implicitly. Use the pinned registry image selected by the
maintained fixture runner, then let that runner own the disposable authenticated
TLS registry and its cleanup:

```bash
set -euo pipefail
umask 077
export CARGO_TARGET_DIR="$PWD/target"
cargo build -p latent -p latentd --all-features --locked
REGISTRY_IMAGE=$(python3 -c 'from tools.run_oci_registry_tests import IMAGE; print(IMAGE)')
docker pull "$REGISTRY_IMAGE"

# The exporter requires a new child directory; it never overwrites old evidence.
FIXTURE_PARENT=$(mktemp -d "${TMPDIR:-/tmp}/latent-operator-fixture.XXXXXXXX")
LSF_OPERATOR_FIXTURE_ROOT="$FIXTURE_PARENT/inputs" \
  cargo test -p latent-policy --lib --all-features --locked \
  export_operator_workflow_fixture -- --ignored --test-threads=1
python3 -m unittest tools.tests.test_phase2_operator_workflow \
  tools.tests.test_phase2_operator_canary
python3 tools/run_phase2_operator_workflow.py \
  --cli "$CARGO_TARGET_DIR/debug/latent" \
  --node "$CARGO_TARGET_DIR/debug/latentd" \
  --fixture-root "$FIXTURE_PARENT/inputs"
```

Run the workflow immediately after exporting. The exporter generates publisher
and independent builder keys in memory, emits public policy and short-lived
signed test evidence, and exports no private signing key. An expired fixture is
rejected; create a fresh directory and export again instead of changing its
timestamps. The original fixture remains available in `FIXTURE_PARENT` for
inspection; the runner removes its own separate client, node and registry output.

The runner checks exact deterministic package rebuilds, inspect results, TLS
push/pull and detached evidence, explicit local policy verification and denied
credentials. Actual CLI processes then publish both packages to an enforced node,
apply a deployment, reconcile exact replay, invoke the component, change manual
stages, reject a no-data canary promotion, observe attributed successful calls,
promote healthy traffic and restore the retained rollback target. It also checks
audit pagination, explicit operation lookup after a short mutation deadline,
restart and clean shutdown. It does not retry a mutation or add invocations until
a canary happens to pass. Candidate manifests are explicit copies with the
first-stage route weight, and invocation transport timeouts fit the node ceiling.

The command has a finite workflow deadline and fixed fixture populations;
retained child ownership and separate cleanup deadlines cover interruption.
Its result uses `latent.operator.workflow-test.v1`. Successful execution establishes
this bounded integration schedule only. The signed build observation is synthetic
test data, not evidence of a real production build. Actual observed-build tests
and historical Phase 1 measurements retain their separate purposes. The
[Phase 2 completion review](../phase-2-completion.md) combines the relevant
evidence and records its limitations; Phase 3 providers remain planned.

For an already owned matching loopback TLS fixture, supply both
`--registry-origin https://127.0.0.1:PORT` and `--registry-ca /absolute/ca.der`.
It must use the maintained fixture's credentials and OCI behavior; the runner
does not acquire or clean up an externally supplied registry. See
[operator workflows](../phase-2-operator-workflows.md),
[management services](../reference/management-services.md) and
[validation](../../VALIDATION.md#phase-2-focused-validation) for the underlying
contracts and focused tests.
