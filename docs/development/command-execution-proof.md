# Actual command execution proof

The bounded Rust authoring gate compiles the maintained `transactional-aggregate`
guest and then executes it through the authenticated `LocalTransactionRuntime`,
production activation manager, Wasmtime backend, protected store, current policy
and atomic commit path. Its native cases use a trusted local publication; signed
publisher/builder and clean-host packaged qualification remain separate gates.

`LSF_TRANSACTION_GUEST_ROOT` names the output of
`tools/compile_transaction_guests.py --language rust`. The fixture checks the
actual component digest and captured template/WIT identities. Its contract
descriptors are derived by the maintained packager from the exact application,
state and intents WIT, then checked against the compiled component and explicit
Phase 4 manifest profile before publication or deployment. Preparation must
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

Further cases cover authorized original/delegated/shared caller scopes, namespace
recreation and stale incarnation denial, retained history blocking destruction,
and zero/oversized results under finite retention ceilings. The Rust compiler also
captures a controlled `result-boundary` authored variant, with unchanged SDK,
state/intent imports, grants and request limits. It stages real business state and
an intent, then returns four bounded strings whose canonical JSON body is exactly one
MiB or one byte larger. Separate cases require the maximum body to commit and
replay byte exactly, and the oversized body to preserve its pending identity
without any partial state/effect commit. The backend observer checks the actual
returned byte count or the unchanged typed-output size rejection before atomic
result validation. This variant's different
export result type belongs to its own isolated qualification publication; it is
not a compatible replacement for the ordinary aggregate contract.

An additional bounded schedule starts owned real children for pending, committed
and rejected commands. Each child executes the maintained guest once, then exits
without Rust destructors or node shutdown. The parent positively reaps the exact
child and reopens the protected engine. Original command/attempt/result/state
bytes and effect identities survive. Both an unqualified boot clock and a large
unqualified wall-clock jump keep the actual dispatcher closed. Private child
probes, bounded process logs and crash-recovered state remain at the printed
evidence root; no historical checkpoint alone grants boot continuity.

Two further schedules create actual concurrent OCC conflicts in the maintained
aggregate guest. The node consumes the opaque physical retirement proof only
after the old guest, native views/work and commit roles have retired. It then
persists technical-abort metadata through a finite recovery worker/reservation,
under the original captured permission, numeric ceilings and deadline intersected
with current policy. This writer cannot reopen a guest or renew its frozen ledger.
Cancellation, unknown acceptance and other failures retain conservative pending
or recovery dispositions rather than automatically obtaining a retry fence.

The explicit wire retry constrains its command, prior attempt/transaction and
server-owned abort proof to the validated durable row before atomic retry
admission. The actual request-ID receipt, original fingerprint/source, generation
CAS, finite attempt/window limits and linked history remain enforced. One case
recovers an aborted record across a clean owner restart and compatible deployment
change, rejects forged associations, coalesces duplicate explicit retries and
refuses a rival request without altering the legitimate owner. Another produces
two real aborts, then recovers an earlier request's immutable attempt while the
later guest is paused and after it commits. The strict response association rejects
an old or substituted attempt for a new explicit retry. Counts independently
cover real guest Stores, state rows, terminal records and exact effect receipts.
These schedules require Native execution; source checks alone do not qualify them.

Two bounded refusal schedules additionally advance the same-process result clock
to expiry while retaining protective command/effect identity, and produce the
configured maximum of three real aborted attempts before refusing a fourth.
Original history, current read denial, execution/Store counts, state and effect
counts stay explicit. Neither a clock advance nor capacity/attempt refusal grants
a new mutator or changes the original declared horizons.

These cases complement the durable waiter and host/storage schedules. They do
not alone close #387: namespace history reclamation and qualified process-loss
replay have independent
acceptance requirements. The owned-child schedule proves physical process loss
and conservative boot handling; authorized replay on a qualified new boot still
requires the production checkpoint/time recovery owner.
