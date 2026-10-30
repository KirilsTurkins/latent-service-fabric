# Renew static-site evidence without losing audit history

Use this runbook for an already published static site, including a site whose
GET and HEAD routes need recovery after audit capacity exhaustion. For a first
publication, start with [release an existing frontend build](static-release-workflow.md).

**Version boundary:** audit-aware preflight, the `audit-journal` inventory row,
and the local maintenance/archive commands below describe current development,
not the released alpha.4 or alpha.5 binaries. Use a reviewed matching node, CLI
and helper checkout that includes these changes. Do not point a newer helper at
an older node and interpret missing counters as spare capacity. The earlier
[evidence-renewal command](../reference/operator-cli.md) remains distinct from
these new maintenance commands. Check your installed commands with `--help`.

## Two different operations

| Operation | Node state | What it changes |
| --- | --- | --- |
| `web renew-evidence` | Running and ready; authenticated management connection | Revalidates evidence for the exact stored package and advances the publication lifecycle generation. It does not change the package bytes or publication ID. |
| `audit maintenance rollover` | Stopped, including automatic restart supervision; exclusive filesystem ownership | Seals the active audit epoch and creates a linked successor with free active-epoch record capacity. It does not renew evidence, reset global sequence numbers or make a publication eligible. |

There is no automatic renewal scheduler, rollover, pruning or background archive
export. Schedule renewal early enough for signing, verification, competing
traffic and any maintenance outage. A ten-minute cadence is an example, not a
safe default for every policy. Signed validity, proof age, trust/revocation
freshness and audit headroom are independent constraints. Neither operation
bypasses current authorization, revocation or publication retirement.

## 1. Prepare a private recovery directory

Run from the matching LSF checkout in Bash on Linux, using Node.js 24 and Python
3.12 or newer. The live commands need an operator profile authorized for node
inventory and the publication's tenant. Management remains on private loopback:
run in the node's network namespace or use the supported
[private CI runner workflow](headless-publication-ci.md), not a public endpoint.

Replace the paths, node ID and digests below. The parent operator directory must
already be private and owned by the current operator. Prepare the complete
`routes.json` using [route-set reconciliation](static-route-sets.md); its tenant,
publication ID, GET/HEAD IDs, hostname and path must describe the intended site.
`EVIDENCE` is the selected evidence directory, prepared in step 3 before dispatch.

```bash
set -euo pipefail
set -C
umask 077
CLI=/opt/lsf/bin/latent
CONFIG=/srv/latent-operator/operator.json
PROFILE=operator
NODE_ID=example-node
PUBLICATION='publication:sha256:REPLACE_WITH_64_LOWERCASE_HEX_DIGITS'
PACKAGE_DIGEST='sha256:REPLACE_WITH_64_LOWERCASE_HEX_DIGITS'
EVIDENCE=/srv/latent-operator/evidence/renewal-001
CYCLE=/srv/latent-operator/renewal-001
PUBLIC_URL=https://docs.example.com/docs/
mkdir -m 700 "$CYCLE"
install -m 600 /srv/latent-operator/routes.json "$CYCLE/routes.json"
```

Choose a new directory for a **new decision**. `mkdir` and noclobber (`set -C`)
intentionally refuse to overwrite an earlier cycle's files. After interruption,
restore the original directory and selectors; do not rerun this setup to invent
a new operation. Do not run competing jobs against the same recovery journal.
Retain recovery files and selected evidence on durable private operator storage,
not an ephemeral CI workspace. Never upload credentials or signing keys with them.

## 2. Check audit headroom before dispatch

```bash
node tools/static-release/route-set.mjs preflight \
  --cli "$CLI" --config "$CONFIG" --profile "$PROFILE" --node "$NODE_ID" \
  --intent "$CYCLE/routes.json" --journal "$CYCLE/routes.journal.json" \
  --diagnostic-records 2 --competing-operations 1 \
  --warning-percent 80 --cadence-minutes 10 > "$CYCLE/preflight.json"
```

This reads live authenticated inventory; it does not create a route journal,
reserve records or dispatch a mutation. The CLI's JSON inventory includes the
fixed `audit-journal` topology entry with profile `audit-capacity-v1`. Missing,
duplicate or unavailable observations are not zero usage. The detailed
[preflight contract](static-route-sets.md#preflight-audit-capacity-before-renewal)
explains the counters and options.

| Result | Exit status | Next step |
| --- | ---: | --- |
| `headroom-observed` | 0 | Review the sample, then continue. Capacity can change immediately afterward. |
| `warning` | 3 | Stop this automated sequence and arrange maintenance or an explicit operator decision before expiry/exhaustion. |
| `blocked` | 4 | Address the reported resource/owner condition; do not dispatch renewal. |
| `unavailable` | 5 | Restore a trustworthy observation; do not treat missing counters as free capacity. |

Invalid inputs or local storage failures also stop the command. With `set -e`,
nonzero results stop the example; do not append `|| true`. The helper permits an
explicit apply after a warning, but this runbook deliberately stops for review.

One renewal **plus two actual route mutations** consumes at least six critical
records: one attempt and one outcome for each mutation. The example adds two
diagnostics and one competing critical operation, budgeting ten records and
160 KiB. Reservations already charged to the owner are deducted. This is neither
a forecast of all other traffic nor a reservation. At ten-minute cadence, six
records per cycle alone would consume 864 records/day; the default 4,096-record
epoch would last about 4.74 days from empty, before other producers. These are
arithmetic planning figures, not measured uptime guarantees.

A renewal of the same publication does **not** by itself require rewriting
unchanged GET/HEAD manifests. The route helper observes already matching routes
without sending apply requests. Its preflight still uses the conservative full
cycle budget; do not use a no-op expectation to bypass native admission.

When headroom requires rollover, follow step 5 first, then repeat the live
preflight into a new observation file after restart. Filesystem space alone does
not supply exhausted record slots.

## 3. Renew the exact publication once

Use evidence that is still valid under the node's current policy. When signed
statements or trust material need replacement, obtain fresh organization approval
and sign the **unchanged prepared package** into a new directory using the
[approval and signing procedure](static-release-workflow.md#approve-and-sign-the-exact-release).
Keep the package digest and publication ID unchanged. Do not edit timestamps in
signed files, reuse expired approval, weaken proof-age policy or copy an old
verification result as current authority. Local verification is a check, not node
admission. Preserve the exact selected evidence files for later investigation.

Read the current generation, even when eligibility has become stale:

```bash
"$CLI" --config "$CONFIG" --profile "$PROFILE" --output json \
  web get --publication "$PUBLICATION" > "$CYCLE/publication-before.json"
```

Review the returned publication, package identity and lifecycle state. A revoked
or retired publication is not repaired by renewal. Record the exact request
before the only dispatch. The following creates a private operator note, **not**
a new CLI input format or a route-set journal. It retains no token or key bytes.
It refuses an unsuccessful/mismatched observation and an existing note.

```bash
python3 - "$CYCLE" "$CONFIG" "$PROFILE" "$NODE_ID" "$PUBLICATION" "$PACKAGE_DIGEST" "$EVIDENCE/index.json" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys

cycle, config, profile, node, publication, package, evidence = sys.argv[1:]
root = Path(cycle)
observed = json.loads((root / 'publication-before.json').read_text())
assert observed['schemaVersion'] == 'latent.cli.result.v1'
assert observed['category'] == 'success' and observed['outcomeKnown'] is True
record = observed['data']['record']
assert record['publication']['id'] == publication
assert re.fullmatch(r'publication:sha256:[0-9a-f]{64}', publication)
assert re.fullmatch(r'sha256:[0-9a-f]{64}', package)
generation = record['generation']
assert isinstance(generation, str) and re.fullmatch(r'[1-9][0-9]{0,19}', generation)
assert int(generation) < 2**64 - 1
with Path(evidence).open('rb') as stream:
    index = stream.read(16385)
assert 0 < len(index) <= 16384
note = {'operationId': 'renew-' + secrets.token_hex(16),
        'expectedGeneration': generation, 'publication': publication,
        'packageDigest': package, 'evidenceIndex': evidence,
        'evidenceIndexSha256': hashlib.sha256(index).hexdigest(),
        'configPath': config, 'profile': profile, 'nodeId': node}
with (root / 'renewal-intent.json').open('x', encoding='utf-8') as stream:
    json.dump(note, stream, indent=2)
    stream.write('\n')
    stream.flush()
    os.fsync(stream.fileno())
descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY
OPERATION=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["operationId"])' "$CYCLE/renewal-intent.json")
GENERATION=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["expectedGeneration"])' "$CYCLE/renewal-intent.json")

"$CLI" --config "$CONFIG" --profile "$PROFILE" --output json \
  --rpc-timeout-ms 30000 web renew-evidence --publication "$PUBLICATION" \
  --package-digest "$PACKAGE_DIGEST" --evidence "$EVIDENCE/index.json" \
  --operation-id "$OPERATION" --expected-generation "$GENERATION" \
  > "$CYCLE/renewal-result.json"
```

Do not change the selected evidence or request fields between recording and
dispatch. The digest in the note identifies the index only; retain its referenced
evidence files too. The native command checks their contents and current trust.

Inspect `category`, `outcomeKnown`, `data.operation` and `data.auditAck` separately.
A committed receipt must identify the original operation and publication and the
resulting lifecycle generation. A catalog commit is not undone by an unavailable
or unknown audit acknowledgement. Stop for reconciliation rather than assuming
that a nonzero exit means no mutation happened.

Read-only recovery and currentness checks use the same connection:

```bash
"$CLI" --config "$CONFIG" --profile "$PROFILE" --output json \
  web operation "$OPERATION" > "$CYCLE/renewal-operation.json"
"$CLI" --config "$CONFIG" --profile "$PROFILE" --output json \
  web get --publication "$PUBLICATION" > "$CYCLE/publication-after.json"
```

For a lost response, restore `OPERATION` from `renewal-intent.json` and run the
lookup, **not the renewal command**, first. Preserve every response in a new
file. Require an established original outcome and current eligibility before
continuing. The route helper checks `RELEASE_LIVE_ELIGIBILITY_ELIGIBLE` with
`RELEASE_ELIGIBILITY_REASON_VERIFIED`; a historical receipt alone is insufficient.

## 4. Reconcile GET and HEAD and check the public site

For a new, reviewed route decision, use the same intent and a new route journal:

```bash
node tools/static-release/route-set.mjs plan \
  --cli "$CLI" --config "$CONFIG" --profile "$PROFILE" --node "$NODE_ID" \
  --intent "$CYCLE/routes.json" --journal "$CYCLE/routes.journal.json" \
  > "$CYCLE/route-plan.json"
```

Review the plan before this separate step:

```bash
node tools/static-release/route-set.mjs apply \
  --cli "$CLI" --config "$CONFIG" --profile "$PROFILE" --node "$NODE_ID" \
  --journal "$CYCLE/routes.journal.json" > "$CYCLE/route-apply.json"
node tools/static-release/route-set.mjs status \
  --cli "$CLI" --config "$CONFIG" --profile "$PROFILE" --node "$NODE_ID" \
  --journal "$CYCLE/routes.journal.json" > "$CYCLE/route-status.json"
```

For an interrupted route decision, restore its **original** journal and run
`status` first; do not plan over it. The helper retains the original IDs,
preconditions, receipts and audit acknowledgements. It resamples capacity before
each new dispatch, but evidence renewal, GET and HEAD are not one transaction.
Already matching routes are observed without rewriting them.

Require `complete`/`observedComplete: true` for the intended set, then check the
actual public hostname through its normal edge:

```bash
curl --fail --silent --show-error --max-time 15 \
  "$PUBLIC_URL" -o "$CYCLE/public-get.html"
curl --fail --silent --show-error --max-time 15 --head \
  "$PUBLIC_URL" > "$CYCLE/public-head.txt"
```

Check the expected content, HEAD headers, a direct deep link and a browser reload;
a 200 response alone does not identify the intended version or prove CSP behavior.
Signed validity failures can produce HTTP 403; a stale positive verification
proof is a different currentness failure and currently maps to HTTP 503. Inspect
the native eligibility reason rather than diagnosing audit exhaustion from HTTP
status alone. Maintenance and renewal never authorize serving ineligible bytes.

## 5. Rollover before exhaustion, then return to live renewal

The [stopped-node audit-journal runbook](audit-journal-lifecycle.md#executable-stopped-owner-workflow)
is the command-by-command procedure. Use a separate new private maintenance
directory, not the route journal, and perform these steps in order:

1. Pause publication jobs and other administrative writers. Stop the whole node
   and its service/container restart supervisor. Verify actual process exit;
   a shutdown timeout is not proof that the audit owner released its root lock.
2. As the effective UID owning the private journal, run local `status`. Retain
   its `journalId`, active `epoch`, `nextSequence`, and a new 32-character lowercase
   hexadecimal maintenance operation ID before dispatch. Local commands must
   not receive `--config`, `--profile`, endpoint or RPC-timeout arguments.
3. Run `rollover` with that exact epoch, operation ID and explicitly selected
   archive root. A healthy full-record journal does not need a spare ordinary
   audit reservation for this transition. It still needs real filesystem space.
4. Require confirmed durability and verify the exact archived epoch. Compare the
   returned successor/sequence/seal with the original status and receipt. Keep
   original `MODE`, `HEAD`, record bytes and the sealed history; never replace
   the journal with an empty directory.
5. Restart the matching node with durable audit enabled. Honor the persisted
   restart clock floor and check authenticated readiness. Recheck live headroom
   and publication eligibility; rollover did not extend either evidence lifetime
   or proof freshness. Return to step 2, then renew only as a new explicit decision
   or recover an already dispatched original request.

Local custody is finite: four epochs and 1 GiB of record bytes. Before another
archive cannot fit, use the [verified oldest-archive transfer](audit-journal-lifecycle.md#verified-transfer-and-local-capacity-release)
to an independently provisioned private destination. The command verifies durable
external custody before releasing the corresponding local copy. Do not use
`rm`, directory moves, manual marker edits or a missing destination as permission
to discard history. Provision filesystem overhead separately from record bytes.

Unrolled version-1 journals are readable by this implementation. Once a rollover
writes version 2, an older binary may reject it: do not downgrade by replacing
`MODE` or deleting history. Maintain backups and a tested matching runtime plan.

## Recovery decisions

| Last established observation | Safe next action |
| --- | --- |
| Preflight blocked before dispatch | No mutation was sent by preflight. Address the reported condition and take a fresh observation. |
| Renewal committed, routes incomplete | Retain the renewal receipt and independent audit acknowledgement. Inspect the original route journal; do not renew again merely because routing stopped. |
| GET committed, HEAD affirmatively rejected for audit pressure | GET remains committed. Maintain the journal as required, preserve the rejected attempt, then explicitly plan from current state in a new route journal. The helper does not silently retry that non-conflict rejection. |
| Lost reply, unknown/evicted receipt or unconfirmed durability | Stop automatic writes. Query the exact original operation and retain its original ID/preconditions. Desired live state or a new audit epoch does not prove that the request did not execute. |
| Generation conflict with a known rejection | Read fresh state and review a new decision. Do not alter an old request's precondition while keeping its operation ID. |
| `audit-critical-pending` or `audit-maintenance-reopen-required` | Use the original node's recovery path as directed by the maintenance runbook; missing receipts stay unknown and never authorize replay. |
| `audit-maintenance-resume-required`, interrupted rollover/transfer or lost maintenance reply | Wait for the physical owner to exit; keep the node stopped and resume only the original maintenance operation with unchanged paths and selectors. |

For automation, serialize the renewal job and maintenance for the shared node,
keep signing authority separate, and retain failed/partial outcomes for the next
operator. Alert on warning, blocked and unavailable results. Never implement a
blanket retry of a mutation, change an uncertain operation's identity, or treat a
completed history transfer as proof of current publication eligibility.
