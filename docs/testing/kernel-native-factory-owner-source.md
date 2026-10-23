# Native factory descriptor and constructor route

This source joins the existing paid constructor to a real protected descriptor.
Normal installation remains Unsupported and the production socket consumer is
NULL. The committed constructor qualification predicate returns zero. An
isolated VM programme may record the exact single-body zero-to-one projection;
there is no runtime, environment, operator or guest enable switch.

The qualification startup reserves the original node 1 MiB allowance, one
existing typed provider client and one maintenance connection before opening
`/dev/lsf-stream-factory`. The original maintenance deadline bounds worker
admission and the response waiter. The admitted blocking job retains its actual
owners if that waiter disappears. Failed/late opens and protocol errors close
their descriptor on that physical job and quarantine the original backing and
connection. Ready-owner Drop submits close to the same finite cleanup table.
Failed cleanup admission keeps the descriptor open in original quarantine.
Successful close also retains backing: close is not physical final-free.

Wire v2 uses explicit little-endian scalars, without pointers or free tickets:

| Frame | Fixed fields |
| --- | --- |
| Request, 24 bytes | magic `0x4c534646`, version `2`, operation u32, reserved zero u32, absolute CLOCK_MONOTONIC expiry u64 ns |
| Status, 24 bytes | magic, version, state u32, positive errno u32, original expiry u64 |
| Diagnostic, 104 bytes | status followed by ten original u64 observations described below |

Operations are BEGIN=1, WAIT=2 and CLOSE_REQUEST=3. States are fresh=0,
pending=1, ready=2, quarantined=3 and closed=4. The first BEGIN fixes one expiry
and rejects more than the existing 120-second maintenance ceiling before child
birth. Repeated BEGIN, widened expiry and concurrent constructor operations
refuse. Pending and busy are published before releasing the factory mutex for
the real constructor/wait. WAIT cannot grant late readiness. CLOSE_REQUEST is
allowed after expiry and requests the same actual destroy route while retaining
the descriptor for observation. CLOSED is an admission state.

The diagnostic snapshots the original ledger under its pool lock. Its ten u64
fields are lifecycle, final phase, request users, task claimed, Control readers,
Control retiring, live records, queued records, request returned and flags.
Flags are stopped=1, pool poisoned=2, uncertain=4 and context poisoned=8.
Source-derived positive terminal expectations are `8,5,0,2,0,1,1,0,1,1`:
the original Root remains live while the private Task, request, Control and
their children have returned. These are intended VM assertions, not measured
runtime evidence or permission to refund the Root.

Only actual kthreadd dispatch of an authenticated original request with the
immutable physical-provider role reaches the full creator. Ordinary and legacy
requests preserve their original paths. Version 1 socket operations require
real readiness and still have no selected production consumer.

The [verified Linux receipt](evidence/kernel-native-factory-owner-linux-2026-10-23.json)
records ten registered and executed controls, zero failures or ignored cases,
and the original thirty stream cases filtered for this focused programme. Run
39885802954 tested source `abd96e62028e60e3e54b5d6597b3209001dadb5f`
with Rust 1.97.1. Its sole artifact passed archive CRC, digest and all 36 Git
source-material checks. The receipt preserves the earlier compile failure and
nine-pass/one-failure attempt as failures. The final test fix retries only the
original transient capability-busy inspection result within the test deadline.
The composed development CI repair preserves all owning input bytes.

These controls cover real ordinary Linux descriptor ownership, quota refusal,
failed open, post-open failure, timeout, abandoned waiters, close, cleanup
capacity refusal and constructor/cleanup panic. This programme does not execute
the custom kernel or its constructor; its opened files are ordinary Linux test
descriptors. Full link/boot, actual constructor and cancellation, complete
bootstrap geometry, all physical child returns, Root final-free, deadline
execution bounds and production enablement remain separate required evidence.
