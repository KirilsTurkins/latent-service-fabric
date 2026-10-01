# Transaction host and original activation ownership

The transaction host extends the existing activation manager and Wasmtime
backend. A trusted state runtime supplies `TransactionActivationAdmission` to
`start_transaction_with_deadline`. Ordinary starts retain their existing
behavior. The manager resolves and admits the original principal and revision,
then calls the transaction admission before preparing code or assigning a cell.
Strict transactions require the explicitly configured Phase 4 budget profile,
zero child calls and zero outbound requests. Queries additionally require zero
state writes and zero intents. The supplied host must retain that exact
activation ID and `ActivationBudget` instance.

`WasmtimeConfig::transactional_state` installs the frozen Phase 4 linker only
when explicitly enabled. Components importing state or intents select its exact
versioned interfaces, mixed synchronous/asynchronous signatures, and affine
resource shapes. Staging borrows the original state's transaction resource.
Immediate-effect imports are rejected on this surface. Stateless components
continue to select the frozen Phase 3 ABI. Prepared and native cache identities
include the explicitly installed transaction profile and its digest.

Canonical lowering and native pages retain the host's real byte owner. A page
has at most 128 entries and 1 MiB, and the host resource table limits live pages,
page bytes and retained lowering buffers. Resource IDs are never reused within
an activation. Every operation rechecks the selected mode and current read
authority. The real Wasmtime Store destructor closes guest access only after
dropping page and lowering owners; this observation does not prove physical
store I/O retirement or durable commitment.

The Phase 4 accounting profile enables state read bytes, state write bytes and
intent count on the original ledger. Backend reports cannot invent those host
counters. `HostMemoryReservation` reserves actual native buffers before
allocation against the same memory ceiling as guest growth. Final observation
freezes consumption while retaining reservations until their actual buffers
are destroyed. Unqualified descendant host-buffer delegation is rejected.

`StateTransactionHost` owns an affine `StateSession` and native snapshot on the
same protected store's fixed workers. It validates the actual Pending claim,
original activation ledger, sealed policy/publication and snapshot generation.
Read and staging costs are charged before exposing values. A detached storage
response retains the native view; retirement requires its issued destruction
witness before releasing the operation and attempt pins. Intent staging
captures the original effect grant immediately, then final envelope preparation
intersects it with current authority without extending its original lifetime.
A narrower rule after preparation prevents writer acceptance. Audit-required
profiles currently fail closed until a real audit reservation owner is installed.

`NativeTransactionAdmission` accepts only a trusted installation with verified
publication metadata, its exact deployment and companion policy bindings. It
checks the selected source and current policy before native lookup. Commands
retain the protected node's actual role guard, publish Pending before opening
guest state, and carry that same guard through final writer acceptance and
physical retirement. Replays require current result-read authority and never
open a second command host. Fresh queries open a frozen read-only snapshot and
create no Command, Attempt, Result or Outbox rows.

Each query exposes the 67-byte token captured from its actual native snapshot.
The token binds tenant, namespace, entity, schema and recovery history as well
as the original unsigned incarnation and generation. A minimum from a future
generation conflicts; a token from another schema or recovery history refuses
without refreshing the original request. A restored global guard awaiting
review denies queries and Pending admission without quarantining a healthy
physical store.

Command/result format 3 retains that same original opaque history token in the
complete terminal envelope. Later namespace changes and reopening cannot
replace it. Formats 1 and 2 explicitly reject because they omit this history.
No-state rejection and technical-abort envelopes compare both the exact
namespace-history row and the original absent or reviewed recovery guard.

The original activation handle invokes native completion after actual guest
cleanup and accounting observation, before publishing its terminal journal
entry or removing its cancellation registration. Accounting stays frozen; a
narrow retained-authority check permits no further execution or spending.
The final namespace/effect fence retains the original cancellation CAS through
acceptance. Cancellation that wins first denies the business envelope; a late
deadline, disconnect or cancellation cannot rewrite a known durable outcome.
Acceptance without a known physical result remains recovery-required. Large
result bodies stay in a once-only native completion owner, rather than being
duplicated into the bounded activation journal.

`CommandCompletion` publishes a successful state/result/intent envelope under
the original role, current policy, namespace lifecycle, effect authority and
cancellation fences. Declared rejection first retires the discarded business
state and intents, then publishes only its terminal result. Known durable
results survive a later cleanup failure. A failed activation can expose a
noncommit proof only after actual guest, native view and attempt owners retire;
an uncertain native outcome remains recovery-required.

The integrated pinned Linux campaign passed 267 library cases: State126,
Commit49 and Node92. The original activation, cancellation, namespace, atomic
and cleanup schedules remain required. Three new node schedules cover actual
future minimums, changed schema/recovery histories and paused restore admission.
Node all-target/all-feature Clippy completed without transaction-runtime
warnings. These native tests do not execute guest components.

The same protected store and dispatcher must bind the original global native
capacity owner before the first command. Physical views, writer callbacks and
actual response owners retain the finite prepaid reservation after a lost
waiter and ledger finalization. Ordinary standalone/RPC composition, authorized
response-frame release, technical-abort/replay composition, audit reservations,
all six signed guest components and crash/restart qualification remain required
for #388 and the wider gate.
