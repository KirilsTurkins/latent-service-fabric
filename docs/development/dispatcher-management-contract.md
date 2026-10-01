---
title: Dispatcher management contract
---

# Dispatcher management contract

The installed dispatcher has one explicit node scope. The three methods in
`latent.control.v1.DispatcherService` are `InspectDispatcher`,
`ControlDispatcher`, and `GetDispatcherOperation`. Authentication supplies the
node operator and stable actor tenant. Knowing an epoch, operation ID, receipt
or namespace does not supply control authority.

Inspection reports the current logical pause/control state and actual ownership
counters. Durable effect counts carry their last native observation time; the
response does not claim an atomic observation across different owners. Pending
control and restored-history review keep admission paused. Pause closes new
provider admission, while already accepted claim/send/cleanup may finish.

Control carries one original operation ID, action, and positive owner epoch and
revision. The revision must have a representable successor. Its durable receipt
retains the authenticated actor, original action, before/after generation, exact
receipt digest, clock facts and committed disposition. Publication of a pause or
resume describes logical admission and supplies no physical-retirement proof.

After a lost response, receipt lookup carries the exact original control request.
Current node-operator access is required before lookup and delivery. Historical
lookup does not publish an old resume, refresh a precondition, or clear restore
review. Generic resume rejects pending/uncertain controls, quarantined owners,
unproven clock continuity, and restored-history review.

Each response carries an independent audit acknowledgement. Typed node audit
records retain the original epoch, actor tenant and revision, without business
payloads, credentials or provider targets. New audit fields are absent on
historical records; their existing canonical bytes remain unchanged. Explicit
null, unrelated target hybrids and reassigned terminal identities fail closed.

`sdk/profile/transaction-requirements-v1.json` records exact dispatcher and
supporting common/audit protobuf source digests. WIT host and preparation profile
digests remain independently versioned. This definition milestone and its pinned
Protobuf compiler check do not establish real-node management qualification;
the native gateway and CLI are qualified separately by their executable tests.

The gateway installs a sealed management handle from the existing dispatcher
and verifies that it uses the same protected engine. It captures the original
node-operator decision and global recovery reservation before returning the
operation future. The native writer holds policy, dispatcher lifecycle and the
original reservation's currentness fence through logical acceptance, then
releases those locks before committing the receipt. Receipt lookup uses the
same engine's reserved recovery reader. Accepted worker completion and response
frames retain the original request owner after the caller disappears.

The CLI requires an explicit node scope:

```shell
latent dispatcher inspect --scope node
latent dispatcher pause --scope node --operation-id control-42 --expected-owner-epoch 7 --expected-revision 3
latent dispatcher resume --scope node --operation-id control-43 --expected-owner-epoch 7 --expected-revision 4
latent dispatcher operation --scope node --operation-id control-42 --original-action pause --expected-owner-epoch 7 --expected-revision 3
```

The final command recovers the original receipt without submitting another
mutation. Epochs and revisions remain lossless decimal strings in CLI output.
Portable tests cover exact RPC validation, CLI preparation and real-engine
acceptance/denial schedules. The native gateway schedules use authenticated
contexts, the installed dispatcher, its protected engine, global recovery
capacity and the actual audit journal. They exercise original policy capture
before polling, revoke/reallow without reviving an old decision, current access
to the unchanged historical receipt, and audit closure preventing mutation.
An accepted audit conclusion followed by a durable journal query supplies the
readiness witness before another critical operation; the tests do not infer
readiness from the caller having received an error.

Full authenticated CLI-to-node qualification,
manual effect reconciliation and restored-store operations remain separate
requirements of issue #400.
