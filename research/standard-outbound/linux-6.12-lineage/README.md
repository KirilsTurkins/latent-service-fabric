# Uninstalled Linux 6.12 lineage prerequisite

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
