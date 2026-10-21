"""Uninstalled cached-ACPI setup subset; no AML, bootstrap or device proof."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_device as prior

OWNED=prior.OWNED
FIXTURE=Path(__file__).parent/'tests/fixtures/host_stream_kernel_device_firmware.json'
ACPI='drivers/pci/pci-acpi.c'
GLUE='drivers/acpi/glue.c'
BUS='drivers/acpi/bus.c'
SCAN='drivers/acpi/scan.c'
OSL='drivers/acpi/osl.c'
EXTRAS={ACPI,GLUE,BUS,SCAN,'include/linux/acpi.h','include/acpi/acpi_bus.h',
    'include/linux/pci-acpi.h','include/linux/fwnode.h',OSL,'drivers/acpi/internal.h',
    'lib/klist.c','include/linux/workqueue.h','include/linux/kref.h'}
DEFINITIONS={'pci_set_acpi_fwnode','acpi_pci_find_companion','pci_acpi_set_companion_lookup_hook',
    'pci_acpi_clear_companion_lookup_hook','find_child_checks','check_one_child','acpi_find_child',
    'acpi_find_child_device','acpi_scan_lock_acquire','acpi_scan_lock_release','acpi_scan_init',
    'acpi_dev_for_one_check','acpi_dev_for_each_child','device_for_each_child','next_device','set_primary_fwnode',
    'acpi_device_del_work_fn','acpi_scan_drop_device','acpi_device_del','acpi_device_release','acpi_device_add',
    'acpi_dev_get','acpi_dev_put','get_device','put_device','kobject_get','kobject_put','kobject_release',
    'klist_children_get','klist_children_put','klist_next','klist_iter_exit','klist_put',
    'acpi_queue_hotplug_work','acpi_os_initialize1','acpi_os_terminate'}
GATES=prior.GATES+('actualFirmwareExecuted','completeFirmwareClosure')
replace=prior.replace
require=prior.require


def fixture():
    value=json.loads(FIXTURE.read_bytes());parent=prior.fixture()
    require(value['upstreamCommit']==parent['upstreamCommit'] and value['archiveSha256']==parent['archiveSha256'],
        'device-firmware-maintained-identity')
    require(set(value['source'])==set(parent['source'])|EXTRAS and
        all(value['source'][name]==row for name,row in parent['source'].items()),'device-firmware-whole-membership')
    require(value['schemaVersion']=='lsf.kernel-device-firmware-source.v1' and
        set(value['sections'])==set(parent['sections'])|DEFINITIONS and
        all(value['sections'][name]==row for name,row in parent['sections'].items()),
        'device-firmware-original-definitions')
    require(all(value[name] is False for name in GATES),'device-firmware-uninstalled')
    return value


def section(text,name):
    row=fixture()['sections'][name]
    starts=[i for i in range(len(text)) if text.startswith(row['prefix'],i) and (not i or text[i-1]=='\n')]
    require(len(starts)==1,'device-firmware-definition-occurrence')
    end=text.find('\n}\n',starts[0]);require(end>=0,'device-firmware-definition-end')
    raw=text[starts[0]:end+3]
    require(raw==row['text'] and len(raw.encode())==row['bytes'] and hashlib.sha256(raw.encode()).hexdigest()==row['sha256'],
        'device-firmware-definition-preimage')
    return raw


def authenticate(inputs):
    value=fixture();require(set(inputs)==set(value['source']),'device-firmware-whole-membership')
    prior.prior.prior.route.bind.avc.maintained.authenticate_files(inputs,value['source'])
    prior.authenticate({name:inputs[name] for name in prior.fixture()['source']})
    for name,row in value['sections'].items():section(inputs[row['source']].decode(),name)


def companion(raw):
    require(section(raw,'acpi_pci_find_companion')==raw,'device-firmware-companion-preimage')
    declaration,body=raw.split('\n{\n',1)
    declaration=replace(declaration,'static struct acpi_device *acpi_pci_find_companion(struct device *dev)',
        'static int lsf_prepaid_acpi_pci_find_companion(struct device *dev, struct acpi_device **result)')
    body=replace(body,'\tu64 addr;\n','\tu64 addr;\n\tint error;\n')
    body=replace(body,'\tif (!dev->parent)\n\t\treturn NULL;\n',
        '\tif (!dev->parent) {\n\t\t*result = NULL;\n\t\treturn 0;\n\t}\n')
    # The caller owns these exact original locks and has checked the hook is
    # NULL while holding the SAME read semaphore. Do not recursively acquire.
    body=replace(body,'\tdown_read(&pci_acpi_companion_lookup_sem);\n\n','')
    body=replace(body,'\tup_read(&pci_acpi_companion_lookup_sem);\n\n','')
    body=replace(body,'\tif (adev)\n\t\treturn adev;\n',
        '\tif (adev) {\n\t\t*result = adev;\n\t\treturn 0;\n\t}\n')
    body=replace(body,'\tadev = acpi_find_child_device(ACPI_COMPANION(dev->parent), addr,\n\t\t\t\t      check_children);\n',
        '\terror = lsf_prepaid_acpi_find_child_device(pci_dev, ACPI_COMPANION(dev->parent), addr,\n'
        '\t\t\t\t      check_children, &adev);\n\tif (error)\n\t\treturn error;\n')
    body=replace(body,'\tif (adev && adev->pnp.type.platform_id && !addr &&\n\t    pci_is_root_bus(pci_dev->bus))\n\t\treturn NULL;\n',
        '\tif (adev && adev->pnp.type.platform_id && !addr &&\n\t    pci_is_root_bus(pci_dev->bus)) {\n'
        '\t\t*result = NULL;\n\t\treturn 0;\n\t}\n')
    body=replace(body,'\treturn adev;\n','\t*result = adev;\n\treturn 0;\n')
    return declaration+'\n{\n'+body


def deletion_worker(raw):
    require(section(raw,'acpi_device_del_work_fn')==raw,'device-firmware-delete-worker-preimage')
    text=replace(raw,'\t\tlist_del(&adev->del_list);\n',
        '\t\tlist_del(&adev->del_list);\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\tif (lsf_acpi_deletions_active == ~0u)\n\t\t\tlsf_acpi_deletion_uncertain = true;\n'
        '\t\telse\n\t\t\tlsf_acpi_deletions_active++;\n#endif\n')
    return replace(text,'\t\tacpi_dev_put(adev);\n',
        '\t\tacpi_dev_put(adev);\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\tmutex_lock(&acpi_device_del_lock);\n'
        '\t\tif (!lsf_acpi_deletions_active)\n\t\t\tlsf_acpi_deletion_uncertain = true;\n'
        '\t\telse\n\t\t\tlsf_acpi_deletions_active--;\n'
        '\t\tmutex_unlock(&acpi_device_del_lock);\n#endif\n')


def deletion_invalidation(raw):
    require(section(raw,'acpi_scan_drop_device')==raw,'device-firmware-invalidation-preimage')
    return replace(raw,'\tadev->handle = INVALID_ACPI_HANDLE;\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tlsf_factory_device_firmware_invalidate(adev, adev->handle);\n#endif\n'
        '\tadev->handle = INVALID_ACPI_HANDLE;\n')


def queue_lifecycle(raw,name):
    require(name in ('acpi_os_initialize1','acpi_os_terminate') and section(raw,name)==raw,
        'device-firmware-queue-lifecycle-preimage')
    if name=='acpi_os_initialize1':
        return replace(raw,'\tBUG_ON(!kacpi_hotplug_wq);\n',
            '\tBUG_ON(!kacpi_hotplug_wq);\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\tlsf_prepaid_acpi_reference_queue_state(true);\n#endif\n')
    return replace(raw,'\tdestroy_workqueue(kacpid_wq);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tlsf_prepaid_acpi_reference_queue_state(false);\n#endif\n'
        '\tdestroy_workqueue(kacpid_wq);\n')


def derive(inputs):
    authenticate(inputs)
    outputs=prior.derive({name:inputs[name] for name in prior.fixture()['source']})
    for name in EXTRAS:outputs[name]=inputs[name]
    header='#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_device_firmware.h>\n#endif\n'
    for name,anchor in ((GLUE,'#include "internal.h"\n'),(BUS,'#include "internal.h"\n'),
        (SCAN,'#include "sleep.h"\n')):
        outputs[name]=replace(inputs[name].decode(),anchor,anchor+header).encode()
    text=replace(inputs[ACPI].decode(),'#include "pci.h"\n','#include "pci.h"\n'+
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_device_private.h>\n'
        '#include <net/lsf_stream_device_firmware.h>\n#endif\n')
    raw=section(inputs[ACPI].decode(),'acpi_pci_find_companion')
    outputs[ACPI]=replace(text,raw,raw+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+companion(raw)+
        '\n#include "../../net/device-acpi-private.c"\n#endif\n').encode()
    for name,function,fragment in ((GLUE,'acpi_find_child_device','device-acpi-child.c'),
        (BUS,'acpi_dev_for_each_child','device-acpi-walk.c')):
        raw=section(inputs[name].decode(),function)
        outputs[name]=replace(outputs[name].decode(),raw,raw+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '#include "../../net/'+fragment+'"\n#endif\n').encode()
    outputs[SCAN]=replace(outputs[SCAN].decode(),'static bool acpi_scan_initialized;\n',
        'static bool acpi_scan_initialized;\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "../../net/device-acpi-lock.c"\n#endif\n').encode()
    text=replace(outputs[SCAN].decode(),'static DEFINE_MUTEX(acpi_device_del_lock);\n',
        'static DEFINE_MUTEX(acpi_device_del_lock);\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        'static unsigned int lsf_acpi_deletions_active;\nstatic bool lsf_acpi_deletion_uncertain;\n#endif\n')
    for name,project in (('acpi_device_del_work_fn',deletion_worker),('acpi_scan_drop_device',deletion_invalidation)):
        raw=section(inputs[SCAN].decode(),name);text=replace(text,raw,project(raw))
    outputs[SCAN]=text.encode()
    text=replace(inputs[OSL].decode(),'#include "internal.h"\n','#include "internal.h"\n'+header)
    raw=section(inputs[OSL].decode(),'acpi_queue_hotplug_work')
    text=replace(text,raw,raw+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "../../net/device-acpi-queue.c"\n#endif\n')
    for name in ('acpi_os_initialize1','acpi_os_terminate'):
        raw=section(inputs[OSL].decode(),name);text=replace(text,raw,queue_lifecycle(raw,name))
    outputs[OSL]=text.encode()
    old=prior.private(prior.fixture()['sections']['pci_setup_device']['text'],'pci_setup_device')
    selected=replace(old,'\tpci_set_acpi_fwnode(dev);\n',
        '\terr = lsf_prepaid_pci_set_acpi_fwnode(dev);\n\tif (err)\n\t\treturn err;\n')
    text=replace(outputs[prior.PCI].decode(),old,selected)
    outputs[prior.PCI]=replace(text,'#include <net/lsf_stream_device_private.h>\n',
        '#include <net/lsf_stream_device_private.h>\n#include <net/lsf_stream_device_firmware.h>\n').encode()
    text=outputs['net/device-prepaid.h'].decode()
    text=replace(text,'    LSF_DEVICE_RX_HEAD\n','    LSF_DEVICE_RX_HEAD,\n    LSF_DEVICE_ACPI_REFERENCE\n')
    outputs['net/device-prepaid.h']=replace(text,'        kind == LSF_DEVICE_RX_HEAD;\n',
        '        kind == LSF_DEVICE_RX_HEAD || kind == LSF_DEVICE_ACPI_REFERENCE;\n').encode()
    text=outputs['net/factory-device.c'].decode()
    text=replace(text,'    unsigned int pci_attempted;\n',
        '    unsigned int pci_attempted, constructor_active;\n    struct lsf_prepaid_ticket firmware;\n')
    text=replace(text,'    if (!lsf_factory_device_pci_ready(domain, bus, devfn)) {\n',
        '    if (!lsf_factory_device_pci_ready(domain, bus, devfn) ||\n'
        '        !lsf_factory_device_firmware_constructor_enter()) {\n')
    text=replace(text,'void lsf_factory_device_pci_leave(void)\n{\n    mutex_unlock(&factory_lock);\n}',
        'void lsf_factory_device_pci_leave(void)\n{\n    mutex_unlock(&factory_lock);\n'
        '    lsf_factory_device_firmware_constructor_leave();\n}')
    text=replace(text,'    int returned = 0;\n    spin_lock_irqsave(&pool_lock, flags);\n',
        '    int returned = 0;\n    int pending = lsf_factory_device_firmware_retire(address);\n'
        '    if (pending)\n        return pending;\n    spin_lock_irqsave(&pool_lock, flags);\n')
    outputs['net/factory-device.c']=text.encode()
    text=replace(outputs['net/factory.c'].decode(),'#include "factory-private.h"\n',
        '#include "factory-private.h"\n#include <linux/acpi.h>\n#include <linux/pci.h>\n'
        '#include <linux/workqueue.h>\n#include <net/lsf_stream_device_firmware.h>\n')
    outputs['net/factory.c']=replace(text,'#include "factory-device.c"\n',
        '#include "factory-device.c"\n#include "factory-device-firmware.c"\n').encode()
    for name in ('device-acpi-child.c','device-acpi-walk.c','device-acpi-lock.c','device-acpi-private.c',
                 'device-acpi-queue.c','factory-device-firmware.c'):
        outputs['net/'+name]=(OWNED/name).read_bytes()
    outputs['include/net/lsf_stream_device_firmware.h']=(OWNED/'device-firmware-private.h').read_bytes()
    return outputs
