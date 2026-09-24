# Try HTTP requests and object storage

A capsule needs permission to contact another service or store data. In this
walkthrough, run two example capsules: one requests a page from a local HTTP
server; the other writes and reads a small object. Then see what happens when a
request is denied and when you remove a previously granted permission.

The example script creates a temporary node, runs the requests, restarts that
node, and stops it afterward. This gives you a complete local demonstration
without a cloud account or changes to the node from your first tutorial.

## 1. Prepare your checkout

Start with the source checkout and Linux environment from
[Run your first node](../start/first-node.md). Run the commands below from the
repository root in one terminal. The examples use the current checkout.

You also need the pinned `wit-bindgen` and Zig tools from the
[toolchain setup](../development/toolchain.md). Zig builds the maintained C
example alongside the Rust examples. Keep the Python virtual environment from
the first-node guide active.

```bash
set -euo pipefail
umask 077
export CARGO_TARGET_DIR="$PWD/target"
mkdir -p "$CARGO_TARGET_DIR"
CAPABILITY_DEMO=$(mktemp -d "$CARGO_TARGET_DIR/capability-demo.XXXXXXXX")
cargo build --locked -p latent -p latentd
python3 tools/build_guest_capsules.py --output "$CAPABILITY_DEMO/guests"
```

This builds LSF and the example capsules. The new directory keeps this attempt
separate from previous attempts. The first build can take several minutes.

## 2. Prepare the packages for the temporary node

The example node checks who built and published each package. This command
creates signed packages and the matching temporary policy:

```bash
LSF_GUEST_CAPSULES="$CAPABILITY_DEMO/guests" \
LSF_PHASE3_WORKFLOW_FIXTURE_ROOT="$CAPABILITY_DEMO/inputs" \
  cargo test --locked -p latentd --test phase3_workflow_fixture -- \
    export_signed_provider_workflow_fixtures --exact --ignored --nocapture
```

Expect `1 passed; 0 failed`. Run the next step immediately afterward: these
demonstration signatures expire. The generated credentials and policy are only
for this temporary example. For your own installed node, follow
[package delivery](deliver-and-recover-a-capsule.md) and its trust configuration.

## 3. Run the example

```bash
python3 tools/run_phase3_management_workflow.py \
  --cli "$CARGO_TARGET_DIR/debug/latent" \
  --node "$CARGO_TARGET_DIR/debug/latentd" \
  --fixture-root "$CAPABILITY_DEMO/inputs" \
  > "$CAPABILITY_DEMO/result.json"
```

The script performs these actions in order:

| Action | What you should learn |
| --- | --- |
| Request the allowed HTTP path | The node can send an authorized request on behalf of a capsule |
| Request a different path | Permission for one destination does not allow every request |
| Write, seal and read an object | An immutable object can be read after it is sealed; its contents cannot then be changed |
| Restart the node and invoke again | The same deployments and their selected versions remain available |
| Revoke the HTTP grant and invoke again | Removing permission prevents another request from reaching the server |
| Stop the node and the local server | The script closes the resources it started |

Show a short result summary:

```bash
python3 - "$CAPABILITY_DEMO/result.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as source:
    result = json.load(source)
print("Authorized HTTP requests:", result["upstream"]["authorized"])
print("Unexpected HTTP requests:", result["upstream"]["unexpected"])
print("Revoked permission blocked further access:", result["grantsRevoked"])
print("Selected deployments survived restart:", result["selectedRevisionPreservedAcrossRestart"])
print("Clean shutdowns:", sum(node["record"]["report"]["providers"]["clean"]
                               for node in result["shutdown"]))
PY
```

Expect four authorized requests, zero unexpected requests, `True` for both
permission revocation and restart, and two clean shutdowns. The denied calls
are intentional parts of the example. If the script exits with an error, use
[provider troubleshooting](../how-to/operate-capability-providers.md) before
rerunning it with a fresh demo directory.

## 4. Follow the capsule code

The [HTTP example](../../tools/toolchain-smoke/examples/guest_http/component.rs)
requests the permitted URL. The
[blob example](../../tools/toolchain-smoke/examples/guest_blob/component.rs)
creates, writes, seals and reads an object. Both ask the host to do the work
through an imported capability; they do not open arbitrary host files or sockets.

Three pieces must agree for a request to work:

1. The node installs a provider that can perform the operation.
2. The deployment receives a grant for that capability.
3. The current policy permits the particular request within its resource budget.

For example, installing an HTTP provider does not grant every capsule internet
access. The demonstration policy allows one local server and path. See
[Configure standalone providers](../reference/standalone-providers.md) when
you are ready to configure your own node.

## 5. Finish or explore another provider

The script stops its temporary node and HTTP server automatically. Its build
outputs and result remain in the directory printed by:

```bash
printf '%s\n' "$CAPABILITY_DEMO"
```

You can remove that demo directory when you no longer need its files.

The standalone configuration currently exposes buffered HTTP and local
immutable blobs. Other capabilities have their own integration paths:
[streaming HTTP](../runtime/streaming-http.md),
[local service calls](../runtime/local-service-invocation.md),
[secrets](../runtime/local-secrets.md), [randomness](../runtime/random.md),
and [custom metrics](../runtime/custom-metrics.md).
For S3, Vault and NATS, continue with the
[local provider examples](../how-to/exercise-provider-failure-and-recovery.md).
