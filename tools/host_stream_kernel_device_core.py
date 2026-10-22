"""Uninstalled actual driver-core metadata and original kobject-tail ownership."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_device_firmware as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_device_core.json'
CORE = 'drivers/base/core.c'
KOBJECT = 'lib/kobject.c'
EXTRAS = {'drivers/base/base.h', 'include/linux/device.h', 'include/linux/kobject.h'}
DEFINITIONS = {'device_private_init', 'device_initialize', 'device_add'}
GATES = prior.GATES + ('actualDeviceCoreExecuted', 'completeDeviceCoreClosure')
replace = prior.replace
require = prior.require


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    parent = prior.fixture()
    require(value['schemaVersion'] == 'lsf.kernel-device-core-source.v1' and
        value['upstreamCommit'] == parent['upstreamCommit'] and
        value['archiveSha256'] == parent['archiveSha256'], 'device-core-maintained-identity')
    require(set(value['source']) == set(parent['source']) | EXTRAS and
        all(value['source'][name] == row for name, row in parent['source'].items()),
        'device-core-whole-membership')
    require(set(value['sections']) == set(parent['sections']) | DEFINITIONS and
        all(value['sections'][name] == row for name, row in parent['sections'].items()),
        'device-core-original-definitions')
    require(all(value[name] is False for name in GATES), 'device-core-uninstalled')
    return value


def section(text, name):
    row = fixture()['sections'][name]
    starts = [i for i in range(len(text)) if text.startswith(row['prefix'], i) and
        (not i or text[i - 1] == '\n')]
    require(len(starts) == 1, 'device-core-definition-occurrence')
    end = text.find('\n}\n', starts[0])
    require(end >= 0, 'device-core-definition-end')
    raw = text[starts[0]:end + 3]
    require(raw == row['text'] and len(raw.encode()) == row['bytes'] and
        hashlib.sha256(raw.encode()).hexdigest() == row['sha256'], 'device-core-definition-preimage')
    return raw


def authenticate(inputs):
    value = fixture()
    require(set(inputs) == set(value['source']), 'device-core-whole-membership')
    prior.prior.prior.prior.route.bind.avc.maintained.authenticate_files(inputs, value['source'])
    prior.authenticate({name: inputs[name] for name in prior.fixture()['source']})
    for name, row in value['sections'].items():
        section(inputs[row['source']].decode(), name)


def private_init(raw):
    require(section(raw, 'device_private_init') == raw, 'device-core-init-preimage')
    text = replace(raw, 'static int device_private_init(struct device *dev)',
        'int lsf_prepaid_device_private_init(struct device *dev)')
    text = replace(text, '{\n', '{\n\tif (lsf_factory_device_core_owned(dev) != 1)\n\t\treturn -EOPNOTSUPP;\n'
        '\tif (dev->p)\n\t\treturn -EOPNOTSUPP;\n')
    return replace(text, 'dev->p = kzalloc(sizeof(*dev->p), GFP_KERNEL);',
        'dev->p = lsf_factory_device_core_allocate(dev, sizeof(*dev->p));')


def metadata_free(expression):
    return ('#ifdef CONFIG_LSF_STREAM_FACTORY\n\t{\n'
        '\t\tint lsf_returned = lsf_factory_device_core_return(dev, ' + expression + ');\n'
        '\t\tif (!lsf_returned)\n\t\t\tkfree(' + expression + ');\n\t}\n'
        '#else\n\tkfree(' + expression + ');\n#endif\n')


def private_cleanup(raw):
    require(section(raw, 'kobject_cleanup') == raw, 'device-core-cleanup-preimage')
    text = replace(raw, 'static void kobject_cleanup(struct kobject *kobj)',
        'static void lsf_prepaid_kobject_cleanup(struct kobject *kobj)')
    return replace(text, '\tkobject_put(parent);\n',
        '\tkobject_put(parent);\n\tlsf_factory_device_core_tail_finish(kobj);\n')


def derive(inputs):
    authenticate(inputs)
    outputs = prior.derive({name: inputs[name] for name in prior.fixture()['source']})
    for name in EXTRAS:
        outputs[name] = inputs[name]
    header = '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_device_core.h>\n#endif\n'
    text = replace(outputs[CORE].decode(), '#include "power/power.h"\n',
        '#include "power/power.h"\n' + header)
    original = section(inputs[CORE].decode(), 'device_private_init')
    dispatch = replace(original, '{\n', '{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tint lsf_owned = lsf_factory_device_core_owned(dev);\n'
        '\tif (lsf_owned < 0)\n\t\treturn -EOPNOTSUPP;\n'
        '\tif (lsf_owned)\n\t\treturn lsf_prepaid_device_private_init(dev);\n#endif\n')
    text = replace(text, original, dispatch + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' +
        private_init(original) + '#endif\n')
    for name, expression in (('device_release', 'p'), ('device_add', 'dev->p')):
        raw = section(inputs[CORE].decode(), name)
        projected = replace(raw, '\tkfree(' + expression + ');\n', metadata_free(expression))
        text = replace(text, raw, projected)
    outputs[CORE] = text.encode()
    text = replace(outputs[KOBJECT].decode(), '#include <linux/random.h>\n',
        '#include <linux/random.h>\n' + header)
    original = section(inputs[KOBJECT].decode(), 'kobject_cleanup')
    text = replace(text, original, original + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' +
        private_cleanup(original) + '#endif\n')
    original = section(inputs[KOBJECT].decode(), 'kobject_release')
    dispatch = replace(original, '#else\n\tkobject_cleanup(kobj);\n',
        '#else\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tint lsf_owned = lsf_factory_device_core_tail_enter(kobj);\n'
        '\tif (lsf_owned < 0)\n\t\treturn;\n'
        '\tif (lsf_owned) {\n\t\tlsf_prepaid_kobject_cleanup(kobj);\n\t\treturn;\n\t}\n#endif\n'
        '\tkobject_cleanup(kobj);\n')
    outputs[KOBJECT] = replace(text, original, dispatch).encode()
    text = replace(outputs[prior.prior.PCI].decode(), '#include <net/lsf_stream_device_firmware.h>\n',
        '#include <net/lsf_stream_device_firmware.h>\n#include <net/lsf_stream_device_core.h>\n')
    # This exact private scan already owns the constructor mutex and complete
    # successful setup. Refusal uses the real failed-setup bus put/retirement.
    raw = prior.prior.private(prior.prior.fixture()['sections']['pci_scan_single_device']['text'],
        'pci_scan_single_device')
    selected = replace(raw, '\tpci_device_add(dev, bus);\n',
        '\tif (lsf_factory_device_core_begin(dev)) {\n'
        '\t\tpci_bus_put(dev->bus);\n\t\t(void)lsf_factory_device_pci_return(dev);\n'
        '\t\tlsf_factory_device_pci_leave();\n\t\treturn NULL;\n\t}\n'
        '\tpci_device_add(dev, bus);\n')
    outputs[prior.prior.PCI] = replace(text, raw, selected).encode()
    text = outputs['net/device-prepaid.h'].decode()
    text = replace(text, '    LSF_DEVICE_ACPI_REFERENCE\n',
        '    LSF_DEVICE_ACPI_REFERENCE,\n    LSF_DEVICE_CORE_PRIVATE\n')
    outputs['net/device-prepaid.h'] = replace(text,
        'kind == LSF_DEVICE_ACPI_REFERENCE;\n',
        'kind == LSF_DEVICE_ACPI_REFERENCE || kind == LSF_DEVICE_CORE_PRIVATE;\n').encode()
    text = outputs['net/factory-device-firmware.c'].decode()
    text = replace(text, '    struct work_struct work;\n    struct lsf_prepaid_ticket pci;\n',
        '    struct work_struct work;\n    struct lsf_prepaid_ticket pci, core_private;\n')
    text = replace(text, '    unsigned int revoked, retirement, queued, putting, returned;\n',
        '    unsigned int revoked, retirement, queued, putting, returned;\n'
        '    unsigned int core_initialized, core_tail_active, core_tail_complete;\n')
    text = replace(text, 'owned->putting || owned->returned || factory.device->constructor_active ||\n',
        'owned->putting || owned->returned || factory.device->constructor_active ||\n'
        '        (owned->core_initialized && !owned->core_tail_complete) ||\n')
    text = replace(text,
        'if (factory.device->constructor_active || !owned->retirement || owned->queued || owned->returned)\n',
        'if (factory.device->constructor_active || !owned->retirement || owned->queued || owned->returned ||\n'
        '        (owned->core_initialized && !owned->core_tail_complete))\n')
    outputs['net/factory-device-firmware.c'] = text.encode()
    text = replace(outputs['net/factory.c'].decode(), '#include <net/lsf_stream_device_firmware.h>\n',
        '#include <net/lsf_stream_device_firmware.h>\n#include <net/lsf_stream_device_core.h>\n')
    outputs['net/factory.c'] = replace(text, '#include "factory-device-firmware.c"\n',
        '#include "factory-device-firmware.c"\n#include "factory-device-core.c"\n').encode()
    outputs['net/factory-device-core.c'] = (OWNED / 'factory-device-core.c').read_bytes()
    outputs['include/net/lsf_stream_device_core.h'] = (OWNED / 'device-core-private.h').read_bytes()
    return outputs
