# Uninstalled Linux 6.12 lineage prerequisite

The additive [prepaid backing/factory source](prepaid-factory.md) separates
permanent backing from original activation occupancy and retains the actual
accepted broker I/O owner in existing quarantine. Its protected source selection
still refuses: real outer/security/RX consumers and physical qualification remain
unfinished. It does not replace or relabel the historical recipes below.

This is source work for #738/#739/#740 under the already accepted ADR-0061.
It is not a supported kernel profile. The normal stream provider still refuses
installation before allocation, and `ACCOUNTING_QUALIFIED` remains false.

`tools/host_stream_kernel_derivation.py` requires the exact complete preimages of
three upstream files at Linux commit
`adc218676eef25575469234709c2d87185ca223a` (the original v6.12 source baseline).
It checks file length, SHA-256, Git blob identity, each function preimage and every
insertion anchor. A different kernel patchlevel is refused, rather than treated
as a supported current kernel. This baseline is not an endorsement of deploying
an unpatched historical kernel. No source is fetched or executed implicitly.

```sh
python tools/host_stream_kernel_derivation.py --source-dir exact-linux-source --output fresh-derived-source
```

The three hook families preserve every original statement and its order:

- `sk_prot_free` copies the registered allocation token and socket cookie before
  allocator free, then observes completion afterward. This function is reached
  after the original deferred transmit/optional RCU destruction path.
- `inet_twsk_free` separately copies the TIME_WAIT cookie and token before free,
  then observes completion afterward. Original `module_put` ordering is retained.
- SKB physical header/clone and heap-head frees copy their registered token
  before their actual allocator call. A shared fclone emits no completion when
  its reference count remains nonzero. Fragment/page-pool return poisons any
  matching registered lineage; it does not certify allocator free.

No post-free callback dereferences the freed object. Its integer address,
cookie, allocation generation, owner generation, kind and charge were copied
while live. A pointer reused before the old post-free observation fails closed.
The header, data head and shared clone block are distinct physical allocations.

`lineage.h` is an allocation-free serialized mechanism with 64 owner slots and
256 allocation slots. These are fixed storage bounds for the experiment, not an
increase in provider or guest capacity. Registered byte credits are reserved
before a corresponding allocation; only a matching copied post-free token
decrements them. The existing TCP 96 KiB and DNS 64 KiB ceilings are unchanged.
Owner slots are never reused. Reused allocation slots receive a non-wrapping new
generation. Wrong, duplicate, stale, foreign, overflowing or unproved lineage
stays poisoned; loss poisons all owners. An unclassified free while any owner is
registered also poisons the experiment. A complete trusted allocation path must
classify genuinely unowned traffic before these private hooks; the current
unfiltered candidate cannot qualify a normal kernel. There is no ring-buffer event dependency,
public release operation, caller-created certificate or eviction path.

Drain does not globally prohibit descendants. A live allocation may create a
charged child while its owner drains, including TIME_WAIT/deferred SKB work.
Only its actual pre-free capture seals that individual allocation. Unaccountable
birth after that point poisons the owner. A reserved but uncommitted allocation
also prevents a drained observation. An empty mechanism is only a mechanism
observation; it is never a kernel retirement certificate or permission to refund.

`kernel-hooks.c` is a private candidate adapter with one IRQ-safe lock, no
exported symbols, device, ioctl, userspace map or output surface. It is **not
linked by a kernel build**. There is deliberately no Kconfig/Makefile selection,
trusted socket-factory/admission integration or normal-provider installation.
Its static table has no live owner registrar yet. The complete future producer
must bind all eight opaque scope words to actual sealed authority and retained
original charges; arbitrary userspace assertions cannot do that.

The sixteen `reference.c` controls exercise this mechanism only. A second
`hook-reference.c` compiles the five exact original/derived functions against
explicit C protocol doubles: original source supplies the missing-post-free
counterexample, while ten current controls cover allocator ordering, copied
identity, the two socket allocators, distinct TIME_WAIT, ordinary/fclone SKB
storage, last-clone lifetime, heap heads and unproved fragment returns. These
controls deliberately overwrite model object bytes before the post-free call.
They cannot
validate kernel ABI, locking, BTF, physical allocation or actual kernel free.
The small authenticated function fixture separately verifies insertion and
pre/post ordering; it cannot replace the complete three-file preimage check.

Before any supported profile can be selected, the missing obligations include:

- A maintained kernel/config/compiler/image and matching **running** kernel/BTF
  identity, the complete allocation and birth/clone graph, and trusted factory
  integration before the first socket allocation.
- Every SKB bulk/NAPI path, fragments, page pools, route/ancillary ownership,
  deferred work and shared allocator/cache lifetime. The selected hooks alone
  do not cover those paths or prove no future unregistered descendants.
- Enforcement and a disjoint complete worst-case physical bound within the
  unchanged 96/64 KiB reservations, including prepaid producer storage and
  shared fixed infrastructure. `SO_SNDBUF`, `SO_RCVBUF`, cgroups or a sampled
  plateau cannot supply this proof.
- Trusted loss/detach/currentness fences and sealed terminal consumption by the
  original bounded maintenance/quarantine owner, plus actual supported-kernel,
  signed-component, protected-operator and adversarial controls.

No kernel/node build, BTF authentication, sealed final-free fact, full allocation
qualification or production enablement is claimed by this source prerequisite.

## Constructor admission prerequisite

The additive constructor recipe authenticates the same three whole preimages
and preserves the five free-hook derivations above. It also derives admission
before the first allocator in the exact upstream sk_prot_alloc, inet_twsk_alloc
and __alloc_skb functions:

    python tools/host_stream_kernel_birth_derivation.py --source-dir exact-linux-source --output fresh-derived-source

The private admission.h carrier copies the complete original eight-word scope
and nonwrapping owner generation. A checked bundle reserves the complete byte
sum, sufficient fixed table slots and every allocation generation before any
allocator may run. SKB header/fclone storage and data head require two distinct
records, both admitted together within the unchanged original allowance.
Header-only plans, missing costs, foreign/sealed parents, stale scope, capacity
and generation overflow refuse before allocation. A draining live parent may
still create charged descendants. Replaying a copied commit ticket poisons the
experiment; it cannot create a second allocation or release credit.

Original security/module failures, TIME_WAIT quota ordering and SKB header/data
cleanup remain in the derived constructors. Failed or uncertain allocator entry
retains the whole original reservation and poisons its owner, including unused
second-allocation tickets. No inferred allocator failure, cache return or normal
cleanup branch refunds a ticket.

This does **not** authenticate physical costs or authority. The C reference
supplies explicit model costs and context. A complete future trusted factory must
bind actual prepaid activation/tenant/provider/boot scope and a source-qualified
disjoint physical layout; arbitrary callers cannot supply either as proof.
proto->obj_size, requested payload length and socket buffer settings are not
complete physical costs. SKB NAPI, allocator rounding, fclone layout and every
remaining allocation path still require the full selected-kernel closure.

In particular, sk_prot_alloc precedes socket initialization. It cannot read a
valid cookie or invent one. The constructor-only recipe's observation with no
cookie cannot commit a socket record; it remains charged and poisoned in that
model. Its original recipe and controls remain unchanged. The additive
initialization handoff below advances that uninstalled source seam; it does not
supply a trusted live factory or a supported kernel profile.

The actual uninstalled CONFIG_LSF_STREAM_LINEAGE constructor adapter therefore
**refuses every constructor before allocation**: no trusted context, physical
layout or cookie handoff has been installed. It shares the existing private
lineage state/lock, with no public registrar, Kconfig, Makefile, userspace release
or certificate. With that CONFIG absent, the header preserves original behavior
without touching lineage state. This candidate cannot be installed as a normal
networking kernel profile.

Supplemental controls now include the original-constructor missing-admission
counterexample, ten derived constructor controls, fourteen carrier controls and
three controls compiling the actual selected adapter/unselected header. They run
against explicit C allocator/type/spinlock doubles in a tiny freestanding Wasm
reference. They establish neither Linux execution nor real locking, allocator
costs, kernel authority, final-free proof or supported installation. All earlier
26 supplemental C controls and 18 source controls remain unchanged; the new
source suite adds eight controls. No production qualification flag changes.

## Reserved-address to initialized-cookie handoff

The next explicit recipe requires all seven complete original source preimages:
the three networking files above plus include/net/sock.h,
include/linux/sock_diag.h, net/core/sock_diag.c and include/linux/cookie.h at the
same exact commit. SHA-256, lengths, Git blob identity and seven initialization/
copy/generator function preimages are checked before derivation.

    python tools/host_stream_kernel_handoff_derivation.py --source-dir exact-linux-source --output fresh-derived-source

The socket allocation keeps its existing record RESERVED and attaches its
address without reading allocator bytes or a cookie. No second table, charge
or allocation is created. Private hooks in sk_alloc and sk_clone_lock observe
initialization before return/publication. The clone hook follows the original
failure branches and precedes smp_wmb and the refcount publication. Those outer
constructor changes are insertions: every upstream statement remains ordered.
Early destruction of a still-reserved socket remains poisoned and charged.

The private adapter copies the complete original token and admission scope under
the existing lock before reading a cookie. It releases that lock, invokes the
unchanged upstream sock_gen_cookie chain, then reacquires the lock and rechecks
the scope, original owner/allocation generations, address and RESERVED phase
before moving that record to LIVE. A stale, foreign, duplicate, reused-address,
unknown or raced handoff cannot release capacity.

The authenticated sk_init_common does not reset a cookie. The authenticated
sock_copy prefix can copy a parent's existing cookie, so a clone may legitimately
share that value. This recipe never resets it or requires global per-object
cookie uniqueness: original allocation generation and address remain distinct.
It neither invents a cookie nor replaces the actual upstream generator.

Fourteen supplementary C controls compile the actual private hook translation
unit and all three unchanged upstream cookie functions with explicit atomic,
per-CPU, preemption, spinlock and type doubles. The previous constructor callback
reproduces the zero-cookie commit refusal (RED, exit 2); the new controls pass.
The outer sk_alloc/sk_clone_lock insertions are source-verified, not executed by
those controls. Eight additive Python controls preserve all twenty-six earlier
source cases and every prior C input. These results are not Linux execution,
real concurrency, ABI or physical allocation measurements.

The actual constructor prepare gate still refuses because no trusted live
factory or complete physical layout has been installed. There is no Kconfig/
Makefile integration, public registrar, caller certificate or quarantine release.
Running maintained-kernel/config/BTF authentication, complete allocation and
descendant coverage, prepaid physical costs and sealed final-free consumption
remain required. Normal installation and ACCOUNTING_QUALIFIED stay unchanged.

## Physical extent plan and allocator-cache retention

The additive [partial allocation closure](allocation-closure.md) authenticates
25 whole historical source files and 37 lifetime functions. It introduces a
checked disjoint whole-extent plan over the original bundle and a conservative
keeper for all five object-return callbacks. Returning a slot to SLUB/kmalloc/
NAPI is not backing-page final free: the keeper retains the original charge in
a nonreusable PHYSICAL_HELD record, without a public or private release shortcut.
The earlier recipes and model controls remain unchanged and separately scoped.

No actual geometry, trusted factory/RX classification, complete shared-cache/
page/route/deferred closure or final-free producer is installed. In particular,
before-socket-lookup RX allocation cannot borrow a later socket's authority.
The actual constructor still refuses before allocation. The partial graph,
explicit model geometry and supplemental C controls cannot qualify a physical
kernel profile; every production/full-accounting flag remains false.
