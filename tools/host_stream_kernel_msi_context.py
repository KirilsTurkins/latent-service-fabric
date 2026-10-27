"""Closed uninstalled MSI context/devres source prefix after VP430.

No selected owner dispatch is changed. IRQ gate, unproved domain creation,
runtime, complete earlier-helper closure and useful-fit claims stay closed.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_device_security import function
from tools.host_stream_kernel_cleanup_native import require

ROOT=Path(__file__).resolve().parents[1]
INPUT_SHA='0768391742d6748633a9af27da9c5f60430ff37ecca83f74d8d1b60b20ac8441'
PRIMARY={'kernel/irq/msi.c': (49438, '24fd20d5697c8f43bb9ed3b9537adbc8c1934af75ab6212d016319f44f1535d9'), 'drivers/base/devres.c': (32610, '11c8fde49c587a7400c2a8c876a97c7154ba96b32a772b874c83a55e8928db87'), 'drivers/pci/msi/irqdomain.c': (13026, '722e989bfd43d02e7b744aa94c63907e402ca85175635e0781405aa0d40ab1e8'), 'fs/sysfs/group.c': (15872, 'aa24130acd8a256dbc038c9fd65509578453b5212739fdd5291971f163dcb44d')}
PREIMAGES={'drivers/base/core.c': (160572, '21ee5597e0436f66b71433e2b209bc2f8d26127649a9be004aa0c73341037b23'), 'net/factory.c': (38118, 'bf97c3fc8c66801f1b07b7e61a86ec39978f555db8d8e0f393538fb44fbee7ae'), 'net/device-prepaid.h': (19408, '96eac2a06cabc6c359d3300937c07a4762b04bfae1f1bffd22e086a69989ecdd')}
BODIES={'kernel/irq/msi.c::int msi_setup_device_data(': (888, '39367969133e7ef2695b6f6b71deb28ccb8a9a5c25b351994335752a916bc164'), 'kernel/irq/msi.c::static void msi_device_data_release(': (323, '95d37e7c7e03065fbc7e653362dd882cdc92f8c7111c94dbd72ebaa3cff81575'), 'drivers/base/devres.c::void devres_free(': (163, 'bf642c5d28ac19a8df009fed304c26b46dff1287a75afa2f5e6f782c7a1559f1'), 'drivers/base/devres.c::static void release_nodes(': (374, '175e9a631a29124a4ec108ea0e9e70e60ce7e3db48625572161724f21b398127'), 'drivers/pci/msi/irqdomain.c::bool pci_setup_msi_device_domain(': (384, '8c7b9e12aeac16595914676947ded87db43c9ad10a3703bf561c02ef43224806'), 'drivers/pci/msi/irqdomain.c::bool pci_setup_msix_device_domain(': (411, '361534a0cee771ba468043d56a7ef1b9ee80d691166a4721a29639fb082fd471'), 'drivers/base/core.c::int devm_device_add_group(': (420, '74a43dd53d7cc8f3a260191b867f3ee9b166367fb05e1d3d9a15749f6f6c24d6'), 'drivers/base/core.c::static void devm_attr_group_remove(': (271, 'e24fd46526845b699bc19f75aa613438b7b7d5d73110d930bf6d619d0c1a3a71')}
BUNDLE_PATH='research/standard-outbound/linux-6.12-lineage/stream-msi-context-sources.json'
BUNDLE_PIN=(25294, 'fe53902ca7a2b9546abea71797613790addb75fec030bc7d04972ec26749cf42')
MATERIAL_PINS={'include/net/lsf_stream_msi_context_private.h': (2394, '85c00e5a9cde5546d9466620ee52da75e8d5fb3bc093917803ae93552ed3f4ff'), 'net/factory-stream-msi-context.c': (11831, '85d88404b3a275fe131935a0276f26edcdc26a622ad319e7880672a853cbae9b'), 'drivers/base/lsf-stream-msi-devres.c': (4692, '9f6c6c30063c4dc98630c9b254abea2939b058acd1bc4c47dfe92c2ce8339fa8'), 'kernel/irq/lsf-stream-msi-context.c': (3473, '544c1b3c9c01707de564a87d949d4b0659d1e9c0869b898be31ca5e23b99c812'), 'drivers/base/lsf-stream-msi-group.c': (1533, '36195de83204913102209109358ed6ecd0ec254c642a69ecc0ccdb1691062af4')}


def _bound(raw,pin):
    return type(raw) is bytes and len(raw)==pin[0] and hashlib.sha256(raw).hexdigest()==pin[1]


def _pairs(items):
    out={}
    for key,value in items:
        require(key not in out,'msi-material-duplicate-key')
        out[key]=value
    return out


def decode_materials(raw):
    require(_bound(raw,BUNDLE_PIN) and len(raw)<128*1024,'msi-whole-material-container')
    value=json.loads(raw.decode('utf8'),object_pairs_hook=_pairs)
    require(type(value) is dict and set(value)=={'schemaVersion','materials'} and
        type(value['schemaVersion']) is int and value['schemaVersion']==1 and
        type(value['materials']) is list and len(value['materials'])==5,'msi-material-schema')
    out={}
    for row in value['materials']:
        require(type(row) is dict and set(row)=={'path','bytes','sha256','text'},'msi-material-fields')
        name=row['path']
        require(type(name) is str and name in MATERIAL_PINS and name not in out and
            type(row['bytes']) is int and type(row['sha256']) is str and type(row['text']) is str,
            'msi-material-typed-row')
        data=row['text'].encode('utf8')
        require(_bound(data,MATERIAL_PINS[name]) and b'\r' not in data and
            (len(data),hashlib.sha256(data).hexdigest())==(row['bytes'],row['sha256']),
            'msi-material-row-identity')
        out[name]=data
    require(set(out)==set(MATERIAL_PINS),'msi-material-complete-set')
    return out


def materials(root=ROOT):
    path=root/BUNDLE_PATH
    before=path.lstat()
    require(stat.S_ISREG(before.st_mode) and not
        (getattr(before,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400)),
        'msi-material-regular-file')
    flags=os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)
    with os.fdopen(os.open(path,flags),'rb') as source:
        opened=os.fstat(source.fileno())
        require(stat.S_ISREG(opened.st_mode) and
            (opened.st_dev,opened.st_ino)==(before.st_dev,before.st_ino) and not
            (getattr(opened,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400)),
            'msi-material-open-identity')
        raw=source.read(BUNDLE_PIN[0]+1)
    return decode_materials(raw)


def _wrap(original,branch):
    at=original.index('\n{\n')
    return original[:at]+'\n{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+branch+'#endif\n'+original[at+1:]+'}\n'


def _release_nodes(original):
    edit=Editor(original)
    old=original
    a='\tlist_for_each_entry_safe_reverse(dr, tmp, todo, node.entry) {\n'
    b=a+'#ifdef CONFIG_LSF_STREAM_FACTORY\n'
    b+='\t\tint owned = lsf_prepaid_stream_msi_devres_validate(dev, dr, LSF_STREAM_MSI_BEFORE_RELEASE);\n'
    b+='\t\tif (owned < 0) { lsf_factory_stream_constructor_retain_unknown(); continue; }\n#endif\n'
    require(old.count(a)==1,'msi-actual-release-loop')
    changed=old.replace(a,b)
    a='\t\tdr->node.release(dev, dr->data);\n\t\tkfree(dr);'
    b='\t\tdr->node.release(dev, dr->data);\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
    b+='\t\tif (owned) {\n\t\t\t(void)lsf_prepaid_stream_msi_devres_retire(dev, dr, LSF_STREAM_MSI_AFTER_RELEASE);\n'
    b+='\t\t\tcontinue;\n\t\t}\n#endif\n\t\tkfree(dr);'
    require(changed.count(a)==1,'msi-after-real-callback-before-envelope-free')
    edit.edit(old,changed.replace(a,b))
    return edit.finish()


def _device_domain(original):
    return _wrap(original,'\tint selected = lsf_factory_stream_msi_selected(&pdev->dev);\n'
            '\tif (selected) {\n'
            '\t\t/* No original paid device-domain provider exists here. */\n'
            '\t\tif (selected < 0) lsf_factory_stream_constructor_retain_unknown();\n'
            '\t\treturn false;\n\t}\n')


def transform(outputs,primary):
    require(type(outputs) is dict and len(outputs)==430 and
        all(type(n) is str and type(b) is bytes for n,b in outputs.items()),'msi-whole-input-shape')
    encoded=(json.dumps({n:{'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
        for n,b in outputs.items()},sort_keys=True,separators=(',',':'))+'\n').encode()
    require(hashlib.sha256(encoded).hexdigest()==INPUT_SHA,'msi-whole-VP430-input')
    require(type(primary) is dict and set(primary)==set(PRIMARY),'msi-closed-primary-set')
    for n,p in PRIMARY.items():require(_bound(primary[n],p),'msi-exact-native-primary')
    require(not(set(primary)&set(outputs)),'msi-primary-new-to-derived-map')
    for n,p in PREIMAGES.items():require(_bound(outputs[n],p),'msi-whole-derived-preimage')
    source={**outputs,**primary}
    for key,pin in BODIES.items():
        n,prefix=key.split('::',1);text=source[n].decode()
        require(text.count(prefix)==1 and _bound(function(text,prefix).encode(),pin),'msi-full-native-function')
    parts=materials();require(not(set(parts)&set(source)),'msi-new-logical-materials')
    result=dict(source)
    def editor(name,anchor):
        value=Editor(source[name].decode())
        value.edit(anchor,anchor+'#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_msi_context_private.h>\n#endif\n')
        return value
    msi=editor('kernel/irq/msi.c','#include <linux/xarray.h>\n')
    old=function(msi.text,'int msi_setup_device_data(')
    msi.edit(old,_wrap(old,
        '\tint selected = lsf_factory_stream_msi_selected(dev);\n'
        '\tif (selected < 0) return selected;\n'
        '\tif (selected) return lsf_prepaid_stream_msi_setup_device_data(dev);\n'))
    old=function(msi.text,'static void msi_device_data_release(')
    msi.edit(old,_wrap(old,
        '\tunsigned int role;\n'
        '\tint owned = lsf_prepaid_stream_msi_resource_classify(dev, res, &role);\n'
        '\tif (owned < 0 || (!owned && lsf_factory_stream_msi_selected(dev)) ||\n'
        '\t    (owned && (role != LSF_STREAM_MSI_CONTEXT ||\n'
        '\t     !lsf_prepaid_stream_msi_payload_known(dev, res, LSF_STREAM_MSI_BEFORE_RELEASE)))) {\n'
        '\t\tlsf_factory_stream_constructor_retain_unknown(); return;\n\t}\n'))
    msi.edit(msi.text,msi.text+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf-stream-msi-context.c"\n#endif\n')
    result['kernel/irq/msi.c']=msi.finish().encode()
    dr=editor('drivers/base/devres.c','#include <linux/percpu.h>\n')
    old=function(dr.text,'void devres_free(')
    dr.edit(old,_wrap(old,
        '\tif (res) {\n'
        '\t\tstruct devres *owned_dr = container_of(res, struct devres, data);\n'
        '\t\tint owned = lsf_prepaid_stream_msi_devres_validate(NULL, owned_dr, LSF_STREAM_MSI_UNLINKED);\n'
        '\t\tif (owned < 0) { lsf_factory_stream_constructor_retain_unknown(); return; }\n'
        '\t\tif (owned) { (void)lsf_prepaid_stream_msi_devres_retire(NULL, owned_dr, LSF_STREAM_MSI_UNLINKED); return; }\n'
        '\t}\n'))
    old=function(dr.text,'static void release_nodes(')
    dr.edit(old,_release_nodes(old))
    dr.edit(dr.text,dr.text+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf-stream-msi-devres.c"\n#endif\n')
    result['drivers/base/devres.c']=dr.finish().encode()
    core=editor('drivers/base/core.c','#include <linux/device.h>\n')
    core.edit(core.text,core.text+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf-stream-msi-group.c"\n#endif\n')
    result['drivers/base/core.c']=core.finish().encode()
    domain=editor('drivers/pci/msi/irqdomain.c','#include <linux/of_irq.h>\n')
    for prefix in ['bool pci_setup_msi_device_domain(','bool pci_setup_msix_device_domain(']:
        old=function(domain.text,prefix)
        domain.edit(old,_device_domain(old))
    result['drivers/pci/msi/irqdomain.c']=domain.finish().encode()
    kinds=editor('net/device-prepaid.h','#include "prepaid.h"\n')
    kinds.edit('    return kind == LSF_STREAM_VP_VQS ||',
        '    return kind == LSF_STREAM_MSI_CONTEXT_DR || kind == LSF_STREAM_MSI_GROUP_DR ||\n'
        '        kind == LSF_STREAM_VP_VQS ||')
    result['net/device-prepaid.h']=kinds.finish().encode()
    factory=Editor(source['net/factory.c'].decode())
    factory.edit(factory.text,factory.text+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "factory-stream-msi-context.c"\n#endif\n')
    result['net/factory.c']=factory.finish().encode()
    result.update(parts)
    require(len(result)==439,'msi-output-count')
    return result
