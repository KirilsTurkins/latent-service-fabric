"""Review-only selected virtio state guard; no production QEMU derivation."""
import hashlib

SOURCE_BYTES = 85641
SOURCE_SHA256 = 'affd3c3257c3b77350f7eba692d1fbe2a155d180f5a78b2e500a0c2256f10739'
FAIL_EXIT = 75

def require(value, reason):
    if not value:
        raise ValueError('q35-virtio-guard-'+reason)

def transform(raw):
    require(type(raw) is bytes and len(raw) == SOURCE_BYTES and
        hashlib.sha256(raw).hexdigest() == SOURCE_SHA256, 'exact-source')
    header_old = b'#include "qemu/osdep.h"\n\n'
    header_new = (b'#include "qemu/osdep.h"\n#include "qemu/main-loop.h"\n'
                  b'#include "hw/virtio/virtio-net.h"\n#include "net/net.h"\n'
                  b'#ifdef CONFIG_LINUX\n#include <unistd.h>\n'
                  b'#else\n#error "q35 virtio qualification requires a Linux host"\n#endif\n\n')
    require(raw.count(header_old) == 1 and raw.count(header_new) == 0, 'header-anchor')
    with_header = raw.replace(header_old, header_new, 1)
    start = b'static void virtio_write_config(PCIDevice *pci_dev, uint32_t address,\n'
    end = b'static int kvm_virtio_pci_vq_vector_use(VirtIOPCIProxy *proxy,\n'
    require(with_header.count(start) == with_header.count(end) == 1, 'function-region')
    first, last = with_header.index(start), with_header.index(end)
    require(first < last, 'function-order')
    region = with_header[first:last]
    changes = [
        (start,
         b'static PCIDevice *lsf_q35_device;\n'
         b'static unsigned int lsf_q35_phase;\n'
         b'static unsigned int lsf_q35_challenge;\n'
         b'static const uint8_t lsf_q35_offsets[] = {0, 1, 2, 3, 9, 10, 11, 10};\n'
         b'static const uint8_t lsf_q35_values[] = {0xf4, 0x1a, 0x41, 0x10, 0, 0, 2, 0};\n'
         b'static bool lsf_q35_selected(PCIDevice *dev)\n'
         b'{\n'
         b'    return pci_dev_bus_num(dev) == 0 && PCI_SLOT(dev->devfn) == 3 &&\n'
         b'        PCI_FUNC(dev->devfn) == 0 && dev->qdev.id &&\n'
         b'        !strcmp(dev->qdev.id, "net0") &&\n'
         b'        pci_get_word(dev->config + PCI_VENDOR_ID) == 0x1af4 &&\n'
         b'        pci_get_word(dev->config + PCI_DEVICE_ID) == 0x1041;\n'
         b'}\n\n' + start),
        (b'    struct virtio_pci_cfg_cap *cfg;\n\n    pci_default_write_config(pci_dev, address, val, len);\n',
         b'    struct virtio_pci_cfg_cap *cfg;\n'
         b'    uint16_t lsf_old = 0;\n'
         b'    int lsf_region;\n'
         b'    VirtIONet *lsf_net = NULL;\n'
         b'    NICState *lsf_nic = NULL;\n'
         b'    NetClientState *lsf_ncs = NULL;\n'
         b'    VirtIONetQueue *lsf_queues = NULL;\n'
         b'    uint16_t lsf_net_status = 0;\n'
         b'    bool lsf_watch = lsf_q35_selected(pci_dev) && lsf_q35_phase;\n'
         b'    if (lsf_watch) {\n'
         b'        if (!bql_locked() || pci_dev != lsf_q35_device ||\n'
         b'            address != PCI_COMMAND || len != 2)\n'
         b'            _exit(75);\n'
         b'        lsf_old = pci_get_word(pci_dev->config + PCI_COMMAND);\n'
         b'        if (!((lsf_q35_phase == 1 && lsf_old == 0x0103 && val == 0x0503) ||\n'
         b'              (lsf_q35_phase == 2 && lsf_old == 0x0503 && val == 0x0103)))\n'
         b'            _exit(75);\n'
         b'    }\n'
         b'    if (lsf_watch) {\n'
         b'        if (!vdev || !object_dynamic_cast(OBJECT(vdev), TYPE_VIRTIO_NET))\n'
         b'            _exit(75);\n'
         b'        lsf_net = VIRTIO_NET(vdev);\n'
         b'    }\n'
         b'    if (lsf_watch && (!vdev || !bql_locked() || !qemu_loglevel_mask(LOG_TRACE) ||\n'
         b'        vdev->status || qatomic_read(&vdev->isr) || !vdev->use_disabled_flag ||\n'
         b'        !vdev->disabled || vdev->broken ||\n'
         b'        vdev->started || vdev->start_on_kick || vdev->vhost_started ||\n'
         b'        proxy->bus.ioeventfd_started || proxy->bus.ioeventfd_grabbed ||\n'
         b'        pci_dev->irq_state || !pci_dev->enabled || pci_dev->is_master ||\n'
         b'        pci_dev->bus_master_enable_region.enabled || pci_dev->has_vga ||\n'
         b'        !lsf_net || !lsf_net->nic || !lsf_net->nic->ncs || !lsf_net->vqs ||\n'
         b'        lsf_net->max_queue_pairs != 1 || lsf_net->curr_queue_pairs != 1 ||\n'
         b'        lsf_net->multiqueue || lsf_net->vhost_started ||\n'
         b'        lsf_net->nic->ncs[0].peer || lsf_net->vqs[0].tx_waiting ||\n'
         b'        ((pci_dev->cap_present & QEMU_PCI_CAP_PM) &&\n'
         b'         (pci_get_word(pci_dev->config + pci_dev->pm_cap + PCI_PM_CTRL) & PCI_PM_CTRL_STATE_MASK)) ||\n'
         b'        msi_enabled(pci_dev) || msix_enabled(pci_dev)))\n'
         b'        _exit(75);\n\n'
         b'    if (lsf_watch) {\n'
         b'        lsf_nic = lsf_net->nic;\n'
         b'        lsf_ncs = lsf_nic->ncs;\n'
         b'        lsf_queues = lsf_net->vqs;\n'
         b'        lsf_net_status = lsf_net->status;\n'
         b'        for (lsf_region = 0; lsf_region < PCI_NUM_REGIONS; ++lsf_region) {\n'
         b'            PCIIORegion *r = &pci_dev->io_regions[lsf_region];\n'
         b'            if (r->size && r->addr != pci_bar_address(pci_dev, lsf_region, r->type, r->size))\n'
         b'                _exit(75);\n'
         b'        }\n'
         b'    }\n\n'
         b'    pci_default_write_config(pci_dev, address, val, len);\n'),
        (b'    }\n}\n\nstatic uint32_t virtio_read_config(PCIDevice *pci_dev,\n',
         b'    }\n'
         b'    if (lsf_watch) {\n'
         b'        if (!bql_locked() || vdev->status || qatomic_read(&vdev->isr) ||\n'
         b'            !vdev->use_disabled_flag || !vdev->disabled || vdev->broken ||\n'
         b'            vdev->started || vdev->start_on_kick || vdev->vhost_started ||\n'
         b'            proxy->bus.ioeventfd_started || proxy->bus.ioeventfd_grabbed ||\n'
         b'            pci_dev->irq_state || !pci_dev->enabled || pci_dev->is_master ||\n'
         b'            pci_dev->bus_master_enable_region.enabled || pci_dev->has_vga ||\n'
         b'            lsf_net->nic != lsf_nic || lsf_nic->ncs != lsf_ncs ||\n'
         b'            lsf_net->vqs != lsf_queues || lsf_net->status != lsf_net_status ||\n'
         b'            lsf_net->max_queue_pairs != 1 || lsf_net->curr_queue_pairs != 1 ||\n'
         b'            lsf_net->multiqueue || lsf_net->vhost_started ||\n'
         b'            lsf_ncs[0].peer || lsf_queues[0].tx_waiting ||\n'
         b'            ((pci_dev->cap_present & QEMU_PCI_CAP_PM) &&\n'
         b'             (pci_get_word(pci_dev->config + pci_dev->pm_cap + PCI_PM_CTRL) & PCI_PM_CTRL_STATE_MASK)) ||\n'
         b'            msi_enabled(pci_dev) || msix_enabled(pci_dev) ||\n'
         b'            pci_get_word(pci_dev->config + PCI_COMMAND) != (uint16_t)val)\n'
         b'            _exit(75);\n'
         b'        for (lsf_region = 0; lsf_region < PCI_NUM_REGIONS; ++lsf_region) {\n'
         b'            PCIIORegion *r = &pci_dev->io_regions[lsf_region];\n'
         b'            if (r->size && r->addr != pci_bar_address(pci_dev, lsf_region, r->type, r->size))\n'
         b'                _exit(75);\n'
         b'        }\n'
         b'        ++lsf_q35_phase;\n'
         b'        qemu_log("lsf_q35_virtio_guard old=0x%x new=0x%x phase=%u status=0 isr=0 disabled=1 broken=0 started=0 kick=0 vhost=0 ioeventfd=0 grabbed=0 irq=0 master=0 vga=0 peer=0 waiting=0 netVhost=0 queues=1 netStable=1 mappings=stable bql=1\\n",\n'
         b'                 lsf_old, (unsigned int)val, lsf_q35_phase);\n'
         b'    }\n}\n\nstatic uint32_t virtio_read_config(PCIDevice *pci_dev,\n'),
        (b'    return pci_default_read_config(pci_dev, address, len);\n',
         b'    uint32_t lsf_value = pci_default_read_config(pci_dev, address, len);\n'
         b'    if (lsf_q35_selected(pci_dev)) {\n'
         b'        if (!bql_locked() || (lsf_q35_phase && pci_dev != lsf_q35_device))\n'
         b'            _exit(75);\n'
         b'        if (!lsf_q35_phase) {\n'
         b'            if (len == 1 && address == lsf_q35_offsets[lsf_q35_challenge] &&\n'
         b'                lsf_value == lsf_q35_values[lsf_q35_challenge])\n'
         b'                ++lsf_q35_challenge;\n'
         b'            else\n'
         b'                lsf_q35_challenge = (len == 1 && address == 0 && lsf_value == 0xf4);\n'
         b'            if (lsf_q35_challenge == ARRAY_SIZE(lsf_q35_offsets)) {\n'
         b'                if (!qemu_loglevel_mask(LOG_TRACE) ||\n'
         b'                    pci_get_word(pci_dev->config + PCI_COMMAND) != 0x0103 ||\n'
         b'                    pci_dev->is_master || pci_dev->bus_master_enable_region.enabled)\n'
         b'                    _exit(75);\n'
         b'                lsf_q35_device = pci_dev;\n'
         b'                lsf_q35_phase = 1;\n'
         b'                qemu_log("lsf_q35_intx_armed command=0x103\\n");\n'
         b'            }\n'
         b'        }\n'
         b'    }\n'
         b'    return lsf_value;\n')]
    for old, new in changes:
        require(region.count(old) == 1 and region.count(new) == 0, 'unique-anchor')
        region = region.replace(old, new, 1)
    derived = with_header[:first]+region+with_header[last:]
    inverse = region
    for old, new in reversed(changes):
        require(inverse.count(new) == 1, 'unique-inverse')
        inverse = inverse.replace(new, old, 1)
    inverse = with_header[:first]+inverse+with_header[last:]
    require(inverse.count(header_new) == 1 and inverse.replace(header_new, header_old, 1) == raw,
            'exact-inverse')
    return derived, {'sourceBytes': len(raw), 'sourceSha256': hashlib.sha256(raw).hexdigest(),
        'derivedBytes': len(derived), 'derivedSha256': hashlib.sha256(derived).hexdigest(),
        'originalSourceInverseExact': True, 'failStopExit': FAIL_EXIT,
        'qemuExecuted': False, 'virtioCustodyQualified': False}
