"""Additional fail-stop guard for a single read-only BAR on the q35 image.

Only the output of the existing, authenticated INTx guard is accepted. The
BAR3 register, its write masks, its QEMU region and every existing mapping
must be unchanged on both sides of each of the two writes. Other BARs and the
ordinary provider remain outside this qualification image.
"""
import hashlib

INPUT_BYTES = 91407
INPUT_SHA256 = 'fe5c7e782bd435310160bffe748c54b96bd67b0bc3ef503e380d6e61209e29ff'


def require(condition, reason):
    if not condition:
        raise ValueError('q35-bar3-guard-' + reason)


def transform(raw):
    require(type(raw) is bytes and len(raw) == INPUT_BYTES and
        hashlib.sha256(raw).hexdigest() == INPUT_SHA256, 'exact-intx-guard-source')
    changes = [
        (b'    uint16_t lsf_old = 0;\n    int lsf_region;\n',
         b'    uint16_t lsf_old = 0;\n    int lsf_region;\n'
         b'    PCIIORegion lsf_regions[PCI_NUM_REGIONS];\n'
         b'    bool lsf_bar3 = lsf_q35_phase == 3 || lsf_q35_phase == 4;\n'),
        (b'        if (!bql_locked() || pci_dev != lsf_q35_device ||\n'
         b'            address != PCI_COMMAND || len != 2)\n'
         b'            _exit(75);\n'
         b'        lsf_old = pci_get_word(pci_dev->config + PCI_COMMAND);\n'
         b'        if (!((lsf_q35_phase == 1 && lsf_old == 0x0103 && val == 0x0503) ||\n'
         b'              (lsf_q35_phase == 2 && lsf_old == 0x0503 && val == 0x0103)))\n'
         b'            _exit(75);\n',
         b'        if (!bql_locked() || pci_dev != lsf_q35_device)\n'
         b'            _exit(75);\n'
         b'        lsf_old = pci_get_word(pci_dev->config + PCI_COMMAND);\n'
         b'        if (lsf_bar3) {\n'
         b'            if (address != PCI_BASE_ADDRESS_3 || len != 4 || lsf_old != 0x0103 ||\n'
         b'                pci_get_long(pci_dev->config + PCI_BASE_ADDRESS_3) ||\n'
         b'                pci_get_long(pci_dev->wmask + PCI_BASE_ADDRESS_3) ||\n'
         b'                pci_get_long(pci_dev->w1cmask + PCI_BASE_ADDRESS_3) ||\n'
         b'                pci_dev->io_regions[3].size ||\n'
         b'                (proxy->config_cap && proxy->config_cap < 0x40) ||\n'
         b'                (pci_dev->msi_cap && pci_dev->msi_cap < 0x40) ||\n'
         b'                (pci_dev->msix_cap && pci_dev->msix_cap < 0x40) ||\n'
         b'                (pci_dev->exp.exp_cap && pci_dev->exp.exp_cap < 0x40) ||\n'
         b'                (pci_dev->exp.ats_cap && pci_dev->exp.ats_cap < 0x100) ||\n'
         b'                (pci_dev->exp.sriov_cap && pci_dev->exp.sriov_cap < 0x100) ||\n'
         b'                !((lsf_q35_phase == 3 && val == UINT32_MAX) ||\n'
         b'                  (lsf_q35_phase == 4 && val == 0)))\n'
         b'                _exit(75);\n'
         b'        } else if (address != PCI_COMMAND || len != 2 ||\n'
         b'                   !((lsf_q35_phase == 1 && lsf_old == 0x0103 && val == 0x0503) ||\n'
         b'                     (lsf_q35_phase == 2 && lsf_old == 0x0503 && val == 0x0103))) {\n'
         b'            _exit(75);\n'
         b'        }\n'),
        (b'        lsf_net_status = lsf_net->status;\n'
         b'        for (lsf_region = 0; lsf_region < PCI_NUM_REGIONS; ++lsf_region) {\n',
         b'        lsf_net_status = lsf_net->status;\n'
         b'        memcpy(lsf_regions, pci_dev->io_regions, sizeof(lsf_regions));\n'
         b'        for (lsf_region = 0; lsf_region < PCI_NUM_REGIONS; ++lsf_region) {\n'),
        (b'            pci_get_word(pci_dev->config + PCI_COMMAND) != (uint16_t)val)\n',
         b'            pci_get_word(pci_dev->config + PCI_COMMAND) !=\n'
         b'                (lsf_bar3 ? 0x0103 : (uint16_t)val) ||\n'
         b'            (lsf_bar3 && (pci_get_long(pci_dev->config + PCI_BASE_ADDRESS_3) ||\n'
         b'                pci_get_long(pci_dev->wmask + PCI_BASE_ADDRESS_3) ||\n'
         b'                pci_get_long(pci_dev->w1cmask + PCI_BASE_ADDRESS_3) ||\n'
         b'                pci_dev->io_regions[3].size ||\n'
         b'                (proxy->config_cap && proxy->config_cap < 0x40) ||\n'
         b'                (pci_dev->msi_cap && pci_dev->msi_cap < 0x40) ||\n'
         b'                (pci_dev->msix_cap && pci_dev->msix_cap < 0x40) ||\n'
         b'                (pci_dev->exp.exp_cap && pci_dev->exp.exp_cap < 0x40) ||\n'
         b'                (pci_dev->exp.ats_cap && pci_dev->exp.ats_cap < 0x100) ||\n'
         b'                (pci_dev->exp.sriov_cap && pci_dev->exp.sriov_cap < 0x100))))\n'),
        (b'            if (r->size && r->addr != pci_bar_address(pci_dev, lsf_region, r->type, r->size))\n'
         b'                _exit(75);\n'
         b'        }\n'
         b'        ++lsf_q35_phase;\n'
         b'        qemu_log("lsf_q35_virtio_guard old=0x%x new=0x%x phase=%u status=0 isr=0 disabled=1 broken=0 started=0 kick=0 vhost=0 ioeventfd=0 grabbed=0 irq=0 master=0 vga=0 peer=0 waiting=0 netVhost=0 queues=1 netStable=1 mappings=stable bql=1\\n",\n'
         b'                 lsf_old, (unsigned int)val, lsf_q35_phase);\n',
         b'            if ((r->size && r->addr != pci_bar_address(pci_dev, lsf_region, r->type, r->size)) ||\n'
         b'                r->size != lsf_regions[lsf_region].size ||\n'
         b'                r->addr != lsf_regions[lsf_region].addr ||\n'
         b'                r->type != lsf_regions[lsf_region].type ||\n'
         b'                r->memory != lsf_regions[lsf_region].memory ||\n'
         b'                r->address_space != lsf_regions[lsf_region].address_space)\n'
         b'                _exit(75);\n'
         b'        }\n'
         b'        ++lsf_q35_phase;\n'
         b'        if (lsf_bar3) {\n'
         b'            qemu_log("lsf_q35_bar3_guard phase=%u saved=0 wmask=0 w1cmask=0 region=0 mappings=stable bql=1\\n", lsf_q35_phase);\n'
         b'        } else {\n'
         b'            qemu_log("lsf_q35_virtio_guard old=0x%x new=0x%x phase=%u status=0 isr=0 disabled=1 broken=0 started=0 kick=0 vhost=0 ioeventfd=0 grabbed=0 irq=0 master=0 vga=0 peer=0 waiting=0 netVhost=0 queues=1 netStable=1 mappings=stable bql=1\\n",\n'
         b'                     lsf_old, (unsigned int)val, lsf_q35_phase);\n'
         b'        }\n'),
    ]
    result = raw
    for old, new in changes:
        require(result.count(old) == 1 and result.count(new) == 0, 'unique-anchor')
        result = result.replace(old, new, 1)
    inverse = result
    for old, new in reversed(changes):
        require(inverse.count(new) == 1, 'unique-inverse')
        inverse = inverse.replace(new, old, 1)
    require(inverse == raw, 'exact-inverse')
    return result, {'sourceBytes':len(raw), 'sourceSha256':hashlib.sha256(raw).hexdigest(),
        'derivedBytes':len(result), 'derivedSha256':hashlib.sha256(result).hexdigest(),
        'originalSourceInverseExact':True, 'failStopExit':75, 'qemuExecuted':False,
        'fullBarSizing':False, 'physicalBankRetired':False}
