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

These ports are an intermediate implementation of issue #388. The complete
state runtime must still supply authenticated companion selection, original
durable command admission, final envelope acceptance, physical cleanup and
current-authorized response release across the existing activation manager. The
six-language signed component campaign, RPC/HTTP delivery and crash/restart
qualification remain required; this page does not record them as passing.
