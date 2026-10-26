/* SPDX-License-Identifier: GPL-2.0-only */
/* Include in original net/core/dev.c. Constructor-only publication and original
 * refs/RCU/free points own this immutable descriptor alias. No pool-lock lookup
 * or allocation is allowed in these IRQ/NMI-capable hot paths. */
#include <net/lsf_stream_netdev_cpu_private.h>
static_assert(NR_CPUS == 64);
static_assert(sizeof(unsigned long) == sizeof(atomic_long_t));

static struct lsf_stream_netdev_cpu_storage *lsf_stream_netdev_cpu_current(
    const struct net_device *dev)
{
    struct lsf_stream_netdev_cpu_storage *storage = READ_ONCE(dev->lsf_cpu_storage);
    if (!storage) return NULL;
    /* Not an adoption API: ONLY the actual original fenced constructor may
     * establish this private field after a typed, parent-bound prepaid birth.
     * Its original refs/RCU protect both objects through each real access. */
    if (READ_ONCE(storage->device) != dev || READ_ONCE(storage->cpus) != NR_CPUS) {
        atomic_set(&storage->fault, 1);
        return NULL;
    }
    return storage;
}

static void lsf_stream_netdev_cpu_ref_change(struct net_device *dev, int change)
{
    struct lsf_stream_netdev_cpu_storage *storage = lsf_stream_netdev_cpu_current(dev);
    unsigned int cpu;
    if (!storage) return;
    /* Original this_cpu_inc/dec is migration-safe as one CPU-local operation.
     * Fix this multi-instruction index through the atomic operation, including
     * nested IRQ/NMI use. No local IRQ masking, pool lock, scheduler callback or
     * per_cpu_ptr of ordinary backing is introduced. Atomic int keeps the
     * original signed cross-CPU debt, including wrap bits, rather than a quota. */
    preempt_disable_notrace();
    cpu = raw_smp_processor_id();
    if (unlikely(cpu >= NR_CPUS)) atomic_set(&storage->fault, 1);
    else atomic_add(change, &storage->references[cpu]);
    preempt_enable_notrace();
}

void lsf_stream_netdev_cpu_get(struct net_device *dev)
{
    lsf_stream_netdev_cpu_ref_change(dev, 1);
}

void lsf_stream_netdev_cpu_put(struct net_device *dev)
{
    lsf_stream_netdev_cpu_ref_change(dev, -1);
}

int lsf_stream_netdev_cpu_ref_read(const struct net_device *dev)
{
    struct lsf_stream_netdev_cpu_storage *storage = lsf_stream_netdev_cpu_current(dev);
    int cpu, total = 0;
    if (!storage) return INT_MIN; /* Unknown never impersonates original base ref 1. */
    for_each_possible_cpu(cpu)
        total += atomic_read(&storage->references[cpu]);
    return total; /* Original reader order and signed aggregate; never slot-zero. */
}

void lsf_stream_netdev_cpu_stats_inc(struct net_device *dev, u32 offset)
{
    struct lsf_stream_netdev_cpu_storage *storage = lsf_stream_netdev_cpu_current(dev);
    unsigned int index, cpu;
    if (!storage) return;
    switch (offset) {
    case offsetof(struct net_device_core_stats, rx_dropped): index = 0; break;
    case offsetof(struct net_device_core_stats, tx_dropped): index = 1; break;
    case offsetof(struct net_device_core_stats, rx_nohandler): index = 2; break;
    case offsetof(struct net_device_core_stats, rx_otherhost_dropped): index = 3; break;
    default: atomic_set(&storage->fault, 1); return;
    }
    preempt_disable_notrace();
    cpu = raw_smp_processor_id();
    if (unlikely(cpu >= NR_CPUS)) atomic_set(&storage->fault, 1);
    else atomic_long_inc(&storage->stats[cpu][index]);
    preempt_enable_notrace();
}

void lsf_stream_netdev_cpu_stats_add(const struct net_device *dev, struct rtnl_link_stats64 *output)
{
    struct lsf_stream_netdev_cpu_storage *storage = lsf_stream_netdev_cpu_current(dev);
    int cpu;
    if (!storage) return;
    for_each_possible_cpu(cpu) {
        /* Same CPU iteration and original four-field read/add ordering.
         * Cast preserves native unsigned-long bits/overflow from atomic long. */
        output->rx_dropped += (unsigned long)atomic_long_read(&storage->stats[cpu][0]);
        output->tx_dropped += (unsigned long)atomic_long_read(&storage->stats[cpu][1]);
        output->rx_nohandler += (unsigned long)atomic_long_read(&storage->stats[cpu][2]);
        output->rx_otherhost_dropped += (unsigned long)atomic_long_read(&storage->stats[cpu][3]);
    }
}
