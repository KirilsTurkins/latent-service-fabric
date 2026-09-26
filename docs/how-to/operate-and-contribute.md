# Inspect and stop a local node

Check whether your node is ready, inspect a recent call and stop the node you
started. These steps use the local node from
[Run your first node](../start/first-node.md), through step 7. Keep that terminal
open: its `cli`, `field`, `start_node`, `stop_node` and `ready` helpers select your private
configuration and the process you own.

## 1. Check readiness and routes

```bash
cli node get learning-node > "$RESULTS/node-inventory.json"
field "$RESULTS/node-inventory.json" data inventory health ready
cli route get > "$RESULTS/routes.json"
python3 - "$RESULTS/routes.json" <<'PY'
import json, sys
routes = json.load(open(sys.argv[1]))["data"]["snapshot"]["services"]
for route in routes:
    print(route["service"], "via", route["routeId"])
PY
```

The readiness check should print **True**. Individual calls can still be denied
or run out of resources. The route list
shows `examples/echo` through its default and named deployment routes.
If the connection is refused, check that the tutorial node is running and read
`$LSF_TUTORIAL_DIR/node/diagnostic.jsonl` for startup errors.

For resource pressure, inspect the node's cells, queues, quotas and caches.
A full execution-cell pool differs from a failed compiler or a denied capability.
Use the [inventory reference](../reference/standalone-node.md) and
[resource budgets](../runtime/resource-budgets.md) to interpret those fields.

## 2. Inspect your most recent echo call

The first-node guide supplies an activation ID before sending each call. Its
post-restart invocation uses `learning-after-restart`:

```bash
cli activation get learning-after-restart > "$RESULTS/activation-status.json"
field "$RESULTS/activation-status.json" data terminalState
```

You should see **completed**. Activation history is bounded;
after eviction or another node restart, a missing status does not prove that
the call never ran. Deployments and activation history have different lifetimes.

For your own calls, choose and save a new activation ID before dispatch. If the
response is lost, inspect that original ID instead of invoking again to discover
the old result.

## 3. Understand an explicit cancellation

The echo call has already finished. Cancelling it demonstrates the
already-terminal response:

```bash
cli activation cancel learning-after-restart > "$RESULTS/cancellation.json"
field "$RESULTS/cancellation.json" data disposition
cli activation get learning-after-restart > "$RESULTS/activation-status.json"
field "$RESULTS/activation-status.json" data terminalState
```

The output is **already_terminal**, followed by **completed**. For an active
call, the same command requests cancellation. Keep these outcomes
separate:

| Result | Meaning |
| --- | --- |
| Accepted | The node accepted the cancellation request; cleanup may still be running |
| Already terminal | The call already has a terminal outcome |
| Not found | The node has no retained activation visible to this caller |

Pressing Ctrl-C in a client stops its local wait; it does not prove the node or an
external provider stopped. A cancelled call can also have completed an external
effect before interruption. Follow the provider's recovery contract when that
outcome is uncertain.

## 4. Recover a management request by its operation ID

Managed changes have their own operation IDs, separate from invocation IDs.
The [policy walkthrough](reconcile-a-policy-change.md) gives a complete example
using `policy operation` to find creation and revocation results.

Choose the lookup that owns your request: `deployment operation`,
`release operation`, `rollout operation` or `policy operation`. Keep its original
tenant, operation ID, request and preconditions. An unknown lookup is still
uncertain because receipt retention is finite. A historical receipt does not
restore permission to a revoked publication or policy.

For a node with durable audit configured, read one bounded page with:

```bash
cli audit query --scope tenant --page-size 16
```

The basic tutorial node has no durable audit configured, so use this command
only after enabling it through the [audit configuration](../phase-2-audit.md).
Continue with the returned cursor, if any. An empty page with a cursor is not
necessarily the end of history, and an audit acknowledgement is separate from
the underlying operation result.

## 5. Stop or restart your node

```bash
stop_node
tail -n 1 "$LSF_TUTORIAL_DIR/node/status.jsonl" > "$RESULTS/stopped.json"
field "$RESULTS/stopped.json" clean
```

The final check should print **True** for clean shutdown. The helper sends termination
to the exact process started by this terminal and waits for it to exit. A forced
stop or incomplete cleanup must be investigated before treating work as drained.

To resume this experiment with its saved deployments:

```bash
start_node
ready
```

When you are finished, remove the tutorial deployment and stop the node using
[the first-node cleanup](../start/first-node.md#8-continue-or-stop).
Keep or remove the printed private tutorial directory only after the node has
stopped. Do not delete a live catalog or use a broad process-name kill command.

For an installed server, use its
[service status and drain commands](../../packaging/linux/INSTALL.md#status-drain-and-hardening)
and [backup procedure](../../packaging/linux/INSTALL.md#reinstall-upgrade-and-recovery).
Preserve matching configuration, credentials, trust history and catalog state
together in a consistent stopped backup. A binary downgrade does not convert
stored data.

To change LSF itself, use the [contribution guide](../contribute/index.md).
It covers choosing an issue, creating a branch and running the checks relevant
to your change.
