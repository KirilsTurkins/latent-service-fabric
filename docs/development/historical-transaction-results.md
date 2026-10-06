---
title: Historical transaction results
---

An original committed or rejected command keeps its original source, caller,
fingerprint, attempt, result bytes, effects and committed view token. A compatible
publication or reviewed schema/restore change does not turn that token into a
minimum view for a new query.

Result recovery uses a separate read path. The coordinator first authorizes the
current installed result scope and reads the actual retained command metadata.
`ReviewedResultHistory::capture` checks the same physical snapshot's command,
namespace incarnation, ready namespace history and reviewed global restore guard.
It validates the original token against the original stored schema and committed
version. A changed history requires an actual retained history row. Pending work
keeps the ordinary history checks and cannot enter this terminal-result path.

The runtime then selects the exact original signed companion and live original
publication. It obtains a current `read-result` decision for that publication and
the original caller, entity and result policy. `seal_result_retained` creates an
inspection authority that permits only result reads. It cannot invoke the old
component, start a query, stage an intent, retry an aborted command or commit a
new mutation. Revoked or missing original publications and unsupported retained
result formats remain refused.

Before replay and again before delivery, a fresh storage observation checks the
captured current schema/recovery history, and the existing short policy/lifecycle
fence checks present authority, cancellation and the original deadline. Ordinary
business generation advances do not replace the original result or its token.
Another schema/restore transition requires a newly authorized result observation.
The actual socket polls retain that delivery fence; they perform no native
storage or blocking I/O and do not renew the activation budget.

Retention remains independent. An expired body is reported as an expired original
receipt. This path does not reconstruct bytes from the current aggregate, create
a new result, extend a horizon or renew dispatch authority. State/query minimum
tokens continue to require the current schema and recovery epochs.

Three focused Linux cases use the actual embedded engine and policy/publication
owners. They cover explicit review/resume of test-controlled paused histories,
original receipt preservation, stale-query denial, wrong caller, read revocation,
refusal of command authority, a subsequent history change and expired bodies.
These cases do not establish signed Java execution or clean-host distribution.
The Java HTTP campaign must separately execute the preserved components through
the normal node and management paths.
