# Recipient continuation and signal producer inventory

This is an implementation plan against merged #1319, not an installed profile
or a new allowance. All inputs come from the already authenticated maintained
Linux 6.12.113 archive. The original 512 KiB bank, 192 KiB infrastructure tail,
256 records, 64 owners and 96/64 KiB TCP/DNS reservations remain unchanged.

## Actual lifetime boundaries

`netlink_broadcast_filtered` retains `info.skb` until all `do_one_broadcast`
calls return. That original LIVE birth can carry explicit source through inline
delivery and overrun notifications even when a receiver concurrently frees a
delivered clone. Classification must use that retained original, not dereference
the possibly freed clone after `skb_queue_tail`.

`netlink_recvmsg` has a different boundary: its original `skb_free_datagram`
precedes `netlink_dump`, `scm_recv` and `netlink_rcv_wake`. An extra `skb_get`
would postpone `sock_rfree` and change the original rmem/dump threshold. The
receiver therefore needs a separate same-bank continuation admitted while the
actual SKB is still held, before its original physical final-free point. Its
record must retain the same original PCI generation until the real post-free
tail returns. Reservation failure cannot become ordinary heap work or a
successful receive; original ownership remains quarantined if safe completion
cannot be established. No source field may survive after the corresponding
continuation returns.

## Grouped producer graph

1. Delivery and error paths: `__netlink_sendskb`,
   `netlink_broadcast_deliver`, `do_one_broadcast`, `netlink_overrun`,
   `netlink_rcv_wake`, `netlink_recvmsg`; original queue/rmem/socket references,
   receiver selection, cross-namespace checks, filtering and error propagation
   remain. `cb_running` invokes the separate real dump producer; it must not be
   treated as an allocation-free callback or silently skipped.
2. Socket notifications: actual `sock_def_readable`, `sock_def_error_report`,
   `sk_wake_async_rcu` and `sock_wake_async`. Known default callbacks may use
   explicit source-passing private copies. Unknown callback identities must
   refuse before publication or before their unclosed invocation, never be
   called under a factory/pool lock or replaced with a successful stub.
3. Wait callbacks: original `__wake_up_common` holds the actual waitqueue lock
   while invoking entries. The known `default_wake_function`, `pollwake` and
   `ep_poll_callback` chain includes real task wakeup, nested epoll, power and
   io_uring paths. A preflight outside that lock would race with registration;
   a replacement must authenticate callback identity in its real lock extent.
   No pool lock may span those callbacks. Scheduler/trace/queued work is still
   an explicit physical closure obligation.
4. Async notification: `kill_fasync` -> `kill_fasync_rcu` -> `send_sigio` ->
   `send_sigio_to_task` -> `do_send_sig_info` -> `send_signal_locked` ->
   `__send_signal_locked` -> `__sigqueue_alloc`. Preserve fasync/fown/RCU and
   sighand lock extents, actual credentials/namespace rewriting, RLIMIT and
   ucounts, coalescing and the original RT-to-SIGIO fallback. Only the actual
   allocating call receives explicit source; there is no per-task allocator
   override or implicit authorization of unrelated nested signals.
5. Signal final return: every real `__sigqueue_free` route (dequeue, flush,
   failed delivery and task exit) must classify private storage before the
   ordinary slab free. Private queue entries retain the original PCI owner
   until this actual return, not sender completion, root close or signal
   acceptance. Original preallocated-signal handling and normal allocation
   paths remain unchanged.
6. Mandatory security: `sigio_perm` calls
   `security_file_send_sigiotask`, whose actual SELinux hook calls
   `avc_has_perm(..., SECCLASS_PROCESS, ..., NULL)`. This can allocate AVC and
   audit descendants. The existing application-context AVC allocator is not a
   NodeFixed owner and cannot silently serve this device path. Explicit
   same-bank propagation through these real hooks is required; unknown active
   hooks remain unsupported before the unclosed invocation. Permission denial
   is preserved and never converted into success.

The selected original configuration keeps TRACEPOINTS, PERF, FTRACE, IO_URING,
SIGNALFD, SELinux and audit enabled. It supplies no absence certificate for
instrumentation or optional wait callbacks. `trace_sk_data_ready`,
`trace_signal_generate`, task wakeup and signalfd/epoll effects must be accounted
or excluded by an actual synchronized admission fence; a racy static-key read
or configuration disable is not accepted evidence.

## Finite source checkpoint and controls

First bind the actual retained sender and independent receive-tail lifetimes,
with source-passing declarations and same-bank, before-dispatch admission.
Then wire signal allocation/final-return and mandatory hook/cache descendants
as one coherent group. Keep incomplete callbacks and profile selection visibly
uninstalled until that group closes. Do not dispatch another object campaign
for declarations or a standalone metadata prerequisite.

Causal controls must cover clone consumed before sender callback, original
rmem threshold unchanged, same-generation receive tail after SKB return,
exhaustion before publication/processing, late tail after root close, foreign
or stale sources, RT allocation refusal with the original SIGIO fallback,
dequeue/task-exit final return, real LSM denial and unknown callback refusal.
Supplemental serialized C controls cannot establish Linux concurrency,
physical queue capacity, allocator final-free or provider installation.
