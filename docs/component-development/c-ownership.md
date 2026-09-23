# C capsule ownership contract

The public helpers are under
[`sdk/c-guest/include/lsf`](../../sdk/c-guest/include/lsf).
Generate `probe.h` from the application's authoritative WIT first; do not copy
an ABI declaration from an example. See [the authoring guide](c-capsule-authoring.md).

## Owners and borrows

| Value | Owner and permitted lifetime | Required completion |
| --- | --- | --- |
| Exported string/list argument | The generated export gives application code owned lifted storage | Free after its last use, or retain it in the invocation frame before any suspension |
| Borrowed literal | Static storage; never an owned generated result | Never send it to a generated free helper or transfer it as an owned export result |
| `lsf_scope_t` allocation | One initialized scope, with explicit byte and slot ceilings | Release once, detach exactly once on real ownership transfer, or close the scope in reverse acquisition order |
| Export result allocation | Application until the return; generated export/post-return owner after transfer | Detach before returning; do not free it again |
| Synchronous imported result | Caller on successful return; error payloads are owned when their type contains allocation | Visit and release all active result fields, including nested lists/options |
| Async request/result | Retained invocation frame, not the caller's transient C stack | Keep storage until the subtask returns or cancellation is terminal |
| Upload/body/chunk resource | Unique application owner after a host-returned resource | Borrow without transfer; move before a consuming import; drop exactly once when no longer owned |
| Secret bytes | `lsf_secret_t`; borrowing does not create a copy | Wipe this owner's bytes before deallocation, then free nested media/version storage |

C cannot prohibit copying a struct. Treat every scope, secret, async state and
resource guard as non-copyable after initialization. Zero-initialize guards
before adoption. Host resources must originate from the generated host call;
creating a guard around a guessed integer is not authority and is rejected by
the host. Do not adopt the same allocation twice or free a borrow.

## Bounded allocation

`lsf_scope_alloc(scope, count, width)` checks multiplication overflow, the byte
budget and the 32-entry ownership capacity before exposing zero-initialized
storage. Zero size, allocator failure or a denied reservation returns `NULL`
without charging live bytes. A failed adoption leaves ownership with its caller.
`lsf_scope_release` removes the entry before cleanup; a repeated release returns
false. `lsf_scope_close` is safe again after completion. Callbacks must neither
re-enter the scope nor start asynchronous work.

`lsf_scope_detach` transfers an owner; it does not free memory and is not a host
quota refund. `live`/`peak` count only explicitly adopted charges, not all canonical
ABI allocations or the node's resident set. The component's linear-memory
ceiling bounds its complete Wasm memory separately. On a fatal allocator failure
an application may return its declared error, or deliberately trap. A trap is
not successful application cleanup; the host then owns activation teardown.

## Recursive results

The pinned generator supplies the authoritative ABI, but an aggregate
`*_free` function is not assumed to recursively visit every aliased nested
list/option. The SDK's HTTP, service, streaming and secret helpers explicitly
visit the active nested owners and reset the released values. The native test
allocates those nested values, rejects unknown/double frees, and checks that no
allocation remains. It tests generated **actual** headers, not handwritten ABI
substitutes.

In particular, service invocation preserves three different outcomes: successful
values, a callee's declared application error, and a platform failure. Do not
collapse cancellation, permission denial or resource exhaustion into a declared
callee error. Payload/metadata ownership exists on failure too. Event receipts
must be released; uncertain publication must not trigger an implicit retry.

## Retained async frames

Use one heap frame for the exported task; put all copied arguments, requests,
result slots and resource guards in that frame or its scope **before** calling
the generated async import. `lsf_frame_enter` installs it into the canonical
task context and rejects an already occupied slot. This is task-local state,
not a deployment/global singleton or an additional scheduler.

`lsf_async_submit` distinguishes an immediate returned result from a pending
subtask. Pending work is joined to a waitable set. STARTED is progress, not
completion. A callback must match the owned task before its result can be read.
A terminal return detaches and drops the subtask; only then may its borrowed
request storage be released or reused for the next operation.

Cancellation first detaches before the canonical cancel operation. A pending
cancellation (`UINT32_MAX`) rejoins and retains the frame. It does not permit
freeing request bytes or claiming the host's budget has returned. Cancellation
can race with a returned result: `LSF_ASYNC_CANCELLED_RETURNED` means the result
is owned and must be disposed of before the frame is destroyed. Do not start
new application work during this cleanup. Terminal cancellation drops the
waitable set, releases resources/results, clears the task context, and reports
task cancellation rather than returning a fabricated success.

See [`http.c`](../../sdk/c-guest/examples/http.c),
[`streaming.c`](../../sdk/c-guest/examples/streaming.c), and
[`service.c`](../../sdk/c-guest/examples/service.c). They show immediate and
suspended completion, explicit error ownership and the returned-result race.
The native state-machine tests cover these transitions, and signed real-runtime
tests independently cover provider cancellation and subsequent cell reuse.

## Streams, blobs and secrets

An HTTP upload moves into `finish`; its guard must no longer drop that owner.
The response's metadata and body are separate owners. A read chunk can outlive
its body, so dropping a body does not make a previously returned chunk a borrow.
Explicit trailers access requires verified EOF; a second access is InvalidState,
not a second successful consumption. Cancellation after any streaming phase
must dispose of that phase's returned owned result before the pre-existing
frame owners. Bounded read sizes are still subject to host policy and remaining
budget.

Blob 0.2 chunk resources use the same explicit ownership convention. Reader and
writer IDs are WIT `u64` handles, not chunk-resource objects. Their async
close/seal operations must finish before the retained request/result is freed.
An abandoned reader/writer remains charged until actual host activation cleanup;
a C helper cannot issue an asynchronous close from a synchronous destructor.
The complete maintained blob fixture tests this distinction.

`lsf_secret_borrow` returns a const borrow. `lsf_secret_close` performs volatile
zero stores before freeing this owner's bytes and nested values. An application
copy is a different owner and needs its own wipe. A trap cannot run a C cleanup
callback; host activation disposal is the containment boundary. No promise is
made that arbitrary compiler/register copies or external host memory have been
cryptographically erased.

## Trap, deadline, abandonment and idle behavior

Successful and declared-error paths clean their explicit owners before returning.
Cooperative cancellation keeps pending work charged until terminal cleanup.
Fuel exhaustion, memory traps and noncooperative termination instead use the
existing host activation/store teardown and cell recovery contract. Do not
invoke C callbacks after the host has invalidated their frame or synthesize a
cleanup receipt merely because a client stopped waiting.

No SDK helper adds a worker thread, service process, interpreter, sidecar, warm
instance pool or deployment-resident heap. A frame exists only for an invocation;
a compiled artifact may remain in the node's shared bounded cache. The live
walkthrough distinguishes cell/quota return, retained cache ownership and
whole-process RSS. Checking one is not evidence for all the others.
