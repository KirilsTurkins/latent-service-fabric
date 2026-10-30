"""Uninstalled q35/KVM direct-vector MSI-X domain and table ownership.

No descriptor/action route opens. Consumer and runtime/fit gates remain closed.
Eight complete C/H materials are separate, pinned research source files.
"""
import hashlib
import json
from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_device_security import function
from tools.host_stream_kernel_cleanup_native import require

INPUT_SHA = '926cbb1c339cf059b8e18f9da2b397edce740e2b56142a6b643243f5151d326b'
PROFILE = {'qemuVersion': '11.1.2', 'qemuCommit': '4fc49f46dc95d4a27de2509e7fceb2931e91faeb', 'machine': 'pc-q35-11.1', 'acceleration': 'kvm', 'virtualIommu': False, 'linuxCommit': '7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e', 'selectedConfigSha256': '0015c9ac3b9af98af1e4a0f88788321e96193ce6a387c5a6cec6eaa358cdc1d6', 'runtimeQualified': False, 'sharedControllerFundingQualified': False}
PREIMAGES = {
    'kernel/irq/msi.c': (50214, 'b382329d42a41244a01ca80be5ff068a5f6fa111a946df89da186c6fd1d4d00b'),
    'kernel/irq/lsf-stream-msi-context.c': (3473, '544c1b3c9c01707de564a87d949d4b0659d1e9c0869b898be31ca5e23b99c812'),
    'drivers/pci/msi/irqdomain.c': (13656, 'fc30980cb3c5e3165b029e0890d72e1f212b3dd104d12dc11cc1a28f99c265fa'),
    'net/factory.c': (38199, '210b403a1f4537650e002b633a6d91a908e9b8c36caf7551b248b5934b9a31ec'),
    'net/device-prepaid.h': (19576, '6931c6a8d132775a16d6c0ca355f808ea26c945ca1057696b1513ab4e3ee1f18'),
}
PRIMARY = {
    'kernel/irq/irqdomain.c': (59948, '0715731e7132f88d8d7b9969ce2aa6d5c0a44deba9114f7cd2d5ef7a543ae066'),
    'arch/x86/kernel/apic/msi.c': (11577, 'e22d0bbefafc0c65282b8f4183aa3c4f3f911d511fb98ce15c9b28906178e2ce'),
    'arch/x86/kernel/apic/vector.c': (37921, '58f24baf4e401325e04da562a2a8d2378011df2754baf6b378d9edb0fee59c97'),
    'drivers/pci/msi/msi.c': (24509, 'd6b01b235f74ff8bd9165aa5f6e49a5cc667569b9487823195c82969dd96bd7d'),
}
CONTEXT = {
    'include/linux/irqdomain.h': (25343, '7c9185fed0d9df2c50f59472aac2f1f0ac004f9d0a7eca8b1c0cf44fc8bbe3a1'),
    'include/linux/msi.h': (22537, 'd37a906db082c3cc96699e0e812e136d9ab5a324b30c43658828c7f6eef4a068'),
    'arch/x86/include/asm/irqdomain.h': (1834, '9fda691001698d9dc5f4842276b72f0a41aebba31459185a0a334742083378c6'),
}
MATERIAL_PINS = {
    'arch/x86/kernel/apic/lsf-stream-q35-msi-parent.c': (727, '48a6a08199e571f270250009e5e6499728b54c9132e73f17eb677a2beed7317d'),
    'arch/x86/kernel/apic/lsf-stream-q35-vector.c': (245, 'b4fd06a4e1c7fc0ad28c22be89cc62bae4433e3faeac6e83e4866db3307bd289'),
    'drivers/pci/msi/lsf-stream-q35-table.c': (4238, '7f529fc8a21eea42b510029a25691b6f081ca955d0bacca3be005172a90ecafc'),
    'drivers/pci/msi/lsf-stream-q35-template.c': (210, 'a4c6f19f41bd6cffe1a40c3c37270a745c10079d05a05ee74e2e16819dda22ba'),
    'include/net/lsf_stream_q35_msi_private.h': (2566, '79ba3712b1dfe5c89e1a5085d6e6593861aed3c9f795878eba0b2294448f9889'),
    'kernel/irq/lsf-stream-q35-domain.c': (10375, '1e70a5f85018dc0adcb6a0150cf041026442a4d9626671b421f914abcf4ae23b'),
    'kernel/irq/lsf-stream-q35-msi.c': (7276, '0c3ca78cc13032f8e9d0075f7bb889c9a70bc330cdc0beb2127921208af7653a'),
    'net/factory-stream-q35-msi.c': (11271, '20ed7fe146a97bc545e963e807920db421c9b42e94ae7d46fca81b478a4a7eae'),
}
from pathlib import Path
from tools.rust_capsule_project import read_file
ROOT = Path(__file__).resolve().parents[4]
MATERIAL_PATHS = {'arch/x86/kernel/apic/lsf-stream-q35-msi-parent.c': 'research/standard-outbound/linux-6.12-lineage/q35-msi/lsf-stream-q35-msi-parent.c', 'arch/x86/kernel/apic/lsf-stream-q35-vector.c': 'research/standard-outbound/linux-6.12-lineage/q35-msi/lsf-stream-q35-vector.c', 'drivers/pci/msi/lsf-stream-q35-table.c': 'research/standard-outbound/linux-6.12-lineage/q35-msi/lsf-stream-q35-table.c', 'drivers/pci/msi/lsf-stream-q35-template.c': 'research/standard-outbound/linux-6.12-lineage/q35-msi/lsf-stream-q35-template.c', 'include/net/lsf_stream_q35_msi_private.h': 'research/standard-outbound/linux-6.12-lineage/q35-msi/lsf_stream_q35_msi_private.h', 'kernel/irq/lsf-stream-q35-domain.c': 'research/standard-outbound/linux-6.12-lineage/q35-msi/lsf-stream-q35-domain.c', 'kernel/irq/lsf-stream-q35-msi.c': 'research/standard-outbound/linux-6.12-lineage/q35-msi/lsf-stream-q35-msi.c', 'net/factory-stream-q35-msi.c': 'research/standard-outbound/linux-6.12-lineage/q35-msi/factory-stream-q35-msi.c'}

def _bound(raw, pin):
    return type(raw) is bytes and len(raw) == pin[0] and hashlib.sha256(raw).hexdigest() == pin[1]


def materials(root=ROOT):
    require(type(MATERIAL_PATHS) is dict and set(MATERIAL_PATHS) == set(MATERIAL_PINS) and
        len(set(MATERIAL_PATHS.values())) == len(MATERIAL_PINS) == 8, 'q35-material-membership')
    result = {}
    for name, pin in MATERIAL_PINS.items():
        raw = read_file(root / MATERIAL_PATHS[name], pin[0])
        require(_bound(raw, pin) and b'\r' not in raw, 'q35-material-identity')
        result[name] = raw
    require(sum(map(len, result.values())) <= 128 * 1024, 'q35-whole-material-bound')
    return result


def _wrap(original, branch):
    at = original.index('\n{\n')
    return original[:at] + '\n{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' + branch + '#endif\n' + original[at+1:] + '}\n'


def edit_inputs(affected, primary):
    """Only this new append stage; old 439 projection is never replayed here."""
    require(type(affected) is dict and set(affected) == set(PREIMAGES), 'q35-affected-set')
    require(type(primary) is dict and set(primary) == set(PRIMARY) | set(CONTEXT), 'q35-native-set')
    for name, pin in PREIMAGES.items(): require(_bound(affected[name], pin), 'q35-derived-whole-preimage')
    for name, pin in {**PRIMARY, **CONTEXT}.items(): require(_bound(primary[name], pin), 'q35-exact-native-input')
    result = dict(affected)
    result.update({name: primary[name] for name in PRIMARY})
    def editor(name, anchor=None):
        edit = Editor(result[name].decode('utf-8'))
        if anchor is not None:
            edit.edit(anchor, anchor + '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_q35_msi_private.h>\n#endif\n')
        return edit
    def append(edit, path):
        edit.edit(edit.text, edit.text + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "' + path + '"\n#endif\n')

    msi = editor('kernel/irq/msi.c', '#include <linux/xarray.h>\n')
    old = function(msi.text, 'bool msi_create_device_irq_domain(')
    msi.edit(old, _wrap(old,
        '\tint selected = lsf_factory_stream_msi_selected(dev);\n'
        '\tif (selected) {\n'
        '\t\tif (selected < 0) { lsf_factory_stream_constructor_retain_unknown(); return false; }\n'
        '\t\treturn lsf_q35_msi_create(dev, domid, template, hwsize, domain_data, chip_data);\n\t}\n'))
    old = function(msi.text, 'void msi_remove_device_irq_domain(')
    msi.edit(old, _wrap(old,
        '\tint selected = lsf_factory_stream_msi_selected(dev);\n'
        '\tif (selected) {\n'
        '\t\tif (selected < 0) { lsf_factory_stream_constructor_retain_unknown(); return; }\n'
        '\t\tlsf_q35_msi_remove(dev, domid); return;\n\t}\n'))
    append(msi, 'lsf-stream-q35-msi.c')
    result['kernel/irq/msi.c'] = msi.finish().encode()

    context = editor('kernel/irq/lsf-stream-msi-context.c', '#include <net/lsf_stream_msi_context_private.h>\n')
    context.edit('(domain && (domain != dev->msi.domain || irq_domain_is_msi_device(domain)))',
        '(domain && (domain == dev->msi.domain ? irq_domain_is_msi_device(domain) :\n'
        '                !lsf_q35_msi_domain_known(dev, domain)))')
    result['kernel/irq/lsf-stream-msi-context.c'] = context.finish().encode()

    pci = editor('drivers/pci/msi/irqdomain.c')
    old = function(pci.text, 'bool pci_setup_msix_device_domain(')
    before = ('\tint selected = lsf_factory_stream_msi_selected(&pdev->dev);\n'
        '\tif (selected) {\n\t\t/* No original paid device-domain provider exists here. */\n'
        '\t\tif (selected < 0) lsf_factory_stream_constructor_retain_unknown();\n'
        '\t\treturn false;\n\t}\n')
    after = ('\tint selected = lsf_factory_stream_msi_selected(&pdev->dev);\n'
        '\tif (selected && (selected < 0 || !lsf_q35_x86_parent_known(dev_get_msi_domain(&pdev->dev)) ||\n'
        '\t    lsf_q35_msi_current(&pdev->dev) < 0)) {\n'
        '\t\tif (selected < 0) lsf_factory_stream_constructor_retain_unknown();\n'
        '\t\treturn false;\n\t}\n')
    require(old.count(before) == 1, 'q35-exact-existing-msix-cut')
    pci.edit(old, old.replace(before, after, 1))
    pci.edit('#include <linux/of_irq.h>\n', '#include <linux/of_irq.h>\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_q35_msi_private.h>\n#endif\n')
    append(pci, 'lsf-stream-q35-template.c')
    result['drivers/pci/msi/irqdomain.c'] = pci.finish().encode()

    domain = editor('kernel/irq/irqdomain.c', '#include <linux/fs.h>\n')
    old = function(domain.text, 'static struct irq_domain *__irq_domain_create(')
    domain.edit(old, _wrap(old,
        '\tstruct device *actual;\n'
        '\tint selected = info && info->fwnode ?\n'
        '\t\tlsf_q35_msi_classify(info->fwnode, LSF_Q35_MSI_FWNODE, &actual) : 0;\n'
        '\tif (selected) {\n'
        '\t\tif (selected < 0) return ERR_PTR(-EOPNOTSUPP);\n'
        '\t\treturn lsf_q35_domain_create(info);\n\t}\n'))
    for prefix, call in [
        ('void irq_domain_free_fwnode(', 'lsf_q35_fwnode_free(fwnode)'),
        ('static void irq_domain_free(', 'lsf_q35_domain_free(domain)'),
        ('void irq_domain_remove(', 'lsf_q35_domain_remove(domain)'),
        ('void irq_domain_update_bus_token(', 'lsf_q35_domain_bus_token(domain, bus_token)')]:
        old = function(domain.text, prefix)
        domain.edit(old, _wrap(old,
            '\tint selected = ' + call + ';\n'
            '\tif (selected) {\n'
            '\t\tif (selected < 0) lsf_factory_stream_constructor_retain_unknown();\n'
            '\t\treturn;\n\t}\n'))
    append(domain, 'lsf-stream-q35-domain.c')
    result['kernel/irq/irqdomain.c'] = domain.finish().encode()

    table = editor('drivers/pci/msi/msi.c', '#include <linux/irqdomain.h>\n')
    old = function(table.text, 'static int msix_capability_init(')
    prototype = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        'static int lsf_q35_msix_capability_init(struct pci_dev *, struct msix_entry *, int, struct irq_affinity *);\n'
        '#endif\n')
    table.edit(old, prototype + _wrap(old,
        '\tint selected = lsf_factory_stream_msi_selected(&dev->dev);\n'
        '\tif (selected) {\n'
        '\t\tif (selected < 0) return -EOPNOTSUPP;\n'
        '\t\treturn lsf_q35_msix_capability_init(dev, entries, nvec, affd);\n\t}\n'))
    append(table, 'lsf-stream-q35-table.c')
    result['drivers/pci/msi/msi.c'] = table.finish().encode()

    for name, part in [('arch/x86/kernel/apic/msi.c', 'lsf-stream-q35-msi-parent.c'),
                       ('arch/x86/kernel/apic/vector.c', 'lsf-stream-q35-vector.c')]:
        edit = editor(name)
        append(edit, part)
        result[name] = edit.finish().encode()
    kinds = editor('net/device-prepaid.h')
    kinds.edit('    return kind == LSF_STREAM_MSI_CONTEXT_DR ||',
        '    return (kind >= 0x1a0u && kind < 0x1a6u) || kind == LSF_STREAM_MSI_CONTEXT_DR ||')
    result['net/device-prepaid.h'] = kinds.finish().encode()
    factory = editor('net/factory.c')
    append(factory, 'factory-stream-q35-msi.c')
    result['net/factory.c'] = factory.finish().encode()
    return result


def transform(outputs, primary):
    require(type(outputs) is dict and len(outputs) == 439 and
        all(type(n) is str and type(b) is bytes for n, b in outputs.items()), 'q35-whole-input-shape')
    encoded = (json.dumps({n: {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()}
        for n, b in outputs.items()}, sort_keys=True, separators=(',', ':')) + '\n').encode()
    require(hashlib.sha256(encoded).hexdigest() == INPUT_SHA, 'q35-whole-msi439-input')
    require(not(set(PRIMARY) & set(outputs)), 'q35-native-paths-new')
    result = dict(outputs)
    result.update(edit_inputs({n: outputs[n] for n in PREIMAGES}, primary))
    parts = materials()
    require(not(set(parts) & set(result)), 'q35-materials-new')
    result.update(parts)
    require(len(result) == 451, 'q35-derived451-count')
    return result
