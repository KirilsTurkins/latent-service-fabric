# Publish sites from a private CI runner

Use this workflow to publish and switch static sites without replacing the
running node. A trusted Linux CI runner reaches the local Docker daemon; the
receiver inside the node uses its private operator credential. Management stays
on loopback. On Windows, run these commands in the Linux/WSL host workspace.

This is the supported local-host alternative to managed-cloud execution. Azure
execution and cloud RBAC are unqualified. Docker access grants control of the
host: use a dedicated trusted runner, never an application container or a job
which executes unreviewed contributions. The maintained
[container CI workflow](../../.github/workflows/container-runtime.yml) demonstrates
the same transport on disposable GitHub-hosted runners with actual released
binaries and fresh test identities.

## Prepare the node and the runner

Follow [Run a node in a Linux container](container-runtime.md). Add a protected
`/etc/lsf/ci-client.json` with your operator client profile for the intended tenant.
Use a read-only `/etc/lsf` mount. Credentials belong to your organization; keep
them out of workflow arguments, environment dumps, logs and infrastructure state.
Only the receiver reads this file. Revoking Docker access does not revoke the
native credential: manage both authorities.

Mount reviewed publication inputs read-only at `/work`, using the signed package
and evidence produced by [Release a static site](static-release-workflow.md).
That directory may contain immutable packages for multiple releases. Atomically
stage complete inputs on the host before requesting publication. Never modify
an already reviewed package. The CLI verifies the package and evidence again.

Install the repository's reviewed operator tools on the host. Keep a private,
persistent journal directory outside the ephemeral CI job workspace. The tools
require Python 3.11 or newer and a protected, root-owned Docker executable at
`/usr/bin/docker`. They use only `/var/run/docker.sock`.

```sh
install -d -m 0700 "$CI_STATE"
python3 tools/container_runtime/ci_operator.py select --container "$CONTAINER_ID" --image "$APPROVED_IMAGE_ID" --node "$NODE_ID" --tenant "$TENANT" --target "$CI_STATE/target.json"
```

Use the complete container and approved image IDs from your deployment record.
Selection checks UID/GID, running state and mount protections. It expires after
15 minutes and cannot follow a restarted or replacement container automatically.
Keep this target private. If its lease expires, create a new target file; the
same exact instance can recover an existing journal with that renewed lease.

## Publish and switch routes

Create a private request file, mode 0600. This example publishes inputs already
mounted in the node. Choose a unique operation ID and record it with the release:

```json
{"kind":"publish","id":"site-release-20260927","generation":"0","package":"/work/site-v2/package","evidence":"/work/site-v2/evidence/index.json"}
```

```sh
python3 tools/container_runtime/ci_operator.py run --target "$CI_STATE/target.json" --request "$CI_STATE/publish.json" --journal "$CI_STATE/publish-result.json"
```

The public summary contains the status and journal path. Read the private journal
for the confirmed `result.data.operation.publication.id`. `confirmed` means an
associated native receipt was observed. Any uncertain result requires recovery
before deciding what to do next. Never reuse a journal with `run`.

Inspect a route with `{"kind":"trigger-get","value":"site-get"}` in another
private request file. Its observed result supplies `data.stateVersion` and the
current trigger generation, or generation `"0"` when no trigger exists. An
`observed` read still requires checking `result.category`: a known not-found or
permission response is not a successful inspection.

A route mutation uses those exact preconditions and the newly admitted
publication. The [route-set guide](static-route-sets.md) explains how
to reconcile GET and HEAD without overwriting unrelated concurrent changes.
The receiver accepts this closed shape:

```json
{
  "kind": "route", "id": "site-get-release-20260927",
  "generation": "1", "stateVersion": "4",
  "manifest": {
    "apiVersion": "latent.dev/v1alpha1", "kind": "HttpTrigger",
    "metadata": {"name": "site-get", "tenant": "example"},
    "spec": {
      "target": {"kind": "static-web", "publication": "publication:sha256:REPLACE_WITH_ADMITTED_ID"},
      "configuration": {"profile": "static-site-v1", "scheme": "https", "host": "frontend.example.test", "path": "/", "pathMatch": "prefix", "method": "GET"}
    }
  }
}
```

Replace all example identities and counters with the inspected values. Run it
with its own request and journal paths, then inspect current state again before
updating HEAD. For rollback, verify that the earlier publication is eligible
and submit new explicit route operations with fresh current preconditions.
Neither publication nor route changes require a container restart.

## Recover an interrupted command

```sh
python3 tools/container_runtime/ci_operator.py recover --target "$CI_STATE/target.json" --request "$CI_STATE/publish.json" --journal "$CI_STATE/publish-result.json"
```

Recovery reads the original receipt only. A historical confirmed receipt is not
proof that another job has left the route unchanged. Inspect current state before
continuing a release or rollback.

| Result or failure | Next action |
| --- | --- |
| `confirmed` | Inspect current publication/route state before subsequent mutations. |
| `rejected` | Review the known native rejection; correct inputs or preconditions with a new reviewed operation. |
| `pending` / `uncertain`, interrupted worker or partial response | Keep the original journal and query its receipt with `recover`. Do not replay the mutation. |
| Missing or evicted receipt | Keep the outcome uncertain; reconcile actual catalog and route state privately before authorizing a new operation. |
| Expired selection | Select the same instance with a new target path, then recover the original journal. |
| Replaced instance, changed start instant or wrong node/tenant | Stop dispatch. Review ownership handover and durable state before using native inspection in the new instance. Do not edit the old journal's binding. |
| Daemon or native permission denied | Correct the intended authority privately; do not publish management or inject credentials into arguments. |
| Another receiver owns the lock | Finish or recover that job first; there is no hidden queue or automatic mutation retry. |

Each call permits 64 KiB input and 512 KiB total channel output. Each Docker
process has a 20-second deadline; the receiver permits at most one 5-second
native RPC after its identity check, with six-second process bounds. One host
invocation performs at most three Docker processes. Cancellation reaps local
transport processes; an already accepted native mutation can still finish.
Journals are fsynced before dispatch and after result recording. Keep them as
private deployment records with a deliberate retention policy.

The [architecture decision](../../adr/0056-run-headless-operators-through-a-private-local-transport.md)
describes the exact identity and recovery boundary.
