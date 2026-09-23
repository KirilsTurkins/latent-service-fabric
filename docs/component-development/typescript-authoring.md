# Create your own TypeScript capsule

Create an independent TypeScript project, edit its typed contract, and run its signed
package on a local node. Your application lives outside the LSF checkout and
uses a pinned copy of the maintained guest SDK.

Use Linux x86-64, Python 3.13.5, Node 24.19.0, Rust 1.97.1 and
wasm-tools 1.254.0. The reviewed compiler lock pins TypeScript 7.0.2,
jco 1.34.0, ComponentizeJS 0.22.0 and esbuild 0.28.2. Node is a build tool,
never a process owned by a deployed capsule. From the LSF checkout:

```sh
python3 -m pip install -r tools/requirements.lock
cargo install --locked wasm-tools --version 1.254.0
export LSF_TYPESCRIPT_TOOLS="$PWD/target/typescript-guest-tools"
python3 tools/typescript_capsule.py install-tools "$LSF_TYPESCRIPT_TOOLS"
cargo --config .cargo/managed-guest.toml build --locked -p latent -p latentd --bins \
  -p latent-packaging --example package --example capsule_contracts \
  -p latent-policy --example capsule_authoring
```

The installer requires a fresh output directory and uses the complete npm lock
without lifecycle scripts. Keep `LSF_TYPESCRIPT_TOOLS` set when reusing an
installation. The opt-in host build configuration optimizes compiler libraries;
it does not remove host assertions or change guest containment.

Run the following six Bash blocks in one terminal.

## 1. Create a project

```bash
set -euo pipefail
umask 077
LSF_CHECKOUT=$PWD
BIN="${CARGO_TARGET_DIR:-$PWD/target}/debug"
export LSF_TYPESCRIPT_PROJECTS="${LSF_TYPESCRIPT_PROJECTS:-$(mktemp -d "${TMPDIR:-/tmp}/lsf-typescript-projects.XXXXXXXX")}"
python3 tools/typescript_capsule.py new "$LSF_TYPESCRIPT_PROJECTS/my-greeting" --template greeting
```

Open `my-greeting/src/main.ts` and `my-greeting/wit/world.wit`. They contain the
complete [greeting example](creating-a-capsule.md#1-a-greeting-capsule), including
its normal TypeScript function and generated component export. The TypeScript template preserves
the same contract and behavior. Its contract is:

```wit
greet: func(name: string) -> result<string, string>;
```

The generated project includes the authoritative WIT, generated-at-build bindings, a pinned
SDK under `vendor/lsf`, and `capsule-project.json`. Edit your `src` and `wit`
files and update the selected world in `capsule-project.json` when renaming
the contract. Keep the SDK files unchanged. The build rejects SDK drift,
path escapes and unsupported contract shapes. Add relative TypeScript modules
inside the project. A JavaScript module also needs matching `.d.ts` declarations
for strict typechecking; untyped JavaScript imports are rejected. The bundler accepts only captured relative imports
or the exact versioned interfaces declared by your WIT. Arbitrary npm packages,
dynamic imports, `require`, Node built-ins, and application compiler/config
overrides are rejected. Vendoring an ordinary source module is supported; its
bytes become part of the source snapshot.

The `word-count` and `shipping` templates provide equivalent TypeScript implementations
of [Creating a capsule](creating-a-capsule.md). Choose another project directory
and replace `greeting` in the creation command with either template name.
`http-status` adds a typed, asynchronous HTTP call; its import still needs an
installed provider and an explicit deployment grant. Creating a project grants
no network access.

## 2. Build and package the project

```bash
python3 tools/typescript_capsule.py build "$LSF_TYPESCRIPT_PROJECTS/my-greeting" \
  --tools "$LSF_TYPESCRIPT_TOOLS" \
  --output "$LSF_TYPESCRIPT_PROJECTS/greeting-build" \
  --contracts-tool "$BIN/examples/capsule_contracts" \
  --packager "$BIN/examples/package" \
  --repository https://github.com/KirilsTurkins/latent-service-fabric
```

Use your own public repository URL for an application you maintain. That label
does not authenticate its source. The builder captures the actual project
files, derives contracts from WIT, checks generated SDK bindings, builds the
component, and inspects the package. `BUILD-COMPLETE.json` appears only after all
steps succeed. Use a fresh output directory for each new attempt.

The output includes `component.wasm`, `capsule.json`, `contracts.json`,
`wit-lock.json`, `deployment.json`, `package/` and `build-observation.json`.
Full-width WIT integers retain their original types; application errors remain
`result` values. Unsupported WIT types fail explicitly during contract derivation.
Public RPC parameters/results cannot transfer owned or borrowed resource values,
even inside records or lists. Blob and streaming capability imports keep their
declared resource ownership; close those owners within the activation.

## 3. Sign for this local experiment

The following signer creates short-lived publisher and builder keys in memory,
signs this exact build, and writes a policy for a new isolated node. It also
adds an inventory of the package's component and WIT inputs. It does not assert
a complete transitive dependency inventory. The keys never enter the compiler.

```bash
"$BIN/examples/capsule_authoring" demo-sign "$LSF_TYPESCRIPT_PROJECTS/releases" \
  "$LSF_TYPESCRIPT_PROJECTS/greeting-build"
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
mkdir "$LSF_TYPESCRIPT_PROJECTS/node" "$LSF_TYPESCRIPT_PROJECTS/results"
python3 - <<'PY'
import json, os, secrets, shutil
from pathlib import Path
root = Path(os.environ["LSF_TYPESCRIPT_PROJECTS"])
shutil.copyfile(root / "releases/policy.json", root / "node/policy.json")
token = secrets.token_urlsafe(32)
node = {
    "formatVersion": 1, "nodeId": "typescript-learning-node", "dataDirectory": "data",
    "bind": "127.0.0.1:0", "securityProfile": "local-experimental-v1",
    "supplyChain": {"mode": "enforced", "policyFile": "policy.json", "clockLeaseSeconds": 5},
    "workers": {"runtime": 1, "control": 1},
    "cells": [{"class": "standard", "capacity": 1, "queueCapacity": 2,
               "maximumMemoryBytes": 134217728}],
    "execution": {"maximumCpuFuel": 1000000000, "maximumWallTimeMillis": 120000},
    "cache": {"entries": 2, "preparations": 1},
    "credentials": [{"token": token, "subject": "typescript-learner", "tenant": "examples", "role": "operator"}],
}
with (root / "node/node.json").open("x") as output:
    json.dump(node, output)
PY
"$BIN/latentd" check-config --config "$LSF_TYPESCRIPT_PROJECTS/node/node.json"
"$BIN/latentd" serve --config "$LSF_TYPESCRIPT_PROJECTS/node/node.json" \
  >"$LSF_TYPESCRIPT_PROJECTS/node/status.jsonl" 2>"$LSF_TYPESCRIPT_PROJECTS/node/diagnostics.jsonl" &
TYPESCRIPT_NODE_PID=$!
stop_typescript_node() {
    if [[ -n "$TYPESCRIPT_NODE_PID" ]]; then
        local pid=$TYPESCRIPT_NODE_PID result=0
        TYPESCRIPT_NODE_PID=
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
trap 'stop_typescript_node >/dev/null 2>&1 || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
python3 - <<'PY'
import json, os, time
from pathlib import Path
root = Path(os.environ["LSF_TYPESCRIPT_PROJECTS"])
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
    "connectTimeoutMillis": 1000, "rpcTimeoutMillis": 125000,
}]}
with (root / "client.json").open("x") as output:
    json.dump(client, output)
PY
typescript_cli() { "$BIN/latent" --config "$LSF_TYPESCRIPT_PROJECTS/client.json" --output json "$@"; }
typescript_cli node get typescript-learning-node >"$LSF_TYPESCRIPT_PROJECTS/results/node.json"
```

## 5. Publish, deploy and invoke

Publishing returns an exact publication identity. Put that identity into the
generated deployment before applying it:

```bash
typescript_cli release publish-package "$LSF_TYPESCRIPT_PROJECTS/releases/my-greeting/package" \
  --evidence "$LSF_TYPESCRIPT_PROJECTS/releases/my-greeting/evidence/index.json" \
  --operation-id publish-my-greeting --expected-generation 0 \
  >"$LSF_TYPESCRIPT_PROJECTS/results/published.json"
python3 - <<'PY'
import json, os
from pathlib import Path
root = Path(os.environ["LSF_TYPESCRIPT_PROJECTS"])
deployment = json.loads((root / "releases/my-greeting/deployment.json").read_text())
published = json.loads((root / "results/published.json").read_text())
deployment["spec"]["publication"] = published["data"]["operation"]["publication"]["id"]
with (root / "results/deployment.json").open("x") as output:
    json.dump(deployment, output)
PY
typescript_cli deployment apply "$LSF_TYPESCRIPT_PROJECTS/results/deployment.json" --expected-generation 0 \
  >"$LSF_TYPESCRIPT_PROJECTS/results/deployed.json"
printf '["Ada"]\n' >"$LSF_TYPESCRIPT_PROJECTS/results/input.json"
typescript_cli invoke --memory-bytes 134217728 --cpu-fuel 1000000000 --wall-time-ms 120000 \
  --service examples/my-greeting --route my-greeting \
  --contract examples:greeting/api@1.0.0 --function greet --activation-id my-greeting-valid \
  --input "$LSF_TYPESCRIPT_PROJECTS/results/input.json" >"$LSF_TYPESCRIPT_PROJECTS/results/answer.json"
typescript_answer() {
    python3 - "$1" <<'PY'
import base64, json, sys
data = json.load(open(sys.argv[1]))["data"]
payload = data.get("payload") or data["declaredError"]["payload"]
print(base64.b64decode(payload["data"]).decode())
PY
}
typescript_answer "$LSF_TYPESCRIPT_PROJECTS/results/answer.json"
printf '[""]\n' >"$LSF_TYPESCRIPT_PROJECTS/results/empty.json"
typescript_cli invoke --memory-bytes 134217728 --cpu-fuel 1000000000 --wall-time-ms 120000 \
  --service examples/my-greeting --route my-greeting \
  --contract examples:greeting/api@1.0.0 --function greet --activation-id my-greeting-invalid \
  --input "$LSF_TYPESCRIPT_PROJECTS/results/empty.json" >"$LSF_TYPESCRIPT_PROJECTS/results/error.json" || test "$?" -eq 3
typescript_answer "$LSF_TYPESCRIPT_PROJECTS/results/error.json"
```

Expected answers are `[{"ok":"Hello, Ada!"}]` and
`[{"err":"Please enter a name."}]`. Exit code 3 is a declared application
error. Connection failures, exhausted budgets and guest traps have different
outcomes. Use a new activation ID for a new request; an uncertain mutation must
be inspected before any retry.

## 6. Clean up and continue

```bash
GENERATION=$(python3 -c 'import json,os; print(json.load(open(os.environ["LSF_TYPESCRIPT_PROJECTS"]+"/results/deployed.json"))["data"]["deployment"]["generation"])')
typescript_cli deployment delete my-greeting --expected-generation "$GENERATION"
stop_typescript_node
printf 'Saved project and results: %s\n' "$LSF_TYPESCRIPT_PROJECTS"
```

Your source and results remain at that path. Edit the greeting, create a new
build directory, and repeat signing and delivery to try a change. See
[delivery and recovery](../learn/deliver-and-recover-a-capsule.md) for updates.

For capabilities, use the [guest SDK reference](guest-sdk.md). It covers buffered
and streaming HTTP, blobs, secrets, events, local calls, randomness and metrics,
including each wrapper's close/drop rules. The generated WIT imports and
`vendor/lsf/sdk/typescript-guest/capabilities` wrappers use `bigint` for
64-bit integers, typed result cases, explicit `close()`/consuming methods and
`Scope.close()` in `finally`. Resource aliases share the same live state;
garbage collection is not a substitute for closing host resources.
An imported effect is allowed only
by host policy. Pending calls retain their budget until the host releases them;
cancelling a subtask never proves an external effect did not occur.

If a build fails, inspect `BUILD-FAILED.json` and `logs/` in that attempt's output.
SDK binding drift means the SDK and generator pins disagree; do not edit the lock
to bypass it. A denied publication commonly means the policy expired, the exact
source approval differs, or an evidence file is missing. A denied HTTP call
requires checking the deployment grant, provider binding and allowed destination.


## Execution boundaries

The guest runs in an activation-owned SpiderMonkey heap in WebAssembly. It is
not Node, a browser, or an application-owned JavaScript event loop. There is no
ambient filesystem, process, clock, entropy, network, timer, worker or DOM API.
Use a declared, configured LSF import for every host effect.

The compiler generates a synchronous JavaScript calling convention, then the
builder restores the original typed async WIT metadata. Wasmtime suspends the
activation's stack across host calls. Application exports and imported wrapper
methods return ordinary values, not promises; never return a pending
`Promise` as a contract value. Host cancellation destroys the activation,
including its stack, pending host future and guest heap. It does not establish
whether an external effect occurred.

WIT `future`, `stream`, `map` and fixed-size-list values are rejected before
compilation. Streaming HTTP uses the current explicit resource/chunk API,
not WIT stream values. Named/free-standing imports and generated interface
filename collisions are rejected explicitly. WIT integer widths, results,
records, lists and canonical resource ownership are not rewritten.

The shared node retains bounded compiled images, not initialized guest heaps.
The embedded engine makes these components larger and colder to compile than
the Rust/C examples. This explicit local profile allows 128 MiB per activation
and a 120-second deadline including cold preparation; warm calls need much less.
An invocation may request a shorter deadline, including during a suspended host
call. These example settings do not change any production node default.
See the source-matched qualification receipt for measured
build, compilation, invocation, memory, cache and cleanup costs; these
correctness experiments are not throughput or production-sizing claims.
