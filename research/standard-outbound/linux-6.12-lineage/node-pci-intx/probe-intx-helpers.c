/* Qualification-only additions to the pinned PCI allocating translation unit.
 * The ordinary pci_intx_mask_broken body remains its exact original bytes. */
#ifdef CONFIG_LSF_STREAM_NODE_PCI_INTX
extern int lsf_node_intx_begin(struct pci_dev *pci);
extern int lsf_node_intx_forward(struct pci_dev *pci);
extern int lsf_node_intx_preflight(struct pci_dev *pci, u16 original);
extern int lsf_node_intx_prepare_toggle(struct pci_dev *pci, u16 original);
extern int lsf_node_intx_claim_restore(struct pci_dev *pci, u16 original);
extern int lsf_node_intx_restore_written(struct pci_dev *pci, u16 original);
extern int lsf_node_intx_observed(struct pci_dev *pci, u16 restored, u8 pin, u8 line);
extern void lsf_node_intx_fault(void);

/* Two bounded, read-only selected-BDF signatures let the owning QEMU trace
 * refuse an ambiguous window. They neither write config nor mint an owner. */
static int lsf_pci_intx_challenge(struct pci_dev *dev, bool after)
{
    static const u8 offsets[] = {0x00, 0x01, 0x02, 0x03, 0x09, 0x0a, 0x0b, 0x0a};
    static const u8 values[] = {0xf4, 0x1a, 0x41, 0x10, 0x00, 0x00, 0x02, 0x00};
    unsigned int i, index;
    u8 value;

    for (i = 0; i < ARRAY_SIZE(offsets); ++i) {
        index = after ? ARRAY_SIZE(offsets) - 1u - i : i;
        if (!lsf_node_intx_forward(dev) ||
            pci_read_config_byte(dev, offsets[index], &value) || value != values[index])
            return 0;
    }
    return 1;
}

/* Read only the selected function's standard capability list. All reads are
 * checked, each offset is bounded/aligned/unique, and no absent or malformed
 * list is interpreted as proof that MSI-X is disabled. */
static int lsf_pci_intx_snapshot(struct pci_dev *dev, u16 *command, u8 *pin, u8 *line,
    bool admit)
{
    u64 seen = 0;
    u16 status, flags;
    u8 pos, id, next;
    unsigned int count = 0, msi = 0, msix = 0;

    if (!command || !pin || !line || (admit && !lsf_pci_intx_challenge(dev, false)) ||
        !lsf_node_intx_forward(dev) ||
        pci_read_config_word(dev, PCI_COMMAND, command) ||
        (*command & PCI_COMMAND_INTX_DISABLE) || !(*command & PCI_COMMAND_MASTER) ||
        !lsf_node_intx_forward(dev) ||
        pci_read_config_word(dev, PCI_STATUS, &status) ||
        (status & PCI_STATUS_INTERRUPT) || !(status & PCI_STATUS_CAP_LIST) ||
        !lsf_node_intx_forward(dev) ||
        pci_read_config_byte(dev, PCI_CAPABILITY_LIST, &pos))
        return 0;
    while (pos) {
        unsigned int bit;
        if (++count > 48u || pos < 0x40u || pos > 0xfcu || (pos & 3u))
            return 0;
        bit = (pos - 0x40u) / 4u;
        if (seen & (1ULL << bit))
            return 0;
        seen |= 1ULL << bit;
        if (!lsf_node_intx_forward(dev) ||
            pci_read_config_byte(dev, pos + PCI_CAP_LIST_ID, &id) ||
            !lsf_node_intx_forward(dev) ||
            pci_read_config_byte(dev, pos + PCI_CAP_LIST_NEXT, &next) ||
            !id || id == 0xffu)
            return 0;
        if (id == PCI_CAP_ID_MSI || id == PCI_CAP_ID_MSIX) {
            if (pos > 0xfcu || !lsf_node_intx_forward(dev) ||
                pci_read_config_word(dev, pos + (id == PCI_CAP_ID_MSI ?
                    PCI_MSI_FLAGS : PCI_MSIX_FLAGS), &flags))
                return 0;
            if (id == PCI_CAP_ID_MSI) {
                if (++msi != 1u || (flags & PCI_MSI_FLAGS_ENABLE))
                    return 0;
            } else if (++msix != 1u || (flags & PCI_MSIX_FLAGS_ENABLE)) {
                return 0;
            }
        }
        pos = next;
    }
    if (msix != 1u || !lsf_node_intx_forward(dev) ||
        pci_read_config_byte(dev, PCI_INTERRUPT_PIN, pin) || !*pin || *pin > 4u ||
        !lsf_node_intx_forward(dev) ||
        pci_read_config_byte(dev, PCI_INTERRUPT_LINE, line) ||
        (!admit && !lsf_pci_intx_challenge(dev, true)) ||
        (admit && !lsf_node_intx_preflight(dev, *command)))
        return 0;
    return 1;
}

/* Same native pin/line order, but selected reads cannot silently fail. */
static void lsf_pci_read_irq_checked(struct pci_dev *dev)
{
    u8 irq;

    if (dev->is_virtfn || !lsf_node_intx_forward(dev) ||
        pci_read_config_byte(dev, PCI_INTERRUPT_PIN, &irq))
        goto fault;
    dev->pin = irq;
    if (irq && (!lsf_node_intx_forward(dev) ||
        pci_read_config_byte(dev, PCI_INTERRUPT_LINE, &irq)))
        goto fault;
    dev->irq = irq;
    return;
fault:
    lsf_node_intx_fault();
}

/* Same four native accesses and XOR as pci_intx_mask_broken, with an explicit
 * status/currentness check at every forward step. Once a write may have been
 * attempted, exactly one original-word restore is allowed even after expiry. */
static int lsf_pci_intx_mask_broken_checked(struct pci_dev *dev)
{
    u16 orig, toggle, value, restored;
    int write_error, good = 1;

    if (!lsf_node_intx_forward(dev) || pci_read_config_word(dev, PCI_COMMAND, &orig))
        goto fault;
    toggle = orig ^ PCI_COMMAND_INTX_DISABLE;
    if (!lsf_node_intx_prepare_toggle(dev, orig) || !lsf_node_intx_forward(dev))
        goto fault; /* The forward write has not been issued. */
    write_error = pci_write_config_word(dev, PCI_COMMAND, toggle);
    if (write_error || !lsf_node_intx_forward(dev) ||
        pci_read_config_word(dev, PCI_COMMAND, &value) || value != toggle)
        good = 0;

    if (!lsf_node_intx_claim_restore(dev, orig))
        goto fault;
    write_error = pci_write_config_word(dev, PCI_COMMAND, orig);
    if (write_error || !lsf_node_intx_restore_written(dev, orig))
        goto fault;
    if (!good || !lsf_node_intx_forward(dev) ||
        pci_read_config_word(dev, PCI_COMMAND, &restored) || restored != orig)
        goto fault;
    return 0;
fault:
    lsf_node_intx_fault();
    return 1;
}
#endif
