# Create your own C# capsule

For the packaged C# workflow, start with [application development](../start/application-development.md) and select `dotnet` when [getting the tools](../start/developer-setup.md). The controller builds your project on Linux or WSL, creates node credentials, and runs the real-node tests. You do not need to build LSF or install the language compiler on Windows.

The commands below describe the language-owned source recipe, packaging and admission steps for readers who need to work at that level.

Create an independent C# project, edit its typed contract, and run its signed
package on a local node. Your application lives outside the LSF checkout.

Use Linux x86-64, Python 3.13.5, Rust 1.97.1 and .NET SDK **10.0.100**.
The captured compiler uses Componentize.NET 0.8.0-preview00011 and its exact
NativeAOT LLVM dependency lock. This experimental profile is not a general .NET
host: no JIT, dynamic assemblies, application packages, thread pool, timers or
host event loop. Contract calls suspend through the LSF runtime.
Run from the checkout after installing the pinned .NET and Rust SDKs:

```sh
DOTNET_COMPILERS=$(mktemp -d "${TMPDIR:-/tmp}/lsf-dotnet-tools.XXXXXXXX")
curl --fail --location --max-time 180 \
  https://github.com/WebAssembly/wasi-sdk/releases/download/wasi-sdk-29/wasi-sdk-29.0-x86_64-linux.tar.gz \
  --output "$DOTNET_COMPILERS/wasi-sdk.tar.gz"
printf '%s  %s\n' 87d1d1a2879d139cdc624b968efad3d4a97b8078cdff95e63ac88ecafd1a0171 "$DOTNET_COMPILERS/wasi-sdk.tar.gz" | sha256sum --check --strict
tar -xzf "$DOTNET_COMPILERS/wasi-sdk.tar.gz" -C "$DOTNET_COMPILERS"
cargo install --locked wasm-tools --version 1.254.0
python3 tools/install_guest_bindgen.py "$DOTNET_COMPILERS/bindgen"
export PATH="$DOTNET_COMPILERS/bindgen:$PATH"
rustup target add wasm32-unknown-unknown --toolchain 1.97.1
python3 tools/dotnet_capsule.py install-tools "$DOTNET_COMPILERS/dotnet" \
  --wasi-sdk "$DOTNET_COMPILERS/wasi-sdk-29.0-x86_64-linux"
export LSF_DOTNET_TOOLS="$DOTNET_COMPILERS/dotnet"
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
export LSF_DOTNET_PROJECTS="${LSF_DOTNET_PROJECTS:-$(mktemp -d "${TMPDIR:-/tmp}/lsf-dotnet-projects.XXXXXXXX")}"
python3 tools/dotnet_capsule.py new "$LSF_DOTNET_PROJECTS/my-greeting" --template greeting
```

Open `my-greeting/src/Main.cs` and `my-greeting/wit/world.wit`. They contain the
complete [greeting example](creating-a-capsule.md#1-a-greeting-capsule), including
its ordinary C# implementation of the generated typed export. The contract is:

```wit
greet: func(name: string) -> result<string, string>;
```

The project includes authoritative WIT, `capsule-project.json`, pinned
`Capsule.csproj`/`global.json`, and an immutable SDK in `vendor/lsf`.
Edit `src/*.cs` and `wit`, using the generated export namespace/class for your
selected `service` world. Keep SDK/compiler configuration unchanged.
The builder rejects SDK drift, escaping paths, unreviewed MSBuild inputs and
application NuGet dependencies. Generated C# and typed `Lsf.Guest` capability
facades are compiled from the actual selected WIT, not handwritten ABI guesses.

The `word-count` and `shipping` templates provide equivalent C# implementations
of [Creating a capsule](creating-a-capsule.md). Choose another project directory
and replace `greeting` in the creation command with either template name.
`http-status` adds a typed, asynchronous HTTP call; its import still needs an
installed provider and an explicit deployment grant. Creating a project grants
no network access.

## 2. Build and package the project

```bash
python3 tools/dotnet_capsule.py build "$LSF_DOTNET_PROJECTS/my-greeting" \
  --tools "$LSF_DOTNET_TOOLS" \
  --output "$LSF_DOTNET_PROJECTS/greeting-build" \
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
"$BIN/examples/capsule_authoring" demo-sign "$LSF_DOTNET_PROJECTS/releases" \
  "$LSF_DOTNET_PROJECTS/greeting-build"
```

This policy lasts for this experiment and accepts only the captured source and
builder recipe. For a maintained deployment, use your organization's publisher,
builder and revocation policies through the [package workflow](packaging.md).
Finish the steps below within 30 minutes of signing; otherwise sign into a new
directory and start a new experiment.
Only this isolated demo gives publisher and builder proofs the same finite
1,800-second window as its signatures. Signature expiry, revocation and the
node's currentness checks remain enforced; production policies are unchanged.

## 4. Start a node with enforced admission

This node listens on an automatically selected loopback port. Its random client
credential stays in private files. It verifies both package signatures and the
builder policy before admitting a release.

```bash
mkdir "$LSF_DOTNET_PROJECTS/node" "$LSF_DOTNET_PROJECTS/results"
python3 - <<'PY'
import json, os, secrets, shutil
from pathlib import Path
root = Path(os.environ["LSF_DOTNET_PROJECTS"])
shutil.copyfile(root / "releases/policy.json", root / "node/policy.json")
token = secrets.token_urlsafe(32)
node = {
    "formatVersion": 1, "nodeId": "dotnet-learning-node", "dataDirectory": "data",
    "bind": "127.0.0.1:0", "securityProfile": "local-experimental-v1",
    "supplyChain": {"mode": "enforced", "policyFile": "policy.json", "clockLeaseSeconds": 5},
    "workers": {"runtime": 1, "control": 1},
    "cells": [{"class": "standard", "capacity": 1, "queueCapacity": 2, "maximumMemoryBytes": 134217728}],
    "execution": {"maximumCpuFuel": 1000000000, "maximumWallTimeMillis": 120000},
    "cache": {"entries": 2, "preparations": 1},
    "budgetProfile": {"mode": "phase3", "maximumOutboundRequests": 0,
                      "maximumBlobReadBytes": 0, "maximumBlobWriteBytes": 0},
    "capabilityPolicies": {"formatVersion": 1, "maximumControlJobs": 2},
    "audit": {"mode": "durable", "records": 1024, "diskBytes": 16777216,
              "queuedOperations": 8, "queryOwners": 2},
    "credentials": [{"token": token, "subject": "dotnet-learner", "tenant": "examples", "role": "operator"}],
}
runtime_imports = {
    "clockMonotonic": "latent:clock/monotonic@0.1.0",
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
"$BIN/latentd" check-config --config "$LSF_DOTNET_PROJECTS/node/node.json"
"$BIN/latentd" serve --config "$LSF_DOTNET_PROJECTS/node/node.json" \
  >"$LSF_DOTNET_PROJECTS/node/status.jsonl" 2>"$LSF_DOTNET_PROJECTS/node/diagnostics.jsonl" &
DOTNET_NODE_PID=$!
stop_dotnet_node() {
    if [[ -n "$DOTNET_NODE_PID" ]]; then
        local pid=$DOTNET_NODE_PID result=0
        DOTNET_NODE_PID=
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
trap 'stop_dotnet_node >/dev/null 2>&1 || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
python3 - <<'PY'
import json, os, time
from pathlib import Path
root = Path(os.environ["LSF_DOTNET_PROJECTS"])
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
dotnet_cli() { "$BIN/latent" --config "$LSF_DOTNET_PROJECTS/client.json" --output json "$@"; }
dotnet_cli node get dotnet-learning-node >"$LSF_DOTNET_PROJECTS/results/node.json"
```

## 5. Publish, deploy and invoke

Publishing returns an exact publication identity. This C# runtime needs explicit
monotonic-clock authority for the GC even for a greeting; no wall-clock or
entropy is implicitly granted. The next
block scopes each grant to this one publication, service, operation and caller.
There is no ambient WASI authority. Omitting a grant produces a platform denial
before the application can return. The guest's 128 MiB memory and fuel budgets
bound its runtime heap; no guest can create a host thread.

```bash
dotnet_cli release publish-package "$LSF_DOTNET_PROJECTS/releases/my-greeting/package" \
  --evidence "$LSF_DOTNET_PROJECTS/releases/my-greeting/evidence/index.json" \
  --operation-id publish-my-greeting --expected-generation 0 \
  >"$LSF_DOTNET_PROJECTS/results/published.json"
python3 - <<'PY'
import json, os
from pathlib import Path
root = Path(os.environ["LSF_DOTNET_PROJECTS"])
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
    }[name]
    binding = {"formatVersion": 1, "tenant": "examples", "capability": capability,
        "providerProfile": provider["profile"], "configurationDigest": provider["configurationDigest"],
        "configurationEpoch": int(provider["configurationEpoch"]), "restriction": {"operations": [operation]}}
    policy = {"formatVersion": 1, "tenant": "examples", "rules": [{
        "id": "runtime", "effect": "allow", "principals": [{"kind": "administrator", "subject": "dotnet-learner"}],
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
for name in clockMonotonic; do
    dotnet_cli policy --kind provider-binding apply --id "$name-installed" \
      --file "$LSF_DOTNET_PROJECTS/results/$name-binding.json" \
      --operation-id "install-$name" --expected-generation 0
    dotnet_cli policy apply --id "$name-allow" --file "$LSF_DOTNET_PROJECTS/results/$name-policy.json" \
      --operation-id "grant-$name" --expected-generation 0
done
dotnet_cli deployment apply "$LSF_DOTNET_PROJECTS/results/deployment.json" --expected-generation 0 \
  >"$LSF_DOTNET_PROJECTS/results/deployed.json"
printf '["Ada"]\n' >"$LSF_DOTNET_PROJECTS/results/input.json"
dotnet_cli invoke --memory-bytes 134217728 --cpu-fuel 1000000000 --wall-time-ms 120000 \
  --service examples/my-greeting --route my-greeting \
  --contract examples:greeting/api@1.0.0 --function greet --activation-id my-greeting-valid \
  --input "$LSF_DOTNET_PROJECTS/results/input.json" >"$LSF_DOTNET_PROJECTS/results/answer.json"
dotnet_answer() {
    python3 - "$1" <<'PY'
import base64, json, sys
data = json.load(open(sys.argv[1]))["data"]
payload = data.get("payload") or data["declaredError"]["payload"]
print(base64.b64decode(payload["data"]).decode())
PY
}
dotnet_answer "$LSF_DOTNET_PROJECTS/results/answer.json"
printf '[""]\n' >"$LSF_DOTNET_PROJECTS/results/empty.json"
dotnet_cli invoke --memory-bytes 134217728 --cpu-fuel 1000000000 --wall-time-ms 120000 \
  --service examples/my-greeting --route my-greeting \
  --contract examples:greeting/api@1.0.0 --function greet --activation-id my-greeting-invalid \
  --input "$LSF_DOTNET_PROJECTS/results/empty.json" >"$LSF_DOTNET_PROJECTS/results/error.json" || test "$?" -eq 3
dotnet_answer "$LSF_DOTNET_PROJECTS/results/error.json"
```

Expected answers are `[{"ok":"Hello, Ada!"}]` and
`[{"err":"Please enter a name."}]`. Exit code 3 is a declared application
error. Connection failures, exhausted budgets and guest traps have different
outcomes. Use a new activation ID for a new request; an uncertain mutation must
be inspected before any retry.

## 6. Clean up and continue

Wait for the completed calls' bounded audit work to drain before deleting the
deployment once. This helper performs only read-only capability inspections,
with a five-second observation deadline and at most 32 reads, and records the
observed audit ownership counters, including queued and staging bytes.
Missing audit counters, unavailable observations, a closed/recovering journal,
or an expired deadline stop cleanup;
inspect that failure instead of retrying an uncertain deletion. Each inspection
has a one-second process bound plus at most five seconds for owned child cleanup.
The idle snapshot is not a reservation or a guarantee of retained-disk capacity;
concurrent work can still consume capacity. The single deletion still checks
its current policy, generation and capacity.

```bash
python3 tools/wait_capsule_audit_idle.py --cli "$BIN/latent" \
  --config "$LSF_DOTNET_PROJECTS/client.json" --deployment my-greeting \
  >"$LSF_DOTNET_PROJECTS/results/audit-idle.json"
GENERATION=$(python3 -c 'import json,os; print(json.load(open(os.environ["LSF_DOTNET_PROJECTS"]+"/results/deployed.json"))["data"]["deployment"]["generation"])')
dotnet_cli deployment delete my-greeting --expected-generation "$GENERATION"
stop_dotnet_node
printf 'Saved project and results: %s\n' "$LSF_DOTNET_PROJECTS"
```

Your source and results remain at that path. Edit the greeting, create a new
build directory, and repeat signing and delivery to try a change. The
[delivery and recovery](../learn/deliver-and-recover-a-capsule.md) guide explains
update and recovery principles using its separate Rust tutorial project and
node. Its commands require that tutorial's prerequisites and variables; for
this C# project, retain the build, signing and admission path above.

For capabilities, use the [guest SDK reference](guest-sdk.md). It covers buffered
and streaming HTTP, blobs, secrets, events, local calls, randomness and metrics,
including each wrapper's close/drop rules. The [C# guest SDK](../../sdk/dotnet-guest/README.md) supplies typed
`Lsf.Guest` facades over exact generated interfaces.
Use consuming operations and `using`/`Dispose` for owners; there is no
finalizer-driven resource release. Aliases share a single consumed/borrowed state. An imported effect is allowed only
by host policy. Pending calls retain their budget until the host releases them;
cancelling a subtask never proves an external effect did not occur.

If a build fails, inspect `BUILD-FAILED.json` and `logs/` in that attempt's output.
SDK binding drift means the SDK and generator pins disagree; do not edit the lock
to bypass it. A denied publication commonly means the policy expired, the exact
source approval differs, or an evidence file is missing. A denied HTTP call
requires checking the deployment grant, provider binding and allowed destination.
