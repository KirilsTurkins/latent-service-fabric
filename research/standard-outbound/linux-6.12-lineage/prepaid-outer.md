# Uninstalled prepaid outer socket and VFS prefix

This source continues the accepted ADR-0061 contract, not a different network
architecture. Normal installation is Unsupported and ACCOUNTING_QUALIFIED is
false. The create-only factory still selects NULL. There is no Kconfig,
Makefile, initcall, trusted bootstrap or executable supported kernel profile.

The ordinary historical chain is `sock_alloc -> new_inode_pseudo -> alloc_inode
-> sock_alloc_inode -> alloc_inode_sb`. It can allocate before any protocol
`sk_alloc`. The private path now supplies the original context before this
outer allocation, instead of registering an arbitrary pointer afterwards.

## Actual source derivation

`tools/host_stream_kernel_outer_derivation.py` requires nine exact whole
historical Linux files (715,444 bytes), Git blob identities and 17 partial
definitions. It refuses changed/duplicate/unknown input. The baseline remains
the earlier historical Linux commit; it is not an endorsement of an unpatched
deployment. No network acquisition or build occurs in this tool.

The new private socket/inode constructor replaces only the outer allocator with
the existing fixed prepaid allocator. It calls `inode_init_once`, preserves all
original wait/socket field initialization, and writes the context, view slot and
generation at birth. Its VFS clone preserves `inode_init_always`, including the
real security call, and the complete original failure cleanup. Its socket clone
preserves the actual inode number, uid/gid, mode and sockfs operations. There is
no general-allocator fallback and no fabricated successful protocol socket.

The private begin helper calls the real `security_socket_create` before the
outer allocation, under the existing kernel-socket semantics. The current
finite prefix accepts only IPv4 TCP stream inputs. It sets the same socket type
as the original outer path. A separate post-create helper requires the actual
protocol fields and original birth context before calling the real
`security_socket_post_create`. A future complete consumer must still perform
real protocol creation, module ownership and the original error/release paths.
The begin helper alone is not that consumer and cannot select the factory.

The ordinary `__sock_create`, `sock_alloc`, generic VFS allocator, security
functions and inode initializers remain intact. Ordinary `sock_alloc_inode`
only clears the private fields; its allocator and normal free remain original.
The new code tests actual sockfs superblock/operations identity before reading
socket-specific fields from a generic inode. An uninitialized sockfs refuses.

## Mandatory security and deferred lifetime

This prefix has not closed allocation paths inside active LSM inode/socket
hooks. It therefore refuses before allocation if the real boot-selected state
contains an inode blob/cache or an active inode allocate/free/free-RCU or socket
create/post-create hook. It does not disable a hook, rewrite an LSM result,
change boot configuration or silently skip a security call. A missing security
translation unit is also unsupported. Lockdep/debug-lock allocation branches
are unsupported by this prefix. These narrow checks are not a complete platform
configuration or allocator-closure proof.

The actual `destroy_inode` retains a private deferred owner immediately before
the unchanged `call_rcu`. The original `i_callback` and sockfs free callback
return the original view only after the real callback reaches that point.
Initializer failure still uses the original synchronous `i_callback`; it does
not invent an RCU completion. Context, ticket and deferred ownership are copied
before returning storage, so no freed/reused object is read afterwards. Unknown
generation, failed return or duplicate deferred notification poisons/fences the
original factory; no capacity is refunded on uncertainty.

View return is not page final free. The original backing record remains LIVE,
and final physical destruction, driver/RX teardown and its trusted consumer
remain unimplemented. The existing 96/64 KiB occupancy, 64 owner / 256 total
records and one-MiB metadata reservation are unchanged. The source does not
claim that a compiled kernel's full outer/protocol/RX layout fits those bounds.

## Supplemental controls and remaining closure

Eleven additive Python source controls preserve the thirteen preceding factory
controls. The tiny freestanding Wasm C reference executes exact original/private
constructor and callback bodies with explicit VFS initializer, security, RCU,
allocator-wrapper and type doubles. The unchanged ordinary constructor chain
reproduces the uncharged general allocation control (exit 2); twelve private
origin, failure-cleanup, security refusal, deferred lifetime and ordinary-host
isolation controls pass (exit 0). R4 fixes the reference reset's array-bound
fidelity; earlier compile/printing attempts remain retained. No numeric model
type/layout, fake callback scheduler or wrapper is authenticated as Linux.

No kernel, host, native runtime or VM build is run. Earlier actual broker tests
and stream compilation retain their separate source attribution. These controls
do not execute the real VFS initializer or LSM bodies and do not prove a real
allocator, concurrency, RCU grace period, physical cost or final-free event.

The next necessary consumers remain real bounded protocol creation, socket/
SKB/clone/cache/route/DNS/deferred allocation, owned prelookup driver/NAPI/page/RX
storage, trusted native bootstrap and descriptor lifetime. A maintained kernel
commit, resolved configuration/compiler/image, running BTF, complete disjoint
physical geometry and sealed final-free consumer are still required before
installation. No caller assertion, public registrar, timeout, socket drop,
empty `ss` output or indefinite quarantine can substitute for those gates.
