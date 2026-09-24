# Change and revoke a capability policy

Create a policy, read it back, revoke it and check that the revocation survives
a node restart. You will also learn how to find the result of a management
request when its response is lost.

This example uses an **empty policy**, which permits no capability operations.
It lets you learn policy management without granting network or secret access.
To give a capsule access to a provider, continue with
[capabilities](../learn/use-capabilities.md).

## Before you start

Complete [Run your first node](../start/first-node.md) through step 7 and keep
that terminal open. This guide uses its running `learning-node`, private files,
`cli`, `field`, `start_node`, `stop_node` and `ready` helpers. Run these Bash blocks
in the same terminal, from the repository root. Use a fresh tutorial directory
if you have already created `learning-policy` in an earlier attempt.

## 1. Enable policy management

Stop the tutorial node before changing its configuration. Add the policy store
settings, check the file and restart the same node:

```bash
stop_node
python3 - "$LSF_TUTORIAL_DIR/node/node.json" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
config = json.loads(path.read_text())
config["capabilityPolicies"] = {"formatVersion": 1, "maximumControlJobs": 2}
path.write_text(json.dumps(config, indent=2) + "\n")
PY
"$BIN/latentd" check-config --config "$LSF_TUTORIAL_DIR/node/node.json"
start_node
ready
```

Wait for **Your node is ready.** Policy management now has a durable local store.
Enabling it does not install a provider or authorize a capsule.

## 2. Write and apply an empty policy

The policy belongs to the tutorial tenant `examples`. An empty `rules` list
grants nothing:

```bash
cat > "$RESULTS/learning-policy.json" <<'JSON'
{
  "formatVersion": 1,
  "tenant": "examples",
  "rules": []
}
JSON
cli policy apply --id learning-policy --file "$RESULTS/learning-policy.json" \
  --operation-id learning-policy-create --expected-generation 0 \
  > "$RESULTS/policy-created.json"
POLICY_GENERATION=$(field "$RESULTS/policy-created.json" data receipt generation)
printf 'Created policy generation %s\n' "$POLICY_GENERATION"
```

`--expected-generation 0` means the policy must not already exist. The node
returns its actual generation, which the next mutation must use. Keep the
operation ID `learning-policy-create`: it identifies this request's saved result.

## 3. Read the policy and its saved operation

```bash
cli policy get --id learning-policy
cli policy list --page-size 1
cli policy operation --operation-id learning-policy-create
```

The policy read shows the empty rules and `revoked: false`. The operation lookup
returns the receipt for creation. Reading that receipt does not apply the policy
again.

If a management response is lost, use its **original operation ID** for lookup.
Do not invent a new ID and repeat the mutation to discover whether the first
request worked. Receipts have finite retention; an `unknown` result does not
prove the request never ran.

## 4. Revoke the policy

Use the generation returned by creation:

```bash
cli policy revoke --id learning-policy \
  --operation-id learning-policy-revoke \
  --expected-generation "$POLICY_GENERATION"
cli policy get --id learning-policy > "$RESULTS/policy-revoked.json"
field "$RESULTS/policy-revoked.json" data policy revoked
cli policy operation --operation-id learning-policy-revoke
```

The helper prints **True**. The policy now has a newer generation and is revoked.
A policy with real grants would no longer authorize new operations through those
grants. Revocation does not undo an external effect that already occurred.

## 5. Restart and compare current state with history

```bash
stop_node
start_node
ready
cli policy get --id learning-policy > "$RESULTS/policy-after-restart.json"
field "$RESULTS/policy-after-restart.json" data policy revoked
cli policy operation --operation-id learning-policy-create
cli policy operation --operation-id learning-policy-revoke
```

The current policy still prints **True**. The creation receipt describes the
earlier successful creation; the revocation receipt describes the later change.
Reading the earlier receipt does not restore the old policy. Use `policy get`
when you need current state and `policy operation` when you need a request's
historical result.

## If a command fails

| Result | Next step |
| --- | --- |
| Policy management unavailable | Check that the node restarted with `capabilityPolicies` in its configuration |
| Policy already exists | Inspect it and its saved operation; use a fresh tutorial node to repeat this exercise from the beginning |
| Generation conflict | Read the current policy and reconcile your original request before deciding on a new change |
| Connection loss or timeout | Restore connectivity, then look up the original operation ID |
| Receipt is unknown | Keep the uncertainty; do not treat absence as proof that nothing changed |

## Continue or stop

The policy remains revoked in your tutorial data directory. Keep the node running
to continue learning, or stop it with `stop_node`. When you are finished with the
echo deployment too, use the cleanup step in the
[first-node guide](../start/first-node.md#8-continue-or-stop).

For the complete policy fields and provider-binding rules, read the
[policy reference](../runtime/capability-policies.md). For operational diagnosis,
continue with [provider failures](operate-capability-providers.md).
