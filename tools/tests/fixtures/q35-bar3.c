/* Exercise the actual qualification C with bounded fake config I/O. This is
 * a fault control, not evidence of a real q35 device or physical retirement. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>

typedef uint32_t u32;
struct pci_dev { int id; };
struct lsf_node_parent {
    unsigned int prefix_intx_phase, prefix_intx_saved;
    unsigned int prefix_bar3_phase, prefix_bar3_saved;
};
enum { LSF_NODE_INTX_RESTORE_WRITTEN = 5 };
enum {
    LSF_NODE_BAR3_EMPTY, LSF_NODE_BAR3_WRITE_MAY_HAVE_RUN,
    LSF_NODE_BAR3_RESTORE_CLAIMED, LSF_NODE_BAR3_RESTORE_WRITTEN,
    LSF_NODE_BAR3_OBSERVED,
};
#define CONFIG_LSF_STREAM_NODE_PCI_BAR3 1
#define LSF_Q35_INTX_ORIGINAL_COMMAND 0x0103u
#define PCI_BASE_ADDRESS_3 0x1c
#define spin_lock_irqsave(lock, flags) ((void)(lock), (flags) = 0)
#define spin_unlock_irqrestore(lock, flags) ((void)(lock), (void)(flags))

static int pool_lock;
static struct lsf_node_parent node;
static struct pci_dev device, foreign;
static int owner_live, current_actor, expired, poisoned;
static int read_count, write_count, fail_read, fail_write, expire_on_write;
static u32 observed_value, writes[2];

static int lsf_factory_device_pci_owned(struct pci_dev *pci, unsigned long size)
{
    return owner_live && pci == &device && size == sizeof(device);
}
static struct lsf_node_parent *lsf_node_intx_bound_locked(struct pci_dev *pci)
{
    return owner_live && !poisoned && current_actor && pci == &device ? &node : 0;
}
static int lsf_node_constructor_actor_current(void) { return current_actor && !expired; }
static int lsf_node_intx_forward(struct pci_dev *pci)
{
    return lsf_node_intx_bound_locked(pci) && lsf_node_constructor_actor_current();
}
static void lsf_node_intx_fault(void) { poisoned = 1; }
static int pci_read_config_dword(struct pci_dev *pci, int offset, u32 *value)
{
    assert(pci == &device && offset == PCI_BASE_ADDRESS_3);
    ++read_count;
    if (read_count == fail_read)
        return 1;
    *value = observed_value;
    return 0;
}
static int pci_write_config_dword(struct pci_dev *pci, int offset, u32 value)
{
    assert(pci == &device && offset == PCI_BASE_ADDRESS_3 && write_count < 2);
    writes[write_count++] = value;
    if (expire_on_write == write_count)
        expired = 1;
    return write_count == fail_write;
}

#include "../../../research/standard-outbound/linux-6.12-lineage/node-pci-bar3/factory-node-pci-bar3.c"
#include "../../../research/standard-outbound/linux-6.12-lineage/node-pci-bar3/probe-bar3.c"

static void reset(void)
{
    node = (struct lsf_node_parent){
        .prefix_intx_phase = LSF_NODE_INTX_RESTORE_WRITTEN,
        .prefix_intx_saved = LSF_Q35_INTX_ORIGINAL_COMMAND,
    };
    owner_live = current_actor = 1;
    expired = poisoned = read_count = write_count = fail_read = fail_write = expire_on_write = 0;
    observed_value = writes[0] = writes[1] = 0;
}
static void two_exact_writes(void)
{
    assert(write_count == 2 && writes[0] == UINT32_MAX && writes[1] == 0);
}

int main(void)
{
    u32 saved = 123;

    reset();
    assert(lsf_pci_bar3_checked(&device) && !poisoned);
    two_exact_writes();
    assert(read_count == 3 && node.prefix_bar3_phase == LSF_NODE_BAR3_OBSERVED);
    assert(!lsf_node_bar3_claim_restore(&device, &saved));

    reset(); observed_value = 1;
    assert(!lsf_pci_bar3_checked(&device) && poisoned && !write_count);
    reset(); fail_read = 1;
    assert(!lsf_pci_bar3_checked(&device) && poisoned && !write_count);
    reset(); current_actor = 0;
    assert(!lsf_pci_bar3_checked(&device) && poisoned && !write_count);
    reset();
    assert(!lsf_pci_bar3_checked(&foreign) && poisoned && !write_count);

    reset(); fail_write = 1;
    assert(!lsf_pci_bar3_checked(&device) && poisoned);
    two_exact_writes();
    assert(node.prefix_bar3_phase == LSF_NODE_BAR3_RESTORE_WRITTEN);
    reset(); fail_read = 2;
    assert(!lsf_pci_bar3_checked(&device) && poisoned);
    two_exact_writes();
    assert(node.prefix_bar3_phase == LSF_NODE_BAR3_RESTORE_WRITTEN);
    reset(); expire_on_write = 1;
    assert(!lsf_pci_bar3_checked(&device) && poisoned);
    two_exact_writes();
    assert(node.prefix_bar3_phase == LSF_NODE_BAR3_RESTORE_WRITTEN);

    reset(); fail_write = 2;
    assert(!lsf_pci_bar3_checked(&device) && poisoned);
    two_exact_writes();
    assert(node.prefix_bar3_phase == LSF_NODE_BAR3_RESTORE_CLAIMED);
    assert(!lsf_node_bar3_claim_restore(&device, &saved));
    reset(); fail_read = 3;
    assert(!lsf_pci_bar3_checked(&device) && poisoned);
    two_exact_writes();
    assert(node.prefix_bar3_phase == LSF_NODE_BAR3_RESTORE_WRITTEN);

    reset();
    assert(lsf_node_bar3_prepare(&device, 0));
    current_actor = 0;
    assert(!lsf_node_bar3_claim_restore(&device, &saved));
    current_actor = 1;
    assert(lsf_node_bar3_claim_restore(&device, &saved) && saved == 0);
    assert(!lsf_node_bar3_claim_restore(&device, &saved));
    assert(!lsf_node_bar3_restore_written(&device, 1));
    assert(lsf_node_bar3_restore_written(&device, 0));
    assert(!lsf_node_bar3_restore_written(&device, 0));
    puts("q35 BAR3 custody fault controls passed");
    return 0;
}
