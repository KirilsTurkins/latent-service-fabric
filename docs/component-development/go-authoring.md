# Create your own Go capsule

Create an independent Go project, edit its typed contract, and run its signed
package on a local node. Your application lives outside the LSF checkout and
uses a pinned copy of the maintained guest SDK.

The examples allow up to 120 seconds for a cold invocation, including component
compilation. Warm calls still start with fresh guest state. This is an explicit
example budget, not a change to the node's default execution limits.

Use Linux x86-64, Python 3.13.5, Rust 1.97.1 and the exact Go async toolchain
below. Stock Go and TinyGo are not substitutes for the maintained
`wasiOnIdle` compiler profile. These prerequisites install compiler tools only;
they do not start a guest or grant capabilities. Run from the LSF checkout:

```sh
GO_TOOLS=$(mktemp -d "${TMPDIR:-/tmp}/lsf-go-tools.XXXXXXXX")
curl --fail --location --max-time 180 \
  https://github.com/dicej/go/releases/download/go1.27.1-wasi-on-idle/go-linux-amd64-bootstrap.tbz \
  --output "$GO_TOOLS/go.tbz"
printf '%s  %s\n' 4b4fcbbab5b5b0a45433112aa51c64a54007b24f1efd05b67018ca2cf8633e2c "$GO_TOOLS/go.tbz" | sha256sum --check --strict
tar -xjf "$GO_TOOLS/go.tbz" -C "$GO_TOOLS"
export PATH="$GO_TOOLS/go-linux-amd64-bootstrap/bin:$PATH"
cargo install --git https://github.com/bytecodealliance/componentize-go \
  --rev 148dba505f8c6c64ad84db777cfde5e34e25098b --locked componentize-go
cargo install --locked wasm-tools --version 1.254.0
cargo --config .cargo/managed-guest.toml build --locked -p latent -p latentd --bins \
  -p latent-packaging --example package --example capsule_contracts \
  -p latent-policy --example capsule_authoring
```

Keep these exact compiler executables on `PATH`. Run the following six Bash
blocks in one terminal.

## 1. Create a project

```bash
set -euo pipefail
umask 077
LSF_CHECKOUT=$PWD
BIN="${CARGO_TARGET_DIR:-$PWD/target}/debug"
export LSF_GO_PROJECTS="${LSF_GO_PROJECTS:-$(mktemp -d "${TMPDIR:-/tmp}/lsf-go-projects.XXXXXXXX")}"
python3 tools/go_capsule.py new "$LSF_GO_PROJECTS/my-greeting" --template greeting
```

Open `my-greeting/src/main.go` and `my-greeting/wit/world.wit`. They contain the
complete [greeting example](creating-a-capsule.md#1-a-greeting-capsule), including
its ordinary Go function and generated component export. The Go template preserves
the same contract and behavior. Its contract is:

```wit
greet: func(name: string) -> result<string, string>;
```

The generated project includes the authoritative WIT, generated-at-build bindings, a pinned
SDK under `vendor/lsf`, and `capsule-project.json`. Edit your `src` and `wit`
files and update the selected world in `capsule-project.json` when renaming
the contract. Keep the SDK files unchanged. The build rejects SDK drift,
path escapes and unsupported contract shapes. Put additional `.go` sources in `src`, using the generated export package name
from your WIT. The supported build captures source, not arbitrary Go modules or
external include paths. The SDK's reviewed dependency graph is vendored and
checked; it does not silently download application dependencies.

The `word-count` and `shipping` templates provide equivalent Go implementations
of [Creating a capsule](creating-a-capsule.md). Choose another project directory
and replace `greeting` in the creation command with either template name.
`http-status` adds a typed, asynchronous HTTP call; its import still needs an
installed provider and an explicit deployment grant. Creating a project grants
no network access.

## 2. Build and package the project

```bash
python3 tools/go_capsule.py build "$LSF_GO_PROJECTS/my-greeting" \
  --output "$LSF_GO_PROJECTS/greeting-build" \
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
"$BIN/examples/capsule_authoring" demo-sign "$LSF_GO_PROJECTS/releases" \
  "$LSF_GO_PROJECTS/greeting-build"
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
mkdir "$LSF_GO_PROJECTS/node" "$LSF_GO_PROJECTS/results"
python3 - <<'PY'
import json, os, secrets, shutil
from pathlib import Path
root = Path(os.environ["LSF_GO_PROJECTS"])
shutil.copyfile(root / "releases/policy.json", root / "node/policy.json")
token = secrets.token_urlsafe(32)
node = {
    "formatVersion": 1, "nodeId": "go-learning-node", "dataDirectory": "data",
    "bind": "127.0.0.1:0", "securityProfile": "local-experimental-v1",
    "supplyChain": {"mode": "enforced", "policyFile": "policy.json", "clockLeaseSeconds": 5},
    "workers": {"runtime": 1, "control": 1},
    "cells": [{"class": "standard", "capacity": 1, "queueCapacity": 2, "maximumMemoryBytes": 67108864}],
    "execution": {"maximumCpuFuel": 1000000000, "maximumWallTimeMillis": 120000},
    "cache": {"entries": 2, "preparations": 1},
    "budgetProfile": {"mode": "phase3", "maximumOutboundRequests": 0,
                      "maximumBlobReadBytes": 0, "maximumBlobWriteBytes": 0},
    "capabilityPolicies": {"formatVersion": 1, "maximumControlJobs": 2},
    "audit": {"mode": "durable", "records": 1024, "diskBytes": 16777216,
              "queuedOperations": 8, "queryOwners": 2},
    "credentials": [{"token": token, "subject": "go-learner", "tenant": "examples", "role": "operator"}],
}
runtime_imports = {
    "clockMonotonic": "latent:clock/monotonic@0.1.0",
    "clockWall": "latent:clock/wall@0.1.0",
    "random": "latent:random/random@0.1.0",
}
node["providers"] = {"formatVersion": 1, "bindings": []}
for name, contract in runtime_imports.items():
    node["providers"][name] = {"identity": {
        "id": name, "tenant": "examples", "service": "runtime-host", "epoch": 1}}
    node["providers"]["bindings"].append({
        "name": name, "tenant": "examples", "consumerService": "examples/my-greeting",
        "providerService": "runtime-host", "contract": contract, "providerBinding": name + "-installed"})
with (root / "node/node.json").open("x") as output:
    json.dump(node, output)
PY
"$BIN/latentd" check-config --config "$LSF_GO_PROJECTS/node/node.json"
"$BIN/latentd" serve --config "$LSF_GO_PROJECTS/node/node.json" \
  >"$LSF_GO_PROJECTS/node/status.jsonl" 2>"$LSF_GO_PROJECTS/node/diagnostics.jsonl" &
GO_NODE_PID=$!
stop_go_node() {
    if [[ -n "$GO_NODE_PID" ]]; then
        local pid=$GO_NODE_PID result=0
        GO_NODE_PID=
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
trap 'stop_go_node >/dev/null 2>&1 || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
python3 - <<'PY'
import json, os, time
from pathlib import Path
root = Path(os.environ["LSF_GO_PROJECTS"])
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
go_cli() { "$BIN/latent" --config "$LSF_GO_PROJECTS/client.json" --output json "$@"; }
go_cli node get go-learning-node >"$LSF_GO_PROJECTS/results/node.json"
```

## 5. Publish, deploy and invoke

Publishing returns an exact publication identity. This Go runtime needs explicit
monotonic-clock, wall-clock and entropy grants even for a greeting. The next
block scopes each grant to this one publication, service, operation and caller.
There is no ambient WASI authority. Omitting a grant produces a platform denial
before the application can return. The guest's 64 MiB memory and fuel budgets
bound its runtime heap and goroutines; no guest can create a host thread.

```bash
go_cli release publish-package "$LSF_GO_PROJECTS/releases/my-greeting/package" \
  --evidence "$LSF_GO_PROJECTS/releases/my-greeting/evidence/index.json" \
  --operation-id publish-my-greeting --expected-generation 0 \
  >"$LSF_GO_PROJECTS/results/published.json"
python3 - <<'PY'
import json, os
from pathlib import Path
root = Path(os.environ["LSF_GO_PROJECTS"])
deployment = json.loads((root / "releases/my-greeting/deployment.json").read_text())
published = json.loads((root / "results/published.json").read_text())
publication = published["data"]["operation"]["publication"]["id"]
deployment["spec"]["publication"] = publication
deployment["spec"]["grants"] = []
startup = json.loads((root / "node/status.jsonl").read_text().splitlines()[0])
for provider in startup["providers"]:
    name, capability = provider["id"], provider["capability"]
    operation, kind = {
        "clockMonotonic": ("now-nanos", "clock"),
        "clockWall": ("now-unix-millis", "clock"),
        "random": ("u64-value", "random"),
    }[name]
    binding = {"formatVersion": 1, "tenant": "examples", "capability": capability,
        "providerProfile": provider["profile"], "configurationDigest": provider["configurationDigest"],
        "configurationEpoch": int(provider["configurationEpoch"]), "restriction": {"operations": [operation]}}
    policy = {"formatVersion": 1, "tenant": "examples", "rules": [{
        "id": "runtime", "effect": "allow", "principals": [{"kind": "administrator", "subject": "go-learner"}],
        "services": ["examples/my-greeting"], "publications": [publication], "capability": capability,
        "operations": [operation], "resources": {"kind": kind},
        "ceiling": {"operations": 4096, "inputBytes": 8 if kind == "random" else 0, "outputBytes": 32768, "wallTimeMillis": 5000}}]}
    for suffix, document in (("binding", binding), ("policy", policy)):
        with (root / "results" / (name + "-" + suffix + ".json")).open("x") as output:
            json.dump(document, output)
    deployment["spec"]["grants"].append({"capability": capability, "policy": name + "-allow"})
with (root / "results/deployment.json").open("x") as output:
    json.dump(deployment, output)
PY
for name in clockMonotonic clockWall random; do
    go_cli policy --kind provider-binding apply --id "$name-installed" \
      --file "$LSF_GO_PROJECTS/results/$name-binding.json" \
      --operation-id "install-$name" --expected-generation 0
    go_cli policy apply --id "$name-allow" --file "$LSF_GO_PROJECTS/results/$name-policy.json" \
      --operation-id "grant-$name" --expected-generation 0
done
go_cli deployment apply "$LSF_GO_PROJECTS/results/deployment.json" --expected-generation 0 \
  >"$LSF_GO_PROJECTS/results/deployed.json"
printf '["Ada"]\n' >"$LSF_GO_PROJECTS/results/input.json"
go_cli invoke --memory-bytes 67108864 --cpu-fuel 1000000000 --wall-time-ms 120000 \
  --service examples/my-greeting --route my-greeting \
  --contract examples:greeting/api@1.0.0 --function greet --activation-id my-greeting-valid \
  --input "$LSF_GO_PROJECTS/results/input.json" >"$LSF_GO_PROJECTS/results/answer.json"
go_answer() {
    python3 - "$1" <<'PY'
import base64, json, sys
data = json.load(open(sys.argv[1]))["data"]
payload = data.get("payload") or data["declaredError"]["payload"]
print(base64.b64decode(payload["data"]).decode())
PY
}
go_answer "$LSF_GO_PROJECTS/results/answer.json"
printf '[""]\n' >"$LSF_GO_PROJECTS/results/empty.json"
go_cli invoke --memory-bytes 67108864 --cpu-fuel 1000000000 --wall-time-ms 120000 \
  --service examples/my-greeting --route my-greeting \
  --contract examples:greeting/api@1.0.0 --function greet --activation-id my-greeting-invalid \
  --input "$LSF_GO_PROJECTS/results/empty.json" >"$LSF_GO_PROJECTS/results/error.json" || test "$?" -eq 3
go_answer "$LSF_GO_PROJECTS/results/error.json"
```

Expected answers are `[{"ok":"Hello, Ada!"}]` and
`[{"err":"Please enter a name."}]`. Exit code 3 is a declared application
error. Connection failures, exhausted budgets and guest traps have different
outcomes. Use a new activation ID for a new request; an uncertain mutation must
be inspected before any retry.

## 6. Clean up and continue

```bash
GENERATION=$(python3 -c 'import json,os; print(json.load(open(os.environ["LSF_GO_PROJECTS"]+"/results/deployed.json"))["data"]["deployment"]["generation"])')
go_cli deployment delete my-greeting --expected-generation "$GENERATION"
stop_go_node
printf 'Saved project and results: %s\n' "$LSF_GO_PROJECTS"
```

Your source and results remain at that path. Edit the greeting, create a new
build directory, and repeat signing and delivery to try a change. See
[delivery and recovery](../learn/deliver-and-recover-a-capsule.md) for updates.

For capabilities, use the [guest SDK reference](guest-sdk.md). It covers buffered
and streaming HTTP, blobs, secrets, events, local calls, randomness and metrics,
including each wrapper's close/drop rules. The [Go guest SDK](../../sdk/go-guest/README.md) supplies typed
`wit_component/lsf/*` packages over exact generated interfaces.
Use explicit `Close`, consuming operations and `defer` for owners; there is no
finalizer-driven resource release. Aliases share a single consumed/borrowed state. An imported effect is allowed only
by host policy. Pending calls retain their budget until the host releases them;
cancelling a subtask never proves an external effect did not occur.

If a build fails, inspect `BUILD-FAILED.json` and `logs/` in that attempt's output.
SDK binding drift means the SDK and generator pins disagree; do not edit the lock
to bypass it. A denied publication commonly means the policy expired, the exact
source approval differs, or an evidence file is missing. A denied HTTP call
requires checking the deployment grant, provider binding and allowed destination.
