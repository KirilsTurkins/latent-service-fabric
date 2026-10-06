# Actual command execution proof

The bounded Rust authoring gate compiles the maintained `transactional-aggregate`
guest and then executes it through the authenticated `LocalTransactionRuntime`,
production activation manager, Wasmtime backend, protected store, current policy
and atomic commit path. Its native cases use a trusted local publication; signed
publisher/builder and clean-host packaged qualification remain separate gates.

`LSF_TRANSACTION_GUEST_ROOT` names the output of
`tools/compile_transaction_guests.py --language rust`. The fixture checks the
actual component digest and captured template/WIT identities. Preparation must
create zero guest Stores. Execution counts are incremented only when the compiled
guest calls the real `acquire-command` import, independently of durable state,
attempt, result, commit receipt and effect IDs. A forwarding test observer keeps
the original host, cancellation probe, budget, deadline and physical cleanup.

One case pauses the compiled guest inside its first state read. Concurrent equal
delivery observes explicit in-progress status and conflicting delivery receives
the original conflict. Dropping a duplicate or terminal response does not cancel
the original command or admit a second guest. Other cases recover committed and
rejected outcomes after stopping, draining and reopening the actual protected
owner; preserve an interrupted pending record; retain the first source across a
compatible deployment change; recheck tenant, subject and revoked permission;
accept token rotation for the same subject; enforce command key limits and
retention capacity; and keep command/effect identity after result expiry.

These cases complement the durable waiter and host/storage schedules. They do
not alone close #387: explicit retry generations, delegated/shared caller scope,
namespace recreation, oversized results and process-loss recovery retain their
own acceptance requirements. The native reopen cases establish actual persisted
owner recovery, not abrupt process or machine loss.
