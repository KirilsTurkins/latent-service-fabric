# Create your own C capsule

Create an independent C project, edit its typed contract, and run its signed
package on a local node. Your application lives outside the LSF checkout and
uses a pinned copy of the maintained guest SDK.

Use Linux, Python 3.13.5, Zig 0.16.0, Rust 1.97.1 for the host tools,
wasm-tools 1.254.0 and wit-bindgen-cli
0.62.0. Follow the [toolchain setup](../development/toolchain.md), install
`tools/requirements.lock` in your Python environment, and run these commands
from the LSF repository root. The build tools are compiled once:

```sh
python3 tools/install_guest_bindgen.py "$PWD/target/guest-tools"
export PATH="$PWD/target/guest-tools:$PATH"
cargo build --locked -p latent -p latentd --bins \
  -p latent-packaging --example package --example capsule_contracts \
  -p latent-policy --example capsule_authoring
```

The binding installer needs a fresh output path. If it is already installed,
keep that directory on `PATH`. Run the following Bash blocks in one terminal.

## 1. Create a project

```bash
set -euo pipefail
umask 077
LSF_CHECKOUT=$PWD
BIN="${CARGO_TARGET_DIR:-$PWD/target}/debug"
export LSF_C_PROJECTS="${LSF_C_PROJECTS:-$(mktemp -d "${TMPDIR:-/tmp}/lsf-c-projects.XXXXXXXX")}"
python3 tools/c_capsule.py new "$LSF_C_PROJECTS/my-greeting" --template greeting
```

Open `my-greeting/src/main.c` and `my-greeting/wit/world.wit`. They contain the
complete [greeting example](creating-a-capsule.md#1-a-greeting-capsule), including
its normal C function and generated component export. The C template preserves
the same contract and behavior. Its contract is:

```wit
greet: func(name: string) -> result<string, string>;
```

The generated project includes the authoritative WIT, generated-at-build bindings, a pinned
SDK under `vendor/lsf`, and `capsule-project.json`. Edit your `src` and `wit`
files and update the selected world in `capsule-project.json` when renaming
the contract. Keep the SDK files unchanged. The build rejects SDK drift,
path escapes and unsupported contract shapes. Put additional C sources and
headers in `src`; the build compiles the captured `.c` files with no external
library search paths. Includes relative to an application's source file work
normally. Absolute includes are outside this supported captured-source recipe.

The `word-count` and `shipping` templates provide equivalent C implementations
of [Creating a capsule](creating-a-capsule.md). Choose another project directory
and replace `greeting` in the creation command with either template name.
`http-status` adds a typed, asynchronous HTTP call; its import still needs an
installed provider and an explicit deployment grant. Creating a project grants
no network access.

## 2. Build and package the project

```bash
python3 tools/c_capsule.py build "$LSF_C_PROJECTS/my-greeting" \
  --output "$LSF_C_PROJECTS/greeting-build" \
  --contracts-tool "$BIN/examples/capsule_contracts" \
  --packager "$BIN/examples/package" \
  --repository https://github.com/KirilsTurkins/latent-service-fabric
```

Use your own public repository URL for an application you maintain. That label
does not authenticate its source. The builder captures the actual project
files, checks generated SDK bindings, builds the component, derives contracts
from WIT, and inspects the package. `BUILD-COMPLETE.json` appears only after all
steps succeed. Use a fresh output directory for each new attempt.

The output includes `component.wasm`, `capsule.json`, `contracts.json`,
`wit-lock.json`, `deployment.json`, `package/` and `build-observation.json`.
Full-width WIT integers retain their original types; application errors remain
`result` values. Unsupported WIT types fail explicitly during contract derivation.

## 3. Sign for this local experiment

The following signer creates short-lived publisher and builder keys in memory,
signs this exact build, and writes a policy for a new isolated node. It also
adds an inventory of the package's component and WIT inputs. It does not assert
a complete transitive dependency inventory. The keys never enter the compiler.

```bash
"$BIN/examples/capsule_authoring" demo-sign "$LSF_C_PROJECTS/releases" \
  "$LSF_C_PROJECTS/greeting-build"
```

This policy lasts for this experiment and accepts only the captured source and
builder recipe. For a maintained deployment, use your organization's publisher,
builder and revocation policies through the [package workflow](packaging.md).
Finish the steps below within 30 minutes of signing; otherwise sign into a new
directory and start a new experiment.

## 4. Start a node with enforced admission

This node listens on an automatically selected loopback port. Its random client
credential stays in private files. It verifies both package signatures and the
builder policy before admitting a release.

```bash
mkdir "$LSF_C_PROJECTS/node" "$LSF_C_PROJECTS/results"
python3 - <<'PY'
import json, os, secrets, shutil
from pathlib import Path
root = Path(os.environ["LSF_C_PROJECTS"])
shutil.copyfile(root / "releases/policy.json", root / "node/policy.json")
token = secrets.token_urlsafe(32)
node = {
    "formatVersion": 1, "nodeId": "c-learning-node", "dataDirectory": "data",
    "bind": "127.0.0.1:0", "securityProfile": "local-experimental-v1",
    "supplyChain": {"mode": "enforced", "policyFile": "policy.json", "clockLeaseSeconds": 5},
    "execution": {"maximumWallTimeMillis": 5000},
    "credentials": [{"token": token, "subject": "c-learner", "tenant": "examples", "role": "operator"}],
}
with (root / "node/node.json").open("x") as output:
    json.dump(node, output)
PY
"$BIN/latentd" check-config --config "$LSF_C_PROJECTS/node/node.json"
"$BIN/latentd" serve --config "$LSF_C_PROJECTS/node/node.json" \
  >"$LSF_C_PROJECTS/node/status.jsonl" 2>"$LSF_C_PROJECTS/node/diagnostics.jsonl" &
C_NODE_PID=$!
stop_c_node() {
    if [[ -n "$C_NODE_PID" ]]; then
        local pid=$C_NODE_PID result=0
        C_NODE_PID=
        kill -TERM "$pid" 2>/dev/null || true
        for ((attempt=0; attempt<100; attempt++)); do
            if ! kill -0 "$pid" 2>/dev/null; then break; fi
            sleep 0.05
        done
        if kill -0 "$pid" 2>/dev/null; then kill -KILL "$pid" 2>/dev/null || true; result=1; fi
        wait "$pid" || result=1
        return "$result"
    fi
}
trap 'stop_c_node >/dev/null 2>&1 || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
python3 - <<'PY'
import json, os, time
from pathlib import Path
root = Path(os.environ["LSF_C_PROJECTS"])
deadline = time.monotonic() + 30
while True:
    lines = (root / "node/status.jsonl").read_text().splitlines()
    if lines:
        endpoint = json.loads(lines[0])["endpoint"]
        break
    if time.monotonic() >= deadline:
        raise SystemExit("Node did not start; inspect node/diagnostics.jsonl")
    time.sleep(0.05)
token = json.loads((root / "node/node.json").read_text())["credentials"][0]["token"]
client = {"formatVersion": 1, "defaultProfile": "local", "profiles": [{
    "name": "local", "endpoint": "http://" + endpoint, "tenant": "examples", "token": token,
    "connectTimeoutMillis": 1000, "rpcTimeoutMillis": 5000,
}]}
with (root / "client.json").open("x") as output:
    json.dump(client, output)
PY
c_cli() { "$BIN/latent" --config "$LSF_C_PROJECTS/client.json" --output json "$@"; }
c_cli node get c-learning-node >"$LSF_C_PROJECTS/results/node.json"
```

## 5. Publish, deploy and invoke

Publishing returns an exact publication identity. Put that identity into the
generated deployment before applying it:

```bash
c_cli release publish-package "$LSF_C_PROJECTS/releases/my-greeting/package" \
  --evidence "$LSF_C_PROJECTS/releases/my-greeting/evidence/index.json" \
  --operation-id publish-my-greeting --expected-generation 0 \
  >"$LSF_C_PROJECTS/results/published.json"
python3 - <<'PY'
import json, os
from pathlib import Path
root = Path(os.environ["LSF_C_PROJECTS"])
deployment = json.loads((root / "releases/my-greeting/deployment.json").read_text())
published = json.loads((root / "results/published.json").read_text())
deployment["spec"]["publication"] = published["data"]["operation"]["publication"]["id"]
with (root / "results/deployment.json").open("x") as output:
    json.dump(deployment, output)
PY
c_cli deployment apply "$LSF_C_PROJECTS/results/deployment.json" --expected-generation 0 \
  >"$LSF_C_PROJECTS/results/deployed.json"
printf '["Ada"]\n' >"$LSF_C_PROJECTS/results/input.json"
c_cli invoke --service examples/my-greeting --route my-greeting \
  --contract examples:greeting/api@1.0.0 --function greet --activation-id my-greeting-valid \
  --input "$LSF_C_PROJECTS/results/input.json" >"$LSF_C_PROJECTS/results/answer.json"
c_answer() {
    python3 - "$1" <<'PY'
import base64, json, sys
data = json.load(open(sys.argv[1]))["data"]
payload = data.get("payload") or data["declaredError"]["payload"]
print(base64.b64decode(payload["data"]).decode())
PY
}
c_answer "$LSF_C_PROJECTS/results/answer.json"
printf '[""]\n' >"$LSF_C_PROJECTS/results/empty.json"
c_cli invoke --service examples/my-greeting --route my-greeting \
  --contract examples:greeting/api@1.0.0 --function greet --activation-id my-greeting-invalid \
  --input "$LSF_C_PROJECTS/results/empty.json" >"$LSF_C_PROJECTS/results/error.json" || test "$?" -eq 3
c_answer "$LSF_C_PROJECTS/results/error.json"
```

Expected answers are `[{"ok":"Hello, Ada!"}]` and
`[{"err":"Please enter a name."}]`. Exit code 3 is a declared application
error. Connection failures, exhausted budgets and guest traps have different
outcomes. Use a new activation ID for a new request; an uncertain mutation must
be inspected before any retry.

## 6. Clean up and continue

```bash
GENERATION=$(python3 -c 'import json,os; print(json.load(open(os.environ["LSF_C_PROJECTS"]+"/results/deployed.json"))["data"]["deployment"]["generation"])')
c_cli deployment delete my-greeting --expected-generation "$GENERATION"
stop_c_node
printf 'Saved project and results: %s\n' "$LSF_C_PROJECTS"
```

Your source and results remain at that path. Edit the greeting, create a new
build directory, and repeat signing and delivery to try a change. The
[delivery and recovery](../learn/deliver-and-recover-a-capsule.md) guide explains
update and recovery principles using a separate Rust tutorial project and node.
Follow that tutorial's prerequisites and variables when using its commands;
for this project, retain the build, signing and admission path above.

For capabilities, use the [guest SDK reference](guest-sdk.md). It covers buffered
and streaming HTTP, blobs, secrets, events, local calls, randomness and metrics,
including each wrapper's close/drop rules. The C headers in
`vendor/lsf/sdk/c-guest/include/lsf` provide explicit scopes, buffer owners and
canonical async task frames. An imported effect is allowed only
by host policy. Pending calls retain their budget until the host releases them;
cancelling a subtask never proves an external effect did not occur.

If a build fails, inspect `BUILD-FAILED.json` and `logs/` in that attempt's output.
SDK binding drift means the SDK and generator pins disagree; do not edit the lock
to bypass it. A denied publication commonly means the policy expired, the exact
source approval differs, or an evidence file is missing. A denied HTTP call
requires checking the deployment grant, provider binding and allowed destination.
