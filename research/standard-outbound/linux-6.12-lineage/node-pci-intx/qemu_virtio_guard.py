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
                  b'#ifdef CONFIG_LINUX\n#include <unistd.h>\n'
                  b'#else\n#error "q35 virtio qualification requires a Linux host"\n#endif\n\n')
    require(raw.count(header_old) == 1 and raw.count(header_new) == 0, 'header-anchor')
    with_header = raw.replace(header_old, header_new, 1)
    start = b'static void virtio_write_config(PCIDevice *pci_dev, uint32_t address,\n'
    end = b'static uint32_t virtio_read_config(PCIDevice *pci_dev,\n'
    require(with_header.count(start) == with_header.count(end) == 1, 'function-region')
    first, last = with_header.index(start), with_header.index(end)
    require(first < last, 'function-order')
    region = with_header[first:last]
    changes = [
        (b'    struct virtio_pci_cfg_cap *cfg;\n\n    pci_default_write_config(pci_dev, address, val, len);\n',
         b'    struct virtio_pci_cfg_cap *cfg;\n'
         b'    uint16_t lsf_old = 0;\n'
         b'    int lsf_region;\n'
         b'    bool lsf_watch = pci_dev_bus_num(pci_dev) == 0 &&\n'
         b'        PCI_SLOT(pci_dev->devfn) == 3 && PCI_FUNC(pci_dev->devfn) == 0 &&\n'
         b'        pci_dev->qdev.id && !strcmp(pci_dev->qdev.id, "net0") &&\n'
         b'        pci_get_word(pci_dev->config + PCI_VENDOR_ID) == 0x1af4 &&\n'
         b'        pci_get_word(pci_dev->config + PCI_DEVICE_ID) == 0x1041 &&\n'
         b'        address == PCI_COMMAND && len == 2;\n'
         b'    if (lsf_watch) {\n'
         b'        lsf_old = pci_get_word(pci_dev->config + PCI_COMMAND);\n'
         b'        lsf_watch = (lsf_old & PCI_COMMAND_MASTER) && (val & PCI_COMMAND_MASTER) &&\n'
         b'            ((lsf_old ^ val) == PCI_COMMAND_INTX_DISABLE);\n'
         b'    }\n'
         b'    if (lsf_watch && (!vdev || !bql_locked() || !qemu_loglevel_mask(LOG_TRACE) ||\n'
         b'        vdev->status || qatomic_read(&vdev->isr) || vdev->disabled || vdev->broken ||\n'
         b'        vdev->started || vdev->start_on_kick || vdev->vhost_started ||\n'
         b'        proxy->bus.ioeventfd_started || proxy->bus.ioeventfd_grabbed ||\n'
         b'        !pci_dev->enabled || !pci_dev->is_master ||\n'
         b'        !pci_dev->bus_master_enable_region.enabled || pci_dev->has_vga ||\n'
         b'        ((pci_dev->cap_present & QEMU_PCI_CAP_PM) &&\n'
         b'         (pci_get_word(pci_dev->config + pci_dev->pm_cap + PCI_PM_CTRL) & PCI_PM_CTRL_STATE_MASK)) ||\n'
         b'        msi_enabled(pci_dev) || msix_enabled(pci_dev)))\n'
         b'        _exit(75);\n\n'
         b'    if (lsf_watch) {\n'
         b'        for (lsf_region = 0; lsf_region < PCI_NUM_REGIONS; ++lsf_region) {\n'
         b'            PCIIORegion *r = &pci_dev->io_regions[lsf_region];\n'
         b'            if (r->size && r->addr != pci_bar_address(pci_dev, lsf_region, r->type, r->size))\n'
         b'                _exit(75);\n'
         b'        }\n'
         b'    }\n\n'
         b'    pci_default_write_config(pci_dev, address, val, len);\n'),
        (b'    }\n}\n\n',
         b'    }\n'
         b'    if (lsf_watch) {\n'
         b'        if (!bql_locked() || vdev->status || qatomic_read(&vdev->isr) || vdev->disabled || vdev->broken ||\n'
         b'            vdev->started || vdev->start_on_kick || vdev->vhost_started ||\n'
         b'            proxy->bus.ioeventfd_started || proxy->bus.ioeventfd_grabbed ||\n'
         b'            !pci_dev->enabled || !pci_dev->is_master ||\n'
         b'            !pci_dev->bus_master_enable_region.enabled || pci_dev->has_vga ||\n'
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
         b'        qemu_log("lsf_q35_virtio_guard old=0x%x new=0x%x status=0 isr=0 disabled=0 broken=0 started=0 kick=0 vhost=0 ioeventfd=0 grabbed=0 master=1 vga=0 mappings=stable bql=1\\n",\n'
         b'                 lsf_old, (unsigned int)val);\n'
         b'    }\n}\n\n')]
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
