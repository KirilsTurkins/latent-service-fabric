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

## Preflight audit capacity before renewal

From the LSF checkout, inspect the live node before renewing evidence or changing
routes. Substitute your actual binary, protected operator profile and node ID.
`operator` below is the profile's configured name:

```sh
node tools/static-release/route-set.mjs preflight \
  --cli /opt/lsf/bin/latent --config /etc/lsf/operator.json \
  --profile operator --node example-node --intent routes.json \
  --journal release-state/docs.json --diagnostic-records 2 \
  --competing-operations 1 --warning-percent 80 --cadence-minutes 10
```

This reads authenticated node inventory and returns a
`latent.static.audit-headroom.v1` result. It creates no route operation and does
not create or replace the recovery journal. The private directory and exclusive
local command lock are still required. Preflight can inspect capacity before
refreshing currently stale evidence; it does not authorize that renewal or bypass
the eligibility checks used by `plan`, `apply` and native mutation admission.

A renewal followed by one GET/HEAD pair needs at least **six critical records**:
an attempt and outcome for each of the three mutations. Reserving the maximum
16 KiB per record gives a conservative 96 KiB critical byte allowance. Defaults
also allow two diagnostics and one competing critical operation: ten records and
160 KiB for this planning example. Existing charged reservations are subtracted
from headroom. More traffic can consume more than this margin.

| Preflight status | Exit | Meaning |
| --- | ---: | --- |
| `headroom-observed` | 0 | The sampled counters meet the requested planning allowance. |
| `warning` | 3 | A configured pressure threshold was reached. Arrange maintenance before exhaustion or evidence expiry. |
| `blocked` | 4 | A sampled resource or owner condition prevents the requested plan from fitting. Inspect the fixed reasons. |
| `unavailable` | 5 | The required observation is unavailable; missing counters are not zero. |

The result is **advisory**, not a reservation or an atomic renewal. Record, byte,
metadata, queue, pending-attempt and storage pressure are separate. Another
producer can consume capacity immediately afterward. `--warning-percent` accepts
1–100, `--cadence-minutes` 1–1440, `--diagnostic-records` 0–256 and
`--competing-operations` 0–64. None changes node admission limits. The read-only
warning remains available without appending another audit diagnostic record.

Use the [stopped-node audit lifecycle](audit-journal-lifecycle.md) when an epoch
needs archival. Stop and drain the whole node before that exclusive operation;
do not move a live audit directory or disable auditing. Maintenance does not
extend signed evidence validity.

## Plan and apply

After any required evidence renewal, retain that renewal's original operation
identity, precondition, receipt and audit acknowledgement separately. The route-set
tool manages GET/HEAD; it does **not** issue or atomically combine evidence renewal.

Prepare a plan:

```sh
node tools/static-release/route-set.mjs plan --cli /opt/lsf/bin/latent --config /etc/lsf/operator.json --profile operator --node example-node --intent routes.json --journal release-state/docs.json
```

Review the generated plan, including `auditCapacity`, then apply it using the same
connection arguments. Apply samples capacity again before each new dispatch;
those observations still are not reservations:

```sh
node tools/static-release/route-set.mjs apply --cli /opt/lsf/bin/latent --config /etc/lsf/operator.json --profile operator --node example-node --journal release-state/docs.json
```

The journal contains manifests, generations, stable operation IDs, receipts,
audit acknowledgements and bounded diagnostic reasons; it contains no credentials.
Keep it private and preserve it with your CI job's recovery artifacts. The
configured endpoint, profile, node and tenant are bound to the journal.
Credentials may rotate within that same authorized connection.

## Understand the result

| Status | Meaning and next step |
| --- | --- |
| `planned` | Current publication eligibility and an unchanged route snapshot were checked; no mutation was sent. Review the advisory capacity report before apply. |
| `complete` | One coherent current route snapshot matches the intended set, and the publication was checked eligible. |
| `partial` | Some progress or the configured write budget was observed; GET and HEAD may select different publications. Inspect the reason before continuing. |
| `uncertain` | A mutation or its durability cannot be confirmed. The tool will not replace or replay that request automatically. |
| `failed` | The plan or a known operation was rejected, or a pre-dispatch prerequisite was unavailable. Inspect live state and the reason before preparing new intent. |

The per-route `operations` observations retain original operation IDs and
preconditions and distinguish `confirmed`, `rejected` and `pending` attempts.
Confirmed receipts and audit acknowledgements remain independent facts. A safe
`audit-journal` reason identifies audit pressure, not by itself whether a mutation
executed. Generic `resource-exhausted`, missing audit records, cancellation and
lost responses are not interchangeable with affirmative pre-mutation rejection.

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

| Renewal progress | Recovery boundary |
| --- | --- |
| Preflight blocked before dispatch | No new mutation ID was created by that refusal. Address pressure, then recheck current evidence, authorization and routes before explicit continuation. |
| Evidence committed; GET not dispatched or rejected | Preserve the renewal receipt; evidence is not rolled back. Inspect the original route journal before a new plan. |
| GET confirmed; HEAD rejected for audit pressure | GET remains committed. Perform supported maintenance as needed, retain the rejected HEAD attempt, then explicitly create a new plan in a new journal after current-state checks. The old non-conflict rejection is not silently retried. |
| Any dispatched step has no established outcome | Keep its original ID and preconditions. Recover from its operation owner's exact retained receipt. Epoch rollover, visible desired state or missing audit history does not establish nonexecution. |

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
