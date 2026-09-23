# Run your first node

Create a local LSF node and give it a small program to run. By the end, you will
send `hello` to an echo capsule, receive `hello`, and restart the node without
losing the deployment. Later tutorials use this same node for your own capsules.

Run the Bash blocks in order, in **one terminal**. Keep it open while you work;
it holds the paths and helper functions used by later steps.

## 1. Get the source and build LSF

Use Linux with Git, Python 3.13.5, Rust 1.97.1 and wasm-tools 1.254.0 installed.
The [toolchain setup](../development/toolchain.md) describes those prerequisites.
You do not need Docker, Kubernetes or a cloud account. Windows users can use a
Linux environment such as WSL for these commands.

```bash
set -euo pipefail
umask 077
git clone --branch development https://github.com/KirilsTurkins/latent-service-fabric.git
cd latent-service-fabric
export CARGO_TARGET_DIR="$PWD/target"
python3 -m venv target/guide-venv
source target/guide-venv/bin/activate
python3 -m pip install -r tools/requirements.lock
rustup target add wasm32-unknown-unknown
cargo build --locked -p latent -p latentd
make echo-capsule
BIN="$CARGO_TARGET_DIR/debug"
```

`latentd` is the node. `latent` is the command-line client that manages it.
The last build creates the example program and its configuration in
`target/capsules/echo`. The first build can take several minutes.

## 2. Create your node

Choose a private directory for this experiment. The configuration below gives
this node the name `learning-node`, stores its data in that directory, and
listens only on your machine at port 17840. If that port is already occupied,
choose another unused port before running the block.

```bash
export LSF_TUTORIAL_DIR
LSF_TUTORIAL_DIR=$(mktemp -d "${TMPDIR:-/tmp}/lsf-learning.XXXXXXXX")
export LSF_TUTORIAL_PORT=17840
mkdir "$LSF_TUTORIAL_DIR/node" "$LSF_TUTORIAL_DIR/client"
python3 - <<'PY'
import json, os, secrets
from pathlib import Path
root = Path(os.environ["LSF_TUTORIAL_DIR"])
port = int(os.environ["LSF_TUTORIAL_PORT"])
assert 1024 <= port <= 65535
token = secrets.token_urlsafe(32)
node = {
    "formatVersion": 1, "nodeId": "learning-node",
    "dataDirectory": "data", "bind": f"127.0.0.1:{port}",
    "securityProfile": "local-experimental-v1",
    "supplyChain": {"mode": "trusted-local"},
    "execution": {"maximumWallTimeMillis": 5000},
    "credentials": [{"token": token, "subject": "learning-operator",
                     "tenant": "examples", "role": "operator"}],
}
client = {"formatVersion": 1, "defaultProfile": "local", "profiles": [{
    "name": "local", "endpoint": f"http://127.0.0.1:{port}",
    "tenant": "examples", "token": token,
    "connectTimeoutMillis": 1000, "rpcTimeoutMillis": 5000,
}]}
for name, value in [("node/node.json", node), ("client/client.json", client)]:
    with (root / name).open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2)
        output.write("\n")
print("Created node and client configuration.")
PY
"$BIN/latentd" check-config --config "$LSF_TUTORIAL_DIR/node/node.json"
```

The script creates a random password shared by the node and your client, and
writes it to private files. You do not need to copy or print the password.
The local profile lets you run capsules you build yourself. Use the
[installation guide](../installation.md) when you need a persistent server with
its own trust policy.

## 3. Start the node and check it

The following helpers start this node in the background and stop it when you
close the terminal. `cli` saves you from typing the client configuration path
for every command.

```bash
NODE_PID=
start_node() {
    "$BIN/latentd" serve --config "$LSF_TUTORIAL_DIR/node/node.json" \
      >"$LSF_TUTORIAL_DIR/node/status.jsonl" \
      2>"$LSF_TUTORIAL_DIR/node/diagnostic.jsonl" &
    NODE_PID=$!
}
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
cli() { "$BIN/latent" --config "$LSF_TUTORIAL_DIR/client/client.json" --output json "$@"; }
ready() {
    for ((attempt=0; attempt<20; attempt++)); do
        if cli node get learning-node >"$LSF_TUTORIAL_DIR/client/node.json"; then
            python3 - "$LSF_TUTORIAL_DIR/client/node.json" <<'PY'
import json, sys
node = json.load(open(sys.argv[1]))["data"]["inventory"]
assert node["health"]["ready"], "Node is not ready; inspect its diagnostics."
print("Your node is ready.")
PY
            return
        fi
        if ! kill -0 "$NODE_PID" 2>/dev/null; then return 1; fi
        sleep 0.1
    done
    return 1
}
start_node
ready
```

Wait for **Your node is ready.** A connection error during the first moment of
startup is harmless if the next attempt succeeds. If the node exits, inspect
`$LSF_TUTORIAL_DIR/node/diagnostic.jsonl`. An occupied port, incorrect file
permissions or an unsupported host must be fixed before you continue.

## 4. Upload the echo capsule

Publishing uploads the program to your node. It does not start a permanent
process for that program. Save the returned publication so the next step can
select exactly the capsule you uploaded.

```bash
PACKAGE="$CARGO_TARGET_DIR/capsules/echo"
RESULTS="$LSF_TUTORIAL_DIR/client"
field() {
    python3 - "$@" <<'PY'
import json, sys
value = json.load(open(sys.argv[1]))
for key in sys.argv[2:]:
    value = value[key]
print(value)
PY
}
cli release publish --manifest "$PACKAGE/capsule.json" \
    --component "$PACKAGE/echo-capsule.wasm" --contracts "$PACKAGE/contracts.json" \
    >"$RESULTS/echo-published.json"
PUBLICATION=$(field "$RESULTS/echo-published.json" data release publication id)
DIGEST=$(field "$RESULTS/echo-published.json" data release digest)
```

## 5. Deploy the capsule

A deployment connects the service name `examples/echo` to your publication.
The small Python block fills in the generated deployment file for you; there
are no identifiers to copy by hand.

```bash
python3 - "$PACKAGE/deployment.json" "$RESULTS/echo-deployment.json" "$DIGEST" "$PUBLICATION" <<'PY'
import json, sys
value = json.load(open(sys.argv[1]))
value["spec"]["release"] = sys.argv[3]
value["spec"]["publication"] = sys.argv[4]
with open(sys.argv[2], "x") as output:
    json.dump(value, output)
PY
cli deployment apply "$RESULTS/echo-deployment.json" --expected-generation 0 \
    >"$RESULTS/echo-applied.json"
GENERATION=$(field "$RESULTS/echo-applied.json" data deployment generation)
```

`--expected-generation 0` means “create a new deployment”. It prevents this
walkthrough from accidentally replacing an existing deployment.

## 6. Call the capsule

The input is a JSON array containing the function's arguments. Write one
string, invoke `echo`, then decode the returned value:

```bash
printf '["hello"]\n' >"$RESULTS/input.json"
cli invoke --service examples/echo --contract examples:echo/api@0.1.0 \
    --function echo --activation-id learning-echo --input "$RESULTS/input.json" \
    >"$RESULTS/answer.json"
answer() {
    python3 - "$1" <<'PY'
import base64, json, sys
reply = json.load(open(sys.argv[1]))
data = reply["data"]
payload = data.get("payload") or data["declaredError"]["payload"]
print(base64.b64decode(payload["data"]).decode())
PY
}
answer "$RESULTS/answer.json"
```

Expected answer:

```json
[{"ok":"hello"}]
```

You have now sent work to a capsule and received its result. Change `hello` to
another message and use a new `--activation-id` to make another call.

Try an empty string to see an application error:

```bash
printf '[""]\n' >"$RESULTS/empty.json"
cli invoke --service examples/echo --contract examples:echo/api@0.1.0 \
    --function echo --activation-id learning-empty --input "$RESULTS/empty.json" \
    >"$RESULTS/empty-answer.json" || test "$?" -eq 3
answer "$RESULTS/empty-answer.json"
```

The command accepts exit code 3, which means the capsule reported an application
error. The decoded answer contains `err` and `empty-message`. That is the capsule
explaining why it cannot process your input. It is different from failing to
connect to the node.

## 7. Restart and call the saved deployment

```bash
stop_node
start_node
ready
cli invoke --service examples/echo --contract examples:echo/api@0.1.0 \
    --function echo --activation-id learning-after-restart --input "$RESULTS/input.json" \
    >"$RESULTS/restarted-answer.json"
answer "$RESULTS/restarted-answer.json"
```

You should receive `hello` again. The node saved your publication and deployment
in its data directory. You did not need to upload them again.

## 8. Continue or stop

Keep this terminal open and the node running to follow
[Creating a capsule](../component-development/creating-a-capsule.md).
For the original echo's implementation, see
[Understand your first capsule](../learn/author-your-first-capsule.md).
To change a capsule and restore its previous version, continue with
[Update and restore a capsule](../learn/deliver-and-recover-a-capsule.md).

When you are finished, remove the tutorial deployment and stop this node:

```bash
cli deployment delete echo-production --expected-generation "$GENERATION"
stop_node
printf 'Saved tutorial files: %s\n' "$LSF_TUTORIAL_DIR"
```

Your private configuration and data remain at the printed path. Keep them if
you want to inspect the results. This only stops the node started by this
terminal and leaves other LSF nodes alone.
