"""Uninstalled VP transport bookkeeping after immutable 427-output MMIO stage.

No consumer selects this stage; compile-only qualification is separate.
IRQ, full earlier helper closure, funding,
useful fit, image and native runtime claims remain false.
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
INPUT_SHA='17fb144ef54af90af8ac9c338bcf7315f702bea92049dfcbe1da37e20a9db0a0'
BUNDLE_PATH='research/standard-outbound/linux-6.12-lineage/stream-vp-transport-sources.json'
BUNDLE_PIN=(26247, '9944ebe14f466f6a02e52d574f1ce86d79bc3f73ea32905bb705b689a5a1da58')
MATERIAL_PINS={'include/net/lsf_stream_vp_transport_private.h': (1232, 'b40baa9354a75bdb5d42a242705f8e46b99223995231c18094fc7f3dbf25451d'), 'net/factory-stream-vp-transport.c': (6380, 'd462377d2099d640fb79773830d0ca9d4917326bbe94e28c78eaf9250262bd58'), 'drivers/virtio/lsf-stream-vp-transport.c': (16805, 'ff65229176d0add6e8063ef67a4b2dff695ac32d9f7caca898649b9d812be9d9')}
PREIMAGES={'net/factory.c': (38036, 'a7b269ee70a45d3c2e0555156e5e41c4162e7e63b8c5a6c32bd5fc05e23fe219'), 'net/device-prepaid.h': (19222, 'f306e163cde4eab5e2c0efabebac8bde49b1c4cc73c443f47c1a2139596f46b6'), 'drivers/virtio/virtio_pci_common.c': (30067, 'c92dee5ebf943af5b938fbc909c6237d74e88c63b2edf73c39e05c6abaabe5ab')}
BODIES={'static int vp_request_msix_vectors(': (1962, '9b08aea69c155ff606eeba250bf7116bb4c6a8f5f7b474892735721d655fc48b'), 'static struct virtqueue *vp_setup_vq(': (1028, '0afc6ea1f0bdda2febb2d13e5e287dadb1f07b4a423234929c7aa31dd63bbe08'), 'static void vp_del_vq(': (471, '3fabf7c5d651a753db049bd92002605189c45ae206000d8742e669aecab071be'), 'void vp_del_vqs(': (1429, '71ab291b234ee8c21a3f662df0fcaa67b7a6a8be28ca1132cb6c1f3cca5873dc'), 'static struct virtqueue *\nvp_find_one_vq_msix(': (1380, '3a7e98aae84a7b59246d9715e385455bb75597c6b41896bc99c9b050e766fbb4'), 'static int vp_find_vqs_msix(': (2073, 'c1adb5e6d2725697223e66ab44f6450ad324e8a7b906df17446ca575fc51f7da'), 'static int vp_find_vqs_intx(': (1440, '995fe7faa7b63f0f24ea7a48e600332fca06b6695a7f55aea86f6975924fe27b'), 'int vp_find_vqs(': (969, '19b2d4a59bdc65cbc6831afe75e35c362c936501b81684f7c7d149030f2d3ed2')}


def _bound(raw,pin):
    return type(raw) is bytes and len(raw)==pin[0] and hashlib.sha256(raw).hexdigest()==pin[1]


def _pairs(rows):
    value={}
    for key,item in rows:
        require(key not in value,'vp-material-duplicate-key')
        value[key]=item
    return value


def decode_materials(raw):
    require(_bound(raw,BUNDLE_PIN) and len(raw)<128*1024,'vp-whole-material-container')
    value=json.loads(raw.decode('utf-8'),object_pairs_hook=_pairs)
    require(type(value) is dict and set(value)=={'schemaVersion','materials'} and
        type(value['schemaVersion']) is int and value['schemaVersion']==1 and
        type(value['materials']) is list and len(value['materials'])==3,'vp-material-schema')
    result={}
    for row in value['materials']:
        require(type(row) is dict and set(row)=={'path','bytes','sha256','text'},'vp-material-fields')
        name=row['path']
        require(type(name) is str and name in MATERIAL_PINS and name not in result and
            type(row['bytes']) is int and type(row['sha256']) is str and type(row['text']) is str,
            'vp-material-typed-identity')
        data=row['text'].encode('utf-8')
        require(_bound(data,MATERIAL_PINS[name]) and (len(data),hashlib.sha256(data).hexdigest())==
            (row['bytes'],row['sha256']) and b'\r' not in data,'vp-material-row-identity')
        result[name]=data
    require(set(result)==set(MATERIAL_PINS),'vp-material-complete-set')
    return result


def materials(root=ROOT):
    path=root/BUNDLE_PATH
    before=path.lstat()
    require(stat.S_ISREG(before.st_mode) and
        not (getattr(before,'st_file_attributes',0) & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400)),
        'vp-material-regular-nonsymlink-file')
    # NOFOLLOW/NONBLOCK also close the lstat/open race on hosts providing them.
    flags=os.O_RDONLY | getattr(os,'O_BINARY',0) | getattr(os,'O_NOFOLLOW',0) | getattr(os,'O_NONBLOCK',0)
    descriptor=os.open(path,flags)
    with os.fdopen(descriptor,'rb') as source:
        opened=os.fstat(source.fileno())
        require(stat.S_ISREG(opened.st_mode) and
            (opened.st_dev,opened.st_ino)==(before.st_dev,before.st_ino) and
            not (getattr(opened,'st_file_attributes',0) & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400)),
            'vp-material-file-identity-changed')
        raw=source.read(BUNDLE_PIN[0]+1)
    return decode_materials(raw)


def _wrap(original,branch):
    at=original.index('\n{\n')
    return original[:at]+'\n{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+branch+\
        '#endif\n'+original[at+1:]+'}\n'


def transform(outputs):
    require(type(outputs) is dict and len(outputs)==427 and
        all(type(n) is str and type(b) is bytes for n,b in outputs.items()),'vp-full-input-shape')
    encoded=(json.dumps({n:{'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
        for n,b in outputs.items()},sort_keys=True,separators=(',',':'))+'\n').encode()
    require(hashlib.sha256(encoded).hexdigest()==INPUT_SHA,'vp-whole-input-identity')
    for n,pin in PREIMAGES.items():require(_bound(outputs[n],pin),'vp-whole-TU-preimage')
    payload=materials()
    require(not(set(payload)&set(outputs)),'vp-new-logical-materials-only')
    result=dict(outputs)
    native=Editor(outputs['drivers/virtio/virtio_pci_common.c'].decode())
    for signature,pin in BODIES.items():
        require(native.text.count(signature)==1 and
            _bound(function(native.text,signature).encode(),pin),'vp-full-native-body')
    native.edit('#include <net/lsf_stream_constructor_mmio_private.h>\n',
        '#include <net/lsf_stream_constructor_mmio_private.h>\n#include <net/lsf_stream_vp_transport_private.h>\n')
    original=function(native.text,'int vp_find_vqs(')
    native.edit(original,_wrap(original,"""
\tint selected = lsf_factory_stream_vp_transport_selected(vdev);
\tif (selected < 0) return selected;
\tif (selected) return lsf_prepaid_stream_vp_find_vqs(vdev, nvqs, vqs, vqs_info, desc);
"""))
    original=function(native.text,'void vp_del_vqs(')
    native.edit(original,_wrap(original,"""
\tint selected = lsf_factory_stream_vp_transport_selected(vdev);
\tif (selected < 0) { lsf_factory_stream_constructor_retain_unknown(); return; }
\tif (selected) { lsf_prepaid_stream_vp_del_vqs(vdev); return; }
"""))
    native.edit(native.text,native.text+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf-stream-vp-transport.c"\n#endif\n')
    result['drivers/virtio/virtio_pci_common.c']=native.finish().encode()
    device=Editor(outputs['net/device-prepaid.h'].decode())
    device.edit('#include "prepaid.h"\n','#include "prepaid.h"\n#include <net/lsf_stream_vp_transport_private.h>\n')
    device.edit('    return kind == LSF_DEVICE_VIRTIO_CORE ||',
        '    return kind == LSF_STREAM_VP_VQS || kind == LSF_STREAM_VP_NAMES ||\n'
        '        kind == LSF_STREAM_VP_MASKS || kind == LSF_STREAM_VP_INFO ||\n'
        '        kind == LSF_DEVICE_VIRTIO_CORE ||')
    result['net/device-prepaid.h']=device.finish().encode()
    factory=Editor(outputs['net/factory.c'].decode())
    factory.edit(factory.text,factory.text+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "factory-stream-vp-transport.c"\n#endif\n')
    result['net/factory.c']=factory.finish().encode()
    result.update(payload)
    require(len(result)==430,'vp-derived-output-count')
    return result
