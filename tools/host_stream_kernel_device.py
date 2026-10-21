"""Uninstalled maintained PCI birth prefix; no device, RX or trusted bootstrap proof."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_packet as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent/'tests/fixtures/host_stream_kernel_device.json'
PCI = 'drivers/pci/probe.c'
IOV = 'drivers/pci/iov.c'
EXTRAS = {PCI, IOV, 'include/linux/pci.h', 'drivers/base/core.c',
          'lib/kobject.c', 'mm/util.c', 'lib/kasprintf.c', 'include/linux/mm.h',
          'include/asm-generic/sections.h'}
replace = prior.replace
require = prior.require
GATES = ('kernelBuilt', 'actualDeviceInitialized', 'trustedNativeBootstrapAuthenticated',
         'completeAllocationClosure', 'finalFreeCertified', 'productionInstallation')


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    parent = prior.fixture()
    require(value['upstreamCommit'] == parent['upstreamCommit'] and
        value['archiveSha256'] == parent['archiveSha256'], 'device-maintained-identity')
    require(set(value['source']) == set(parent['source']) | EXTRAS and
        all(value['source'][name] == row for name, row in parent['source'].items()),
        'device-whole-membership')
    require(all(value[name] is False for name in GATES), 'device-uninstalled')
    require(len(value['sections']) == 19, 'device-definition-membership')
    return value


def section(text, name):
    row = fixture()['sections'][name]
    starts = [i for i in range(len(text)) if text.startswith(row['prefix'], i) and
        (not i or text[i - 1] == '\n')]
    require(len(starts) == 1, 'device-definition-occurrence')
    end = text.find('\n}\n', starts[0])
    require(end >= 0, 'device-definition-end')
    raw = text[starts[0]:end + 3]
    require(raw == row['text'] and len(raw.encode()) == row['bytes'] and
        hashlib.sha256(raw.encode()).hexdigest() == row['sha256'], 'device-definition-preimage')
    return raw


def authenticate(inputs):
    value = fixture()
    require(set(inputs) == set(value['source']), 'device-whole-membership')
    maintained = prior.prior.route.bind.avc.maintained
    maintained.authenticate_files(inputs, value['source'])
    prior.authenticate({name: inputs[name] for name in prior.fixture()['source']})
    for name, row in value['sections'].items():
        section(inputs[row['source']].decode(), name)


def private(raw, name):
    require(name in ('pci_alloc_dev', 'pci_setup_device', 'pci_scan_device', 'pci_scan_single_device') and
        section(raw, name) == raw, 'device-private-preimage')
    declaration, body = raw.split('\n{\n', 1)
    declaration = replace(declaration, name + '(', 'lsf_prepaid_' + name + '(')
    if name == 'pci_alloc_dev':
        declaration = replace(declaration, 'struct pci_bus *bus)', 'struct pci_bus *bus, int devfn)')
        body = replace(body, '\tdev = kzalloc(sizeof(struct pci_dev), GFP_KERNEL);\n',
            '\tdev = lsf_factory_device_pci_allocate(pci_domain_nr(bus), bus->number,\n'
            '\t\tdevfn, sizeof(struct pci_dev));\n')
    elif name == 'pci_setup_device':
        # Only this exact whole born view and coordinate may use the immutable
        # spelling. Real kernel rodata membership is checked before any setup
        # effect; missing image placement refuses instead of kstrdup fallback.
        body = replace(body, '\thdr_type = pci_hdr_type(dev);\n',
            '\tif (lsf_factory_device_pci_owned(dev, sizeof(*dev)) != 1)\n'
            '\t\treturn -EOPNOTSUPP;\n'
            '\tif (!lsf_factory_device_selected(pci_domain_nr(dev->bus), dev->bus->number, dev->devfn) ||\n'
            '\t    dev->vendor != LSF_DEVICE_PCI_VENDOR || dev->device != LSF_DEVICE_PCI_DEVICE ||\n'
            '\t    !is_kernel_rodata((unsigned long)LSF_DEVICE_PCI_NAME))\n'
            '\t\treturn -EOPNOTSUPP;\n\n'
            '\thdr_type = pci_hdr_type(dev);\n')
        body = replace(body,
            '\tdev_set_name(&dev->dev, "%04x:%02x:%02x.%d", pci_domain_nr(dev->bus),\n'
            '\t\t     dev->bus->number, PCI_SLOT(dev->devfn),\n'
            '\t\t     PCI_FUNC(dev->devfn));\n',
            '\tdev_set_name(&dev->dev, LSF_DEVICE_PCI_NAME);\n')
    elif name == 'pci_scan_device':
        body = replace(body, '\tu32 l;\n', '\tu32 l;\n\n'
            '\tif (!lsf_factory_device_pci_ready(pci_domain_nr(bus), bus->number, devfn))\n'
            '\t\treturn NULL;\n')
        body = replace(body, '\tdev = pci_alloc_dev(bus);\n',
            '\t/* Reject a changed/non-modern identity BEFORE the real birth. */\n'
            '\tif ((l & 0xffff) != LSF_DEVICE_PCI_VENDOR ||\n'
            '\t    (l >> 16) != LSF_DEVICE_PCI_DEVICE)\n\t\treturn NULL;\n\n'
            '\tdev = lsf_prepaid_pci_alloc_dev(bus, devfn);\n')
        body = replace(body, '\tif (pci_setup_device(dev)) {\n',
            '\tif (lsf_prepaid_pci_setup_device(dev)) {\n')
        body = replace(body, '\t\tkfree(dev);\n',
            '\t\t(void)lsf_factory_device_pci_return(dev);\n')
    else:
        body = replace(body, '\tstruct pci_dev *dev;\n', '\tstruct pci_dev *dev;\n\n'
            '\tif (!lsf_factory_device_pci_enter(pci_domain_nr(bus), bus->number, devfn))\n'
            '\t\treturn NULL;\n')
        # A previously discovered normal device is not retroactively adopted.
        body = replace(body, '\t\treturn dev;\n', '\t\tdev = NULL;\n\t\tgoto out;\n')
        body = replace(body, '\tdev = pci_scan_device(bus, devfn);\n',
            '\tdev = lsf_prepaid_pci_scan_device(bus, devfn);\n')
        body = replace(body, '\tif (!dev)\n\t\treturn NULL;\n',
            '\tif (!dev)\n\t\tgoto out;\n')
        body = replace(body, '\treturn dev;\n',
            'out:\n\tlsf_factory_device_pci_leave();\n\treturn dev;\n')
    return declaration + '\n{\n' + body


def scan_routing(raw):
    require(section(raw, 'pci_scan_single_device') == raw, 'device-scan-dispatch-preimage')
    declaration, body = raw.split('\n{\n', 1)
    selected = declaration + '\n{\n'
    selected += '\tif (lsf_factory_device_selected(pci_domain_nr(bus), bus->number, devfn))\n'
    selected += '\t\treturn lsf_prepaid_pci_scan_single_device(bus, devfn);\n\t{\n' + body + '}\n'
    return '#ifdef CONFIG_LSF_STREAM_FACTORY\n' + selected + '#else\n' + raw + '#endif\n'


def final_routing(raw):
    require(section(raw, 'pci_release_dev') == raw, 'device-final-return-preimage')
    return replace(raw, '\tkfree(pci_dev);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (lsf_factory_device_pci_return(pci_dev))\n\t\treturn;\n#endif\n'
        '\tkfree(pci_dev);\n')


def vf_routing(raw):
    require(section(raw, 'pci_iov_add_virtfn') == raw, 'device-vf-dispatch-preimage')
    declaration, body = raw.split('\n{\n', 1)
    selected = declaration + '\n{\n'
    # These authenticated upstream helpers only read the original PF geometry.
    # Refuse BEFORE virtfn_add_bus can allocate a new bus or PCI device.
    selected += '\tif (lsf_factory_device_selected(pci_domain_nr(dev->bus),\n'
    selected += '\t\tpci_iov_virtfn_bus(dev, id), pci_iov_virtfn_devfn(dev, id)))\n'
    selected += '\t\treturn -EOPNOTSUPP;\n\t{\n' + body + '}\n'
    return '#ifdef CONFIG_LSF_STREAM_FACTORY\n' + selected + '#else\n' + raw + '#endif\n'


def derive(inputs):
    authenticate(inputs)
    outputs = prior.derive({name: inputs[name] for name in prior.fixture()['source']})
    for name in EXTRAS:
        outputs[name] = inputs[name]
    text = outputs['net/factory-private.h'].decode()
    text = replace(text, '#include "prepaid.h"\n',
        '#include "prepaid.h"\n#include <net/lsf_stream_device_private.h>\n')
    outputs['net/factory-private.h'] = text.encode()
    text = outputs['net/factory.c'].decode()
    text = replace(text, '#include "factory-private.h"\n',
        '#include "factory-private.h"\n#include "device-prepaid.h"\n')
    text = replace(text, 'static struct {\n    struct lsf_prepaid pool;\n',
        'struct lsf_factory_device_state;\nstatic struct {\n    struct lsf_prepaid pool;\n')
    text = replace(text, '    struct page *pages;\n',
        '    struct lsf_factory_device_state *device;\n    struct page *pages;\n')
    text = replace(text, 'static int lsf_factory_open(struct inode *inode, struct file *file)\n',
        '#include "factory-device.c"\n\n'
        'static int lsf_factory_open(struct inode *inode, struct file *file)\n')
    text = replace(text, '    factory.opened = 1;\n    file->private_data = &factory;\n',
        '    factory.opened = 1;\n'
        '    error = lsf_factory_device_initialize();\n    if (error)\n        goto out;\n'
        '    file->private_data = &factory;\n')
    text = replace(text, '        factory.pool.contexts[i].closed = 1;\n',
        '        factory.pool.contexts[i].closed = 1;\n'
        '    if (factory.device)\n'
        '        (void)lsf_device_close(&factory.pool, factory.device->key);\n')
    outputs['net/factory.c'] = text.encode()
    for source, target in (('device-prepaid.h', 'net/device-prepaid.h'),
        ('device-private.h', 'include/net/lsf_stream_device_private.h'),
        ('factory-device.c', 'net/factory-device.c')):
        outputs[target] = (OWNED/source).read_bytes()
    original = inputs[PCI].decode()
    text = replace(original, '#include "pci.h"\n',
        '#include "pci.h"\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include <net/lsf_stream_device_private.h>\n#include <asm/sections.h>\n#endif\n')
    # Private constructors are defined after pci_dev_type and their upstream
    # static dependencies, before any selected enumeration call.
    anchor = section(original, 'pci_scan_single_device')
    clones = '\n'.join(private(section(original, name), name) for name in
        ('pci_alloc_dev', 'pci_setup_device', 'pci_scan_device', 'pci_scan_single_device'))
    text = replace(text, anchor, '#ifdef CONFIG_LSF_STREAM_FACTORY\n' + clones +
        '\n#endif\n' + scan_routing(anchor))
    raw = section(original, 'pci_release_dev')
    text = replace(text, raw, final_routing(raw))
    outputs[PCI] = text.encode()
    text = inputs[IOV].decode()
    text = replace(text, '#include "pci.h"\n',
        '#include "pci.h"\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include <net/lsf_stream_device_private.h>\n#endif\n')
    raw = section(text, 'pci_iov_add_virtfn')
    outputs[IOV] = replace(text, raw, vf_routing(raw)).encode()
    return outputs
