# Mandatory SIGIO security owner integration

The actual maintained `sigio_perm` invokes `security_file_send_sigiotask`, whose
SELinux implementation resolves the existing file-owner SID and recipient task
SID before `avc_has_perm(..., SECCLASS_PROCESS, ..., NULL)`. Permission denial
must remain denial. A cache hit must retain its original creator's owner. A
miss, permissive update, extended-permission descendant, mandatory audit and
SID-to-string cache allocation must not borrow an unrelated stream context.

The existing source already implements those real AVC/SID/audit algorithms for
an explicit application `lsf_factory_blob`. Its `context` member is an actual
`lsf_factory_context *`, validated by the original four application-context
lookup. A NodeFixed PCI source cannot be cast to that type, represented by a
special context pointer, or encoded as NULL with a claim of equivalent scope.

The smallest reusable integration would extend that **private internal carrier**
with a closed, explicit owner-domain tag and an actual device birth identity.
The application tag remains zero for the existing initializers. Every carrier
entry point must reject unknown tags and check either the original application
context/ticket, or the distinct original NodeFixed PCI slot/generation and
typed child birth. This is a representation of an already admitted owner, not
a new owner, ledger, caller certificate or ambient current-task allocator.

For a new SIGIO check the device variant must originate only from the exact
live WORK record and its current task/socket extent. A published cache node can
later supply its own real persistent source under the original cache lock/RCU,
without reviving the returned WORK record or reopening root admission.

NodeFixed AVC/SID/audit allocations need disjoint device kinds in the same
256-record bank. Their original PCI ancestry occupies the existing parent
fields; actual cache bucket/table identity therefore needs distinct metadata
in the same bounded record. That increase must be checked against the existing
1 MiB total bootstrap ceiling, never described as free metadata or another
bank. It cannot enlarge the 192 KiB infrastructure tail or any connection cap.

Before this variant can run, all equality tests that currently compare only
`blob.context` must become complete domain/owner comparisons. Merely allowing
NULL context equality would permit false same-owner graph membership. Generic
lookup/allocate/final-return, AVC phase/replace/queue/current, SID cache/table
ABA and audit head/string/buffer return must dispatch the explicit device
variant before an unknown private address could reach the old application or
ordinary allocator. The old application behavior and all unknown-address
refusals remain exact beneath that closed dispatch.

Normal cache revocation must still unlink and revoke an old private entry even
when its owner is poisoned. A failed private replacement cannot leave an
orphan publication. Actual RCU final callbacks, policy destroy and original
last SKB dataref/header returns retain the creator's PCI until real retirement.
No source counter is evidence of an installed allocator final-free producer.

The plan was approved before implementation. The grouped, still uninstalled
source now implements the closed carrier, disjoint security kinds, generic
factory dispatch and complete owner comparisons. The real SIGIO credential,
namespace, fasync, RT fallback and SELinux PROCESS permission bodies are copied
from exact authenticated definitions. Each private entry validates its real
current WORK before reading the borrowed credential, file-owner or async list.
The original application and ordinary functions remain present.

Device cache draining uses the existing fixed record table. A candidate has a
NULL address and only scalar birth, original PCI and cache identities. The
AVC slot lock is acquired before current-generation revalidation and address
derivation. SID draining first compares the scalar table identity to the
current policy under RCU, then acquires the original table cache lock and
revalidates the exact birth. Queue marking precedes the original unlink; the
real SID RCU request follows cache unlock. Actual callbacks and policy destroy
retain their original final-return responsibilities. Application drains are
unchanged. A finite close scan does not settle a legitimate late descendant.

The private socket async copy preserves the actual WAITDATA/NOSPACE flag
decisions, RCU snapshot and SIGIO/SIGURG selection. Its external entry validates
the exact socket stored in the current WORK. Its inner helper is static and
is emitted before its only private caller; the ordinary socket function is
unchanged. This helper has not yet replaced the real notification dispatch.

No Linux object/runtime result is claimed for this recipient group. Serialized
C controls exercise selected carrier/cache algorithms; their lock, policy,
task, layout and RCU doubles do not establish Linux concurrency or retirement.
The final signal-return source now prepays an embedded RCU head with the actual
original sigqueue and immutable birth tuple, refuses PREEMPT_RT, and retains
occupancy until the actual callback. Only its post-return callback requests the
existing cleanup work. Original sigqueue and ordinary allocation are unchanged.
This is source/mechanism scope; RCU/bootstrap and actual cleanup remain unqualified.

Actual wait callback dispatch, sender and receiver-tail wiring, synchronized
instrumentation admission, shared queue capacity, full allocation closure and
production installation remain explicit gates.
The source-selected factory consumer remains unavailable.
