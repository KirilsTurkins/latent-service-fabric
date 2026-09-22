# Operate a local node and choose a contribution

## Outcome and supported scope

Separate an operational symptom from a retry decision, inspect the right retained
identity, stop only your owned node, and choose focused validation for a change.
This is the standalone development profile, not a cluster or a production
service-level guarantee. Start with [the first-node guide](../start/first-node.md)
and the [CLI contract](../reference/operator-cli.md) before using these commands.

You need the CLI, an explicitly selected protected client configuration, the actual
node ID and any invocation/operation identity retained by your own request.
`CLIENT_CONFIG`, `NODE_ID`, `ACTIVATION_ID` and `OPERATION_ID` below are selectors
from that run, not shared credentials or IDs to paste against somebody else's node.
No token belongs in a command-line argument, website bundle or public log.

## Readiness and resource diagnosis

```bash
latent --config "$CLIENT_CONFIG" --output json node get "$NODE_ID"
latent --config "$CLIENT_CONFIG" --output json route get
latent --config "$CLIENT_CONFIG" --output json activation get "$ACTIVATION_ID"
```

Check `data.inventory.health.ready`, then the bounded cell, queue, quota and cache
observations. A responsive management listener does not guarantee admission is
ready. Missing pressure observations, exhaustion and preparation contention have
different owners; do not infer a cause from HTTP reachability or one empty queue.
Use [node configuration](../reference/standalone-node.md),
[resource budgets](../runtime/resource-budgets.md) and
[telemetry](../telemetry.md) to interpret the reported values.
Configured ceilings are not measured resident memory and a warmed cache is not a
per-dormant-application process. Preserve the exact source and measurement scope
when discussing memory or latency.

A requested Invoke RPC timeout must fit `execution.maximumWallTimeMillis` even
when `--wall-time-ms` is smaller. Diagnose cold preparation and the selected
client/node time ceilings; do not silently enlarge them, infer that a timed-out
activation never ran, or retry until the system happens to accept it.

## Cancellation and uncertain results

To cancel a known activation explicitly from another process:

```bash
latent --config "$CLIENT_CONFIG" --output json activation cancel "$ACTIVATION_ID"
latent --config "$CLIENT_CONFIG" --output json activation get "$ACTIVATION_ID"
```

Preserve `accepted`, `already_terminal` and `not_found` distinctly. Ctrl-C of a
client is not an acknowledged Cancel RPC. A missing status can mean eviction,
restart or foreign scope, not proof of non-execution. The existing
[real CLI outcome tests](../../apps/latent/tests/standalone_cli/outcomes.rs)
exercise declared errors, traps, deadlines, explicit cancellation and recovery;
the small echo runner does not replace that cancellation suite.

For a managed deployment response lost after submission, inspect the original
operation rather than constructing a new mutation:

```bash
latent --config "$CLIENT_CONFIG" --output json deployment operation "$OPERATION_ID"
```

Use the matching `release operation` or `rollout operation ROLLOUT OPERATION`
family for those owners. Keep original tenant, request and preconditions.
`unknown` remains unknown; finite receipt retention cannot prove a request did
not execute. A replayed historical receipt does not restore revoked authority.
The [delivery/recovery walkthrough](../learn/deliver-and-recover-a-capsule.md)
shows the separate object generation, catalog state version, rollout revision and
rollback target. Aborting a rollout is not restoration of old traffic weights.

For configured durable audit, read a bounded page:

```bash
latent --config "$CLIENT_CONFIG" --output json audit query --scope tenant --page-size 16
```

Use only the returned cursor for continuation. An empty page with a cursor is not
necessarily the end of history; audit observation is not durable external action.
Absent or uncertain acknowledgement does not undo a committed catalog mutation.
No part of this guide automatically restarts pagination or retries a mutation.

## Shutdown, backup and recovery

The first-node runner stops its owned processes and checks both reported cleanup
and physical reap. An interactive source node instead uses the PID/process owner
created by the [quickstart](../development/standalone-quickstart.md). Do not use
broad `pkill`, delete a live catalog, or adopt a PID whose ownership was lost.
Stopping a listener is not sufficient evidence that guest/compiler/provider work
has drained; inspect the node's actual stopped/clean report.

For an installed node, use the installer's [status/drain contract](../../packaging/linux/INSTALL.md#status-drain-and-hardening)
and [consistent backup/recovery procedure](../../packaging/linux/INSTALL.md#reinstall-upgrade-and-recovery).
Preserve credentials, protected trust and matching catalog state together under
the documented offline boundary. There is no live config reload or generic
cross-version downgrade promise. A binary downgrade does not reverse a storage
migration. Native uninstall and separately confirmed installation-ID purge are
different operations; a guide-test cleanup authorizes neither on a server.

## Choose and validate a contribution

Follow [CONTRIBUTING](../../CONTRIBUTING.md) and the
[live issue queue](https://github.com/KirilsTurkins/latent-service-fabric/issues).
Select an open issue, read its owning subsystem/acceptance criteria and create a
focused branch from development. Do not use article counts or one passing test
as a replacement for the requested behavior.
The [contract and evidence guide](../learn/read-contracts-and-evidence.md) shows
how to validate retained receipts and find the exact authority for a proposed change.

For these guide sources and their first-node runner:

```bash
python3 -m unittest tools.tests.test_first_node_guide
python3 tools/validate_docs.py
git diff --check
```

Then use the pinned [website validation commands](../development/website.md) and
its production builds for both base paths. The new synthetic Python tests prove
runner sequencing/redaction/cleanup behavior, not a real-node walkthrough.
Changes to executable examples still require their owning runtime/SDK tests.
The [CI classifier contract](../development/ci-profiles.md) retains conservative
full validation for shared tools, product inputs, frozen evidence and uncertain
changes; do not bypass it by calling executable MDX inert prose.

## Failure, cleanup and evidence

A failing selected test remains a failure; retain the command/source/toolchain and
bounded redacted diagnostic, fix the cause and rerun the relevant check. Never
mark a skipped native/browser test as passed, replace a failed receipt, enlarge a
frozen budget, or silently substitute synthetic peers for LSF.

Remove only your owned preview processes, target output or private guide-test
files after retaining the compact nonsecret evidence. Link validation and human
review separately in the [core guide handoff](../development/core-guide-validation.md).
Next, use the shared [delivery/recovery path](../learn/deliver-and-recover-a-capsule.md)
or the applicable capability/SDK guide; avoid inventing later-phase state,
workflow or exactly-once semantics from a successful local call.
