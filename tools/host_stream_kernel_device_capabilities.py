"""Uninstalled original PCI saved-capability births and final capability frees."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_device_core as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_device_capabilities.json'
PCI = 'drivers/pci/pci.c'
EXTRAS = {PCI}
DEFINITIONS = {'pci_add_saved_cap', '_pci_add_cap_save_buffer', 'pci_allocate_cap_save_buffers',
    'pci_free_cap_save_buffers'}
GATES = prior.GATES + ('actualDeviceCapabilitiesExecuted', 'completeCapabilitiesClosure')
replace = prior.replace
require = prior.require


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    parent = prior.fixture()
    require(value['schemaVersion'] == 'lsf.kernel-device-capabilities-source.v1' and
        value['upstreamCommit'] == parent['upstreamCommit'] and
        value['archiveSha256'] == parent['archiveSha256'], 'device-capabilities-maintained-identity')
    require(set(value['source']) == set(parent['source']) | EXTRAS and
        all(value['source'][name] == row for name, row in parent['source'].items()),
        'device-capabilities-whole-membership')
    require(set(value['sections']) == set(parent['sections']) | DEFINITIONS and
        all(value['sections'][name] == row for name, row in parent['sections'].items()),
        'device-capabilities-original-definitions')
    require(all(value[name] is False for name in GATES), 'device-capabilities-uninstalled')
    return value


def section(text, name):
    row = fixture()['sections'][name]
    starts = [i for i in range(len(text)) if text.startswith(row['prefix'], i) and
        (not i or text[i - 1] == '\n')]
    require(len(starts) == 1, 'device-capabilities-definition-occurrence')
    end = text.find('\n}\n', starts[0])
    require(end >= 0, 'device-capabilities-definition-end')
    raw = text[starts[0]:end + 3]
    require(raw == row['text'] and len(raw.encode()) == row['bytes'] and
        hashlib.sha256(raw.encode()).hexdigest() == row['sha256'],
        'device-capabilities-definition-preimage')
    return raw


def authenticate(inputs):
    value = fixture()
    require(set(inputs) == set(value['source']), 'device-capabilities-whole-membership')
    prior.prior.prior.prior.prior.route.bind.avc.maintained.authenticate_files(inputs, value['source'])
    prior.authenticate({name: inputs[name] for name in prior.fixture()['source']})
    for name, row in value['sections'].items():
        section(inputs[row['source']].decode(), name)


def private_allocate(raw):
    require(section(raw, '_pci_add_cap_save_buffer') == raw, 'device-capabilities-allocator-preimage')
    text = replace(raw, 'static int _pci_add_cap_save_buffer(',
        'int lsf_prepaid_pci_add_cap_save_buffer(')
    # Original capability lookup and hlist publication remain. Its exact actual
    # sizeof+payload replaces only the original allocation after a live-owner
    # check. There is no synthetic successful capability or skipped callback.
    text = replace(text, '\tstruct pci_cap_saved_state *save_state;\n',
        '\tstruct pci_cap_saved_state *save_state;\n\n'
        '\tif (lsf_factory_device_capabilities_owned(dev) != 1)\n'
        '\t\treturn -EOPNOTSUPP;\n')
    return replace(text, 'save_state = kzalloc(sizeof(*save_state) + size, GFP_KERNEL);',
        'save_state = lsf_factory_device_capability_allocate(dev, sizeof(*save_state) + size);')


def allocator_dispatch(raw):
    require(section(raw, '_pci_add_cap_save_buffer') == raw, 'device-capabilities-dispatch-preimage')
    declaration, body = raw.split('\n{\n', 1)
    return declaration + '\n{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' + (
        '\tint lsf_owned = lsf_factory_device_capabilities_owned(dev);\n'
        '\tif (lsf_owned < 0)\n\t\treturn -EOPNOTSUPP;\n'
        '\tif (lsf_owned)\n'
        '\t\treturn lsf_prepaid_pci_add_cap_save_buffer(dev, cap, extended, size);\n'
        '\t{\n#endif\n') + body[:-2] + '#ifdef CONFIG_LSF_STREAM_FACTORY\n\t}\n#endif\n}\n'


def final_return(raw):
    require(section(raw, 'pci_free_cap_save_buffers') == raw, 'device-capabilities-free-preimage')
    return replace(raw, '\t\tkfree(tmp);\n', '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\tif (!lsf_factory_device_capability_return(dev, tmp))\n\t\t\tkfree(tmp);\n'
        '#else\n\t\tkfree(tmp);\n#endif\n')


def derive(inputs):
    authenticate(inputs)
    outputs = prior.derive({name: inputs[name] for name in prior.fixture()['source']})
    text = replace(inputs[PCI].decode(), '#include "pci.h"\n',
        '#include "pci.h"\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include <net/lsf_stream_device_capabilities.h>\n#endif\n')
    original = section(inputs[PCI].decode(), '_pci_add_cap_save_buffer')
    text = replace(text, original, '#ifdef CONFIG_LSF_STREAM_FACTORY\n' +
        private_allocate(original) + '#endif\n' + allocator_dispatch(original))
    original = section(inputs[PCI].decode(), 'pci_free_cap_save_buffers')
    outputs[PCI] = replace(text, original, final_return(original)).encode()
    text = replace(outputs['net/device-prepaid.h'].decode(),
        '    LSF_DEVICE_CORE_PRIVATE\n', '    LSF_DEVICE_CORE_PRIVATE,\n    LSF_DEVICE_CAP_SAVE\n')
    outputs['net/device-prepaid.h'] = replace(text,
        'kind == LSF_DEVICE_CORE_PRIVATE;',
        'kind == LSF_DEVICE_CORE_PRIVATE || kind == LSF_DEVICE_CAP_SAVE;').encode()
    text = replace(outputs['net/factory.c'].decode(), '#include <net/lsf_stream_device_core.h>\n',
        '#include <net/lsf_stream_device_core.h>\n#include <net/lsf_stream_device_capabilities.h>\n')
    text = replace(text, '#include "factory-device-core.c"\n',
        '#include "factory-device-core.c"\n#include "factory-device-capabilities.c"\n')
    outputs['net/factory.c'] = text.encode()
    outputs['include/net/lsf_stream_device_capabilities.h'] = (
        OWNED / 'device-capabilities-private.h').read_bytes()
    outputs['net/factory-device-capabilities.c'] = (OWNED / 'factory-device-capabilities.c').read_bytes()
    return outputs
