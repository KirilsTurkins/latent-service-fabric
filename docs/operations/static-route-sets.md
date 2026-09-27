# Publish and recover a static route set

Use the route-set tool when one static publication serves both GET and HEAD.
It records the full intent before changing a route and helps a CI job continue
after interruption. You need Node.js 22 or newer, the released `latent` binary,
an operator profile for your tenant, and an already published static site.
On Windows, run these commands inside the Linux backend or WSL where your node
and private operator profile are available.

The tool uses the existing private loopback management endpoint. Run it in the
node's network namespace or through a separately supported private operator
workflow. A remote hosted job cannot reach the node through its own loopback.

## Describe the complete route set

Save this as `routes.json`, replacing the publication ID with the one returned
by `latent web publish` and the host with your public hostname:

```json
{
  "schemaVersion": "latent.static.route-set.v1",
  "tenant": "example",
  "publication": "publication:sha256:<publication-id>",
  "routes": [
    {
      "get": "docs-get",
      "head": "docs-head",
      "scheme": "https",
      "host": "docs.example.com",
      "path": "/docs",
      "pathMatch": "prefix"
    }
  ]
}
```

Each entry declares both methods. Up to eight route pairs can share one
immutable target publication. Existing trigger IDs must already belong to the
same static route configuration; a plan cannot take over an API route or move
another route's host/path. Existing labels and annotations are preserved.

Create a private local directory for the journal:

```sh
mkdir -m 700 release-state
```

From the LSF checkout, prepare a plan. Substitute your actual binary, protected
operator profile and node ID. `operator` below is the profile's configured name:

```sh
node tools/static-release/route-set.mjs plan --cli /opt/lsf/bin/latent --config /etc/lsf/operator.json --profile operator --node example-node --intent routes.json --journal release-state/docs.json
```

Review the generated plan, then apply it using the same connection arguments:

```sh
node tools/static-release/route-set.mjs apply --cli /opt/lsf/bin/latent --config /etc/lsf/operator.json --profile operator --node example-node --journal release-state/docs.json
```

The journal contains manifests, generations, stable operation IDs and receipts;
it contains no credentials. Keep it private and preserve it with your CI job's
recovery artifacts. The configured endpoint, profile, node and tenant are bound
to the journal. Credentials may rotate within that same authorized connection.

## Understand the result

| Status | Meaning and next step |
| --- | --- |
| `planned` | Current publication eligibility and an unchanged route snapshot were checked; no mutation was sent. |
| `complete` | One coherent current route snapshot matches the intended set, and the publication was checked eligible. |
| `partial` | Some progress or the configured write budget was observed; GET and HEAD may select different publications. Inspect the reason before continuing. |
| `uncertain` | A mutation or its durability cannot be confirmed. The tool will not replace or replay that request automatically. |
| `failed` | The plan or a known operation was rejected. Inspect live state and the reason before preparing new intent. |

Success is an observation, not a promise that another authorized operator cannot
change the routes afterward. The sequence is **not atomic**: GET changes first,
then HEAD. Requests accepted between those commits can use different versions.
Applications needing atomic visibility must wait for a separate route-set API;
this tool does not hide that window or weaken catalog fences.

## Recover an interrupted job

Run `status` with the same connection and journal arguments. It only reads the
node and updates local recovery observations. It never submits a route mutation.
Then run `apply` to continue any remaining known intent. `apply` queries a pending
operation's receipt and checks its current live route before proceeding. A
historical successful receipt cannot restore a subsequently changed route.

An unrelated catalog update can cause a state-version conflict. After a confirmed
rejection, the tool rereads the exact original route and may create a new guarded
operation ID. A changed generation or manifest stops the run without overwriting
the other writer. Four attempts per route, 256 CLI calls per run and a 120-second
default deadline bound this process. `--deadline-seconds` permits 1–600 seconds;
`--maximum-writes` permits 1–64 writes per apply invocation. Smaller batches can
intentionally leave a visible partial set.

The node retains only its latest 64 trigger receipts. `UNKNOWN` can mean eviction,
not non-execution. If lookup cannot confirm an operation, inspect the live routes,
publication eligibility and audit history. Preserve the uncertain journal and
prepare a **new** plan in a new journal for an explicit new decision. Do not edit
an old operation's preconditions or delete its history to make it retry.

A crashed process may leave `docs.json.lock`. Check its recorded PID, verify that
the owning process has exited and that no CI job is using the journal, then remove
that exact lock file. Never remove a live owner's lock. Interrupted `.pending`
files are not recovery authority; the last complete journal remains authoritative.
The tool requires a private local filesystem with atomic replacement and directory
sync. This does not qualify an Azure mount or a shared network filesystem.

## Roll back a publication

Create another intent file with the same route IDs/configuration and the earlier
publication ID. Use a **new journal** and run `plan` then `apply`. Rollback creates
new guarded operations; it never replays the old promotion. Retired/revoked
publications and evidence that is expired or no longer trusted are rejected by
the current eligibility check and again by native admission. Renew evidence or
choose an eligible publication before making a new release decision.

See [HTTP route contracts](../reference/http-triggers.md) for generation fences,
retained receipt semantics and current-publication checks, and
[ADR-0047](../../adr/0047-reconcile-static-route-sets-with-durable-intent.md)
for the recovery decision.
